"""Codex как исполнитель шагов с суждением: библия, карточки сцен, стиль из книги.

Итог задания определяет не Codex, а валидатор. Codex падает молча — файла просто нет, а код
возврата нулевой, — и это правило проекта, а не редкий случай. Поэтому после каждой попытки
проверяется результат на диске и то, что в дереве изменилось только ожидаемое; провал даёт
одну повторную попытку, в инструкцию дословно дописываются претензии валидатора.

Дерево во время работы почти всегда грязное, поэтому «посторонние изменения» ищутся не по
факту правок, а по разнице двух снимков `git status --porcelain` — до запуска и после.

Только стандартная библиотека.
"""
import shlex
import string
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import settings as panel_settings

ROOT = Path(__file__).resolve().parents[1]
TASKS = Path(__file__).resolve().parent / 'tasks'


def instruction(kind, fields, tasks=TASKS):
    """Инструкция из шаблона `tasks/<kind>.md`. Подстановка `$поле`, а не `{поле}`: в шаблонах
    есть фигурные скобки JSON, и формат с фигурными скобками на них спотыкается."""
    template = Path(tasks) / f'{kind}.md'
    if not template.is_file():
        raise FileNotFoundError(f'нет шаблона задания: {template}')
    return string.Template(template.read_text(encoding='utf-8')).safe_substitute(fields)


def git_status(root=ROOT):
    """Снимок дерева: множество строк `git status --porcelain`."""
    done = subprocess.run(['git', 'status', '--porcelain'], cwd=str(root),
                          capture_output=True, text=True)
    return {line for line in done.stdout.splitlines() if line.strip()}


def _path_of(line):
    """Путь из строки porcelain: два знака статуса, пробел, путь; переименование — справа."""
    path = line[3:]
    if ' -> ' in path:
        path = path.split(' -> ', 1)[1]
    return path.strip().strip('"')


def stray_changes(before, after, expected):
    """Изменения вне ожидаемых путей. `expected` — префиксы путей от корня репозитория."""
    out = []
    for line in sorted(after - before):
        path = _path_of(line)
        if not any(path.startswith(prefix) for prefix in expected):
            out.append(f'посторонняя правка в дереве: {path} — задание меняет только '
                       f'{", ".join(expected)}')
    return out


def codex_command(prompt, root=ROOT, config=None):
    config = config or panel_settings.load(root)
    fill = {'{root}': str(root), '{prompt}': prompt}
    return [fill.get(arg, arg) for arg in config['codex_cmd']]


def run_codex(prompt, root=ROOT, config=None, log=None, watch=None):
    """Один запуск Codex. stdin закрыт: с открытым stdin `codex exec` виснет.

    `watch` получает запущенный процесс — так очередь может его убить по «снять задание».
    """
    config = config or panel_settings.load(root)
    command = codex_command(prompt, root, config)
    started = time.monotonic()
    timeout = int(config.get('timeout', 1200))
    if log is not None:
        _append(log, f'$ {shlex.join(command[:-1])} <инструкция>\n')
    process = subprocess.Popen(command, cwd=str(root), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, bufsize=1)
    if watch is not None:
        watch(process)
    # Вывод пишется построчно, а не одним куском в конце: кадр идёт минуты, и хвост лога
    # в панели должен что-то показывать всё это время.
    killed = threading.Event()
    killer = threading.Timer(timeout, lambda: (killed.set(), process.kill()))
    killer.start()
    lines = []
    try:
        for line in process.stdout:
            lines.append(line)
            if log is not None:
                _append(log, line)
        process.wait()
    finally:
        killer.cancel()
        if watch is not None:
            watch(None)
    output = ''.join(lines)
    code = None if killed.is_set() else process.returncode
    if killed.is_set():
        output += f'\n— таймаут {timeout} с, процесс убит'
    spent = time.monotonic() - started
    if log is not None:
        _append(log, f'— код {code}, {spent:.0f} с\n')
    return code, output, spent


def _append(log, text):
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('a', encoding='utf-8') as fh:
        fh.write(text)


def retry_note(complaints):
    return ('\n\n## Прошлая попытка не прошла проверку\n\n'
            'Претензии проверяющего, дословно:\n\n'
            + '\n'.join(f'- {c}' for c in complaints)
            + '\n\nИсправь ровно это и не переделывай остальное.\n')


def run(kind, fields, validate, expected, root=ROOT, config=None, log=None, watch=None):
    """Задание с суждением: инструкция → Codex → проверка → при провале одна повторная попытка.

    `validate` — функция без аргументов, возвращающая список претензий (пустой = годно).
    `expected` — префиксы путей от корня репозитория, которые заданию позволено менять.
    Возвращает отчёт: прошло ли, сколько попыток, претензии последней попытки.
    """
    root = Path(root)
    config = config or panel_settings.load(root)
    attempts = max(1, int(config.get('attempts', 2)))
    base = instruction(kind, fields)
    complaints, tries = [], []
    # Снимок дерева один на всё задание, а не на попытку: иначе посторонняя правка первой
    # попытки становится фоном второй и уже не видна.
    before = git_status(root)

    for attempt in range(1, attempts + 1):
        prompt = base if attempt == 1 else base + retry_note(complaints)
        if log is not None:
            _append(log, f'\n=== попытка {attempt} из {attempts}, '
                         f'{datetime.now():%Y-%m-%d %H:%M:%S} ===\n')
            _append(Path(log).with_suffix('.prompt.txt'),
                    f'=== попытка {attempt} ===\n{prompt}\n')
        code, output, spent = run_codex(prompt, root, config, log, watch)
        try:
            complaints = list(validate())
        except Exception as error:
            # Неразбираемый JSON — самый вероятный плохой исход, и это претензия к попытке,
            # а не крах задания: иначе повтор, существующий ровно для этого, не наступит.
            complaints = [f'результат не читается: {type(error).__name__}: {error} — '
                          f'файл должен существовать и разбираться как JSON']
        complaints += stray_changes(before, git_status(root), expected)
        tries.append({'attempt': attempt, 'returncode': code, 'seconds': round(spent),
                      'complaints': complaints})
        if log is not None:
            _append(log, 'проверка: годно\n' if not complaints
                    else 'проверка: ' + '\n'.join(f'  ! {c}' for c in complaints) + '\n')
        if not complaints:
            return {'ok': True, 'attempts': attempt, 'complaints': [], 'tries': tries}
    return {'ok': False, 'attempts': attempts, 'complaints': complaints, 'tries': tries}
