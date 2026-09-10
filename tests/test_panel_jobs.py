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
