"""Очередь заданий: порядок, состояния, разбор после падения, снятие.

Codex здесь не нужен: обработчик — обычная функция, и проверяется именно очередь.
"""
import threading
import time

import jobs


def queue(tmp_path, handlers):
    return jobs.Queue(root=tmp_path, handlers=handlers)


def test_job_is_written_to_a_file_and_read_back(tmp_path):
    q = queue(tmp_path, {'ping': lambda job, tools: {'ok': True}})
    job = q.add('ping', {'key': 'darrow'}, label='darrow')
    assert q.file_of(job['id']).is_file()
    assert q.get(job['id'])['status'] == jobs.QUEUED
    assert job['kind'] == 'ping' and job['args'] == {'key': 'darrow'}
    assert job['id'].endswith('-ping-darrow')


def test_unknown_kind_is_refused_at_the_door(tmp_path):
    q = queue(tmp_path, {})
    try:
        q.add('nonesuch')
    except KeyError as error:
        assert 'nonesuch' in str(error)
    else:
        raise AssertionError('задание неизвестного вида приняли в очередь')


def test_worker_runs_the_job_and_marks_it_done(tmp_path):
    q = queue(tmp_path, {'ping': lambda job, tools: {'ok': True, 'said': job['args']['say']}})
    q.start()
    job = q.wait(q.add('ping', {'say': 'привет'})['id'], timeout=5)
    q.stop()
    assert job['status'] == jobs.DONE
    assert job['result'] == {'ok': True, 'said': 'привет'}
    assert job['attempts'] == 1 and job['started'] and job['finished']


def test_handler_that_raises_gives_failed_with_the_reason(tmp_path):
    def boom(job, tools):
        raise ValueError('обработчик упал')

    q = queue(tmp_path, {'boom': boom})
    q.start()
    job = q.wait(q.add('boom')['id'], timeout=5)
    q.stop()
    assert job['status'] == jobs.FAILED
    assert 'обработчик упал' in job['error']
    assert 'обработчик упал' in q.tail(job['id'])


def test_report_with_ok_false_is_a_failure_not_a_success(tmp_path):
    """Раннер агента возвращает отчёт, а не исключение: неудача видна по полю, не по падению."""
    q = queue(tmp_path, {'agent': lambda job, tools: {'ok': False, 'complaints': ['локатор пуст']}})
    q.start()
    job = q.wait(q.add('agent')['id'], timeout=5)
    q.stop()
    assert job['status'] == jobs.FAILED and 'локатор пуст' in job['error']


def test_jobs_run_one_at_a_time_in_order(tmp_path):
    seen, busy = [], []

    def slow(job, tools):
        busy.append(job['id'])
        assert len(busy) == 1, 'два задания пошли разом'
        time.sleep(0.05)
        seen.append(job['args']['n'])
        busy.pop()
        return {'ok': True}

    q = queue(tmp_path, {'slow': slow})
    ids = [q.add('slow', {'n': n})['id'] for n in range(4)]
    q.start()
    for job_id in ids:
        q.wait(job_id, timeout=10)
    q.stop()
    assert seen == [0, 1, 2, 3]


def test_queued_job_can_be_taken_off_the_queue(tmp_path):
    gate = threading.Event()
    q = queue(tmp_path, {'hold': lambda job, tools: (gate.wait(5), {'ok': True})[1]})
    first = q.add('hold')
    second = q.add('hold')
    q.start()
    time.sleep(0.1)
    assert q.cancel(second['id'])['status'] == jobs.CANCELLED
    gate.set()
    q.wait(first['id'], timeout=5)
    q.stop()
    assert q.get(first['id'])['status'] == jobs.DONE
    assert q.get(second['id'])['status'] == jobs.CANCELLED


def test_running_job_is_cancelled_and_its_process_killed(tmp_path):
    import subprocess
    import sys

    def sleeper(job, tools):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        tools.watch(process)
        return {'ok': process.wait() == 0, 'code': process.returncode}

    q = queue(tmp_path, {'sleep': sleeper})
    q.start()
    job = q.add('sleep')
    time.sleep(0.4)
    q.cancel(job['id'])
    done = q.wait(job['id'], timeout=10)
    q.stop()
    assert done['status'] == jobs.CANCELLED and done['error'] == 'снято человеком'


def test_running_handler_sees_the_cancel_flag(tmp_path):
    """Обработчик обязан узнать о снятии сам: раннер агента по этому флагу гасит повтор."""
    saw, gate = [], threading.Event()

    def watcher(job, tools):
        gate.wait(5)
        saw.append(tools.stopped())
        return {'ok': True}

    q = queue(tmp_path, {'watch': watcher})
    q.start()
    job = q.add('watch')
    time.sleep(0.2)
    q.cancel(job['id'])
    gate.set()
    q.wait(job['id'], timeout=5)
    q.stop()
    assert saw == [True]


def test_restart_marks_running_interrupted_and_requeues_the_waiting(tmp_path):
    q = queue(tmp_path, {'ping': lambda job, tools: {'ok': True}})
    crashed = q.add('ping')
    waiting = q.add('ping')
    q._write({**q.get(crashed['id']), 'status': jobs.RUNNING, 'started': '2026-09-10T12:00:00'})

    fresh = queue(tmp_path, {'ping': lambda job, tools: {'ok': True}})
    fresh.recover()
    assert fresh.get(crashed['id'])['status'] == jobs.INTERRUPTED
    assert 'остановилась на ходу' in fresh.get(crashed['id'])['error']
    fresh.start()
    assert fresh.wait(waiting['id'], timeout=5)['status'] == jobs.DONE
    fresh.stop()


def test_restart_fails_a_queued_job_whose_kind_is_gone(tmp_path):
    q = queue(tmp_path, {'ping': lambda job, tools: {'ok': True}})
    job = q.add('ping')
    fresh = jobs.Queue(root=tmp_path, handlers={})
    fresh.recover()
    assert fresh.get(job['id'])['status'] == jobs.FAILED


def test_listing_is_newest_first(tmp_path):
    q = queue(tmp_path, {'ping': lambda job, tools: {'ok': True}})
    ids = [q.add('ping', label=str(n))['id'] for n in range(3)]
    listed = [j['id'] for j in q.all()]
    assert listed == sorted(ids, reverse=True)
    assert len(q.all(limit=2)) == 2


# — несколько полос —

def locks(kind, args):
    """Та же таблица, что в панели, только короче: книга общая, правка — исключительная."""
    slug, key = args.get('slug', ''), args.get('key', '')
    if kind == 'bible-entry':
        return (f'книга:{slug}',), (f'библия:{slug}',)
    if kind == 'sheet':
        return (f'книга:{slug}',), (f'лист:{slug}/{key}',)
    if kind == 'ingest':
        return (), (f'книга:{slug}',)
    return (), ('всё',)


def until(check, limit=4.0):
    waited = 0.0
    while waited < limit and not check():
        time.sleep(0.05)
        waited += 0.05
    return check()


def busy_queue(tmp_path, width, hold):
    """Очередь, где обработчик держит задание, пока его не отпустят."""
    started, release = [], threading.Event()

    def handler(job, tools):
        started.append(job['args'].get('key') or job['args'].get('slug'))
        release.wait(timeout=hold)
        return {'ok': True}

    q = jobs.Queue(root=tmp_path, handlers={k: handler for k in
                                            ('bible-entry', 'sheet', 'ingest')},
                   locks=locks, width=width)
    return q, started, release


def test_jobs_that_share_a_file_still_go_one_at_a_time(tmp_path):
    """Две записи героев одной книги правят один `bible.json`: рядом им нельзя."""
    q, started, release = busy_queue(tmp_path, width=3, hold=5)
    q.add('bible-entry', {'slug': 'kniga', 'key': 'a'})
    q.add('bible-entry', {'slug': 'kniga', 'key': 'b'})
    q.start()
    time.sleep(0.4)
    assert len(q.running()) == 1, 'взяли обе записи одной книги разом'
    release.set()
    assert until(lambda: len(started) == 2), f'вторая запись не пошла: {started}'
    q.stop()
    assert sorted(started) == ['a', 'b']


def test_jobs_that_share_nothing_go_side_by_side(tmp_path):
    """Листы независимы: каждый пишет свою картинку в кеш."""
    q, started, release = busy_queue(tmp_path, width=3, hold=5)
    for key in ('a', 'b', 'c'):
        q.add('sheet', {'slug': 'kniga', 'key': key})
    q.start()
    assert until(lambda: len(q.running()) == 3), f'рядом пошло только {len(q.running())}'
    release.set()
    q.stop()


def test_width_is_the_ceiling(tmp_path):
    q, started, release = busy_queue(tmp_path, width=2, hold=5)
    for key in ('a', 'b', 'c', 'd'):
        q.add('sheet', {'slug': 'kniga', 'key': key})
    q.start()
    assert until(lambda: len(q.running()) == 2)
    time.sleep(0.3)
    assert len(q.running()) == 2, 'взяли больше, чем разрешено'
    release.set()
    q.stop()


def test_a_blocked_job_does_not_block_the_one_behind_it(tmp_path):
    """Задание, чьи замки заняты, не снимается с очереди, а пропускается: иначе одна
    книга держала бы всю панель, пока её герои собираются по одному."""
    q, started, release = busy_queue(tmp_path, width=2, hold=5)
    q.add('bible-entry', {'slug': 'kniga', 'key': 'a'})
    q.add('bible-entry', {'slug': 'kniga', 'key': 'b'})     # ждёт первого
    q.add('sheet', {'slug': 'kniga', 'key': 'c'})           # спорить не с кем
    q.start()
    assert until(lambda: len(started) == 2), f'пошли {started}'
    assert sorted(started) == ['a', 'c'], f'пошли {started}'
    release.set()
    q.stop()


def test_parsing_a_book_holds_it_whole(tmp_path):
    """Разбор правит книгу целиком: рядом с ним по ней нельзя ничего."""
    q, started, release = busy_queue(tmp_path, width=3, hold=5)
    q.add('ingest', {'slug': 'kniga'})
    q.add('sheet', {'slug': 'kniga', 'key': 'a'})
    q.add('sheet', {'slug': 'drugaya', 'key': 'a'})         # другая книга — можно
    q.start()
    assert until(lambda: len(q.running()) == 2)
    time.sleep(0.3)
    assert len(q.running()) == 2 and 'kniga' in started
    release.set()
    q.stop()


def test_a_waiting_job_says_what_holds_it(tmp_path):
    """«Ждёт очереди» при трёх полосах ничего не объясняет: рядом не идёт не потому,
    что нельзя, а потому что занят файл. Очередь должна назвать какой и кем."""
    q, started, release = busy_queue(tmp_path, width=3, hold=5)
    first = q.add('bible-entry', {'slug': 'kniga', 'key': 'grace'})
    second = q.add('bible-entry', {'slug': 'kniga', 'key': 'rocky'})
    free = q.add('sheet', {'slug': 'kniga', 'key': 'rocky'})
    q.start()
    assert until(lambda: len(q.running()) == 2)

    held = q.blocked_by(q.get(second['id']))
    assert len(held) == 1
    assert held[0]['lock'] == 'библия:kniga' and held[0]['job'] == first['id']
    assert not q.blocked_by(q.get(free['id'])) or free['id'] in q.running()
    assert jobs.subject_of(q.get(first['id'])) == 'grace'
    release.set()
    q.stop()


def test_a_job_file_is_never_read_half_written(tmp_path):
    """`write_text` сначала обрезает файл, потом пишет: между этими мгновениями читатель
    видит пустышку. При одной полосе это почти не случалось, при нескольких — сразу, и
    тесты очереди посыпались в контейнере с «Expecting value: line 1 column 1»."""
    q = jobs.Queue(root=tmp_path, handlers={'ingest': lambda job, tools: {'ok': True}})
    job = q.add('ingest', {'slug': 'kniga'})
    beda = []

    def читаем():
        for _ in range(400):
            try:
                if q.get(job['id']) is None:
                    beda.append('задание пропало')
            except Exception as error:
                beda.append(f'{type(error).__name__}: {error}')
                return

    def пишем():
        for n in range(400):
            job['attempts'] = n
            q._write(job)

    reader = threading.Thread(target=читаем)
    reader.start()
    пишем()
    reader.join(timeout=10)
    assert not beda, beda[:3]
