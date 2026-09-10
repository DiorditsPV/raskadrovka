"""Очередь заданий панели: один рабочий поток, задания по одному, состояние — файлы в `cache/`.

Один поток нарочно. Codex один, кадры идут по одному, и очередь, которую видно сверху вниз,
читается человеком без объяснений. Быстрые детерминированные шаги — разбор, индекс, сборка
промпта, регистрация — идут через ту же очередь, чтобы порядок был один и лог общий.

Состояние живёт в файлах `cache/panel/jobs/<id>.json`, а не в памяти: панель — не сервер
с базой, а окно в репозиторий, и после падения должно быть видно, на чём всё встало.
Задание в `running` при старте помечается `interrupted`; задание в `queued` возвращается
в очередь — перезапуск панели дело обычное и не должен тихо терять работу.

Только стандартная библиотека.
"""
import json
import threading
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

QUEUED, RUNNING, DONE, FAILED, INTERRUPTED, CANCELLED = (
    'queued', 'running', 'done', 'failed', 'interrupted', 'cancelled')
OPEN_STATUSES = (QUEUED, RUNNING)


def _now():
    return datetime.now().isoformat(timespec='seconds')


class Tools:
    """То, что рабочий поток даёт обработчику: путь лога и способ отдать процесс на убийство."""

    def __init__(self, queue, job, stop=None):
        self.queue = queue
        self.job = job
        self.log = queue.log_of(job['id'])
        self._stop = stop or threading.Event()

    def stopped(self):
        """Задание сняли на ходу. Обработчик обязан спрашивать: убитый процесс сам по себе
        выглядит как неудачная попытка, и без этого флага раннер начнёт следующую."""
        return self._stop.is_set()

    def watch(self, process):
        self.queue._watch(self.job['id'], process)

    def say(self, text):
        self.log.parent.mkdir(parents=True, exist_ok=True)
        with self.log.open('a', encoding='utf-8') as fh:
            fh.write(f'{text}\n')


class Queue:
    """Очередь заданий. `handlers` — `{kind: обработчик(job, tools) -> результат}`."""

    def __init__(self, root=ROOT, handlers=None):
        self.root = Path(root)
        self.dir = self.root / 'cache' / 'panel' / 'jobs'
        self.handlers = dict(handlers or {})
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._order = deque()
        self._process = None
        self._current = None
        self._stop_current = None
        self._worker = None

    # — файлы —

    def file_of(self, job_id):
        return self.dir / f'{job_id}.json'

    def log_of(self, job_id):
        return self.dir / f'{job_id}.log'

    def _write(self, job):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file_of(job['id']).write_text(
            json.dumps(job, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return job

    def get(self, job_id):
        file = self.file_of(job_id)
        return json.loads(file.read_text(encoding='utf-8')) if file.is_file() else None

    def all(self, limit=None):
        if not self.dir.is_dir():
            return []
        jobs = [json.loads(f.read_text(encoding='utf-8')) for f in self.dir.glob('*.json')]
        jobs.sort(key=lambda j: j['id'], reverse=True)
        return jobs[:limit] if limit else jobs

    def tail(self, job_id, lines=200):
        log = self.log_of(job_id)
        if not log.is_file():
            return ''
        return '\n'.join(log.read_text(encoding='utf-8', errors='replace').splitlines()[-lines:])

    # — жизнь задания —

    def _new_id(self, kind, label):
        stamp = datetime.now().strftime('%Y%m%d-%H%M-%S')
        tail = f'-{label}' if label else ''
        job_id = f'{stamp}-{kind}{tail}'
        n = 2
        while self.file_of(job_id).exists():
            job_id = f'{stamp}-{kind}{tail}-{n}'
            n += 1
        return job_id

    def add(self, kind, args=None, label=None):
        if kind not in self.handlers:
            raise KeyError(f'нет обработчика для задания «{kind}»')
        with self._lock:
            job = {'id': self._new_id(kind, label), 'kind': kind, 'args': dict(args or {}),
                   'status': QUEUED, 'created': _now(), 'started': None, 'finished': None,
                   'attempts': 0, 'error': None, 'result': None}
            job['log'] = str(self.log_of(job['id']).relative_to(self.root))
            self._write(job)
            self._order.append(job['id'])
        self._wake.set()
        return job

    def cancel(self, job_id):
        """Из очереди — снять; на ходу — убить процесс. Файл-результат, если успел, остаётся."""
        with self._lock:
            job = self.get(job_id)
            if job is None:
                return None
            if job['status'] == QUEUED:
                if job_id in self._order:
                    self._order.remove(job_id)
                job.update(status=CANCELLED, finished=_now())
                return self._write(job)
            if job['status'] == RUNNING and self._current == job_id:
                job['error'] = 'снято человеком'
                self._write(job)
                if self._stop_current is not None:
                    self._stop_current.set()
                if self._process is not None and self._process.poll() is None:
                    self._process.kill()
                return job
            return job

    def recover(self):
        """Разбор после падения: `running` → `interrupted`, `queued` возвращается в очередь."""
        restored = []
        with self._lock:
            for job in sorted(self.all(), key=lambda j: j['id']):
                if job['status'] == RUNNING:
                    job.update(status=INTERRUPTED, finished=_now(),
                               error='панель остановилась на ходу')
                    self._write(job)
                    restored.append(job)
                elif job['status'] == QUEUED:
                    if job['kind'] in self.handlers:
                        self._order.append(job['id'])
                        restored.append(job)
                    else:
                        job.update(status=FAILED, finished=_now(),
                                   error=f'нет обработчика для задания «{job["kind"]}»')
                        self._write(job)
        if self._order:
            self._wake.set()
        return restored

    # — рабочий поток —

    def _watch(self, job_id, process):
        with self._lock:
            if self._current == job_id:
                self._process = process

    def _take(self):
        with self._lock:
            while self._order:
                job = self.get(self._order.popleft())
                if job is not None and job['status'] == QUEUED:
                    job.update(status=RUNNING, started=_now(), attempts=job['attempts'] + 1)
                    self._current, self._process = job['id'], None
                    self._stop_current = threading.Event()
                    return self._write(job)
            return None

    def _finish(self, job, status, result=None, error=None):
        with self._lock:
            fresh = self.get(job['id']) or job
            # «Снято человеком» проставляет cancel(), пока задание ещё бежит: не затираем.
            if fresh.get('error') == 'снято человеком':
                status, error = CANCELLED, 'снято человеком'
            fresh.update(status=status, finished=_now(), result=result, error=error)
            self._current, self._process, self._stop_current = None, None, None
            return self._write(fresh)

    def run_one(self, job):
        """Одно задание целиком. Вынесено отдельно: так его можно позвать из теста без потока."""
        tools = Tools(self, job, self._stop_current)
        try:
            result = self.handlers[job['kind']](job, tools)
        except Exception:                                   # обработчик — чужой код
            report = traceback.format_exc()
            tools.say(report)
            return self._finish(job, FAILED, error=report.strip().splitlines()[-1])
        if isinstance(result, dict) and result.get('ok') is False:
            return self._finish(job, FAILED, result=result,
                                error='; '.join(result.get('complaints') or []) or 'не прошло')
        return self._finish(job, DONE, result=result)

    def _loop(self):
        while not self._stop.is_set():
            job = self._take()
            if job is None:
                self._wake.wait(timeout=0.5)
                self._wake.clear()
                continue
            self.run_one(job)

    def start(self):
        if self._worker is None or not self._worker.is_alive():
            self._stop.clear()
            self._worker = threading.Thread(target=self._loop, name='raskadrovka-jobs',
                                            daemon=True)
            self._worker.start()
        return self._worker

    def stop(self, timeout=2):
        self._stop.set()
        self._wake.set()
        if self._worker is not None:
            self._worker.join(timeout=timeout)

    def wait(self, job_id, timeout=60):
        """Дождаться конца задания — для тестов и синхронных вызовов."""
        end = threading.Event()
        waited = 0.0
        while waited < timeout:
            job = self.get(job_id)
            if job and job['status'] not in OPEN_STATUSES:
                return job
            end.wait(0.05)
            waited += 0.05
        return self.get(job_id)
