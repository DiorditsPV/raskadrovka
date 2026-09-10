"""Сервер панели: маршруты, задание через очередь, и то, что наружу не выходит.

Репозиторий временный, Codex поддельный. Проверяется, что сервер отвечает из файлов и что
раздача файлов не выпускает текст книги: право на текст у нас на чтение, не на раздачу.
"""
import http.client
import json
import subprocess
import sys
import threading

import pytest

import server as panel_server

SLUG = 'test-book'
FAKE = '''import json, os, sys
from pathlib import Path

root, desk = Path(sys.argv[1]), Path(os.environ['FAKE_CODEX_DESK'])
bible = root / 'books' / '%s' / 'bible.json'
data = json.loads(bible.read_text())
data['characters']['hero'] = json.loads((desk / 'entry.json').read_text())
bible.write_text(json.dumps(data, ensure_ascii=False, indent=2))
''' % SLUG

ENTRY = {'name': 'Герой', 'appearance': 'Описание для человека.',
         'appearance_en': 'a description for the prompt',
         'locators': [{'chapter': 1, 'paragraphs': [1, 2]}],
         'audit': {'age': 1, 'build': 1, 'face': 1, 'eyes': 0.5, 'hair': 1,
                   'skin': 1, 'clothing': 1, 'gear': 1, 'marks': 1, 'bearing': 0.5},
         'understanding': 9.0}

PARAGRAPHS = [{'i': 0, 'chapter': 1, 'text': 'Первый абзац.'},
              {'i': 1, 'chapter': 1, 'text': 'Второй абзац, в нём про волосы.'}]

PNG = bytes.fromhex('89504e470d0a1a0a0000000d494844520000000100000001080600000'
                    '01f15c4890000000a49444154789c6300010000050001')


@pytest.fixture
def live(tmp_path, monkeypatch):
    """Поднятый сервер на свободном порту поверх временного репозитория."""
    desk = tmp_path / 'desk'
    desk.mkdir()
    (desk / 'entry.json').write_text(json.dumps(ENTRY, ensure_ascii=False), encoding='utf-8')
    (desk / 'fake_codex.py').write_text(FAKE, encoding='utf-8')
    monkeypatch.setenv('FAKE_CODEX_DESK', str(desk))

    root = tmp_path / 'repo'
    (root / 'cache' / SLUG).mkdir(parents=True)
    (root / 'cache' / SLUG / 'paragraphs.jsonl').write_text(
        '\n'.join(json.dumps(p, ensure_ascii=False) for p in PARAGRAPHS), encoding='utf-8')
    (root / 'books' / SLUG / 'source').mkdir(parents=True)
    (root / 'books' / SLUG / 'source' / 'book.txt').write_text('весь текст книги', encoding='utf-8')
    (root / 'books' / SLUG / 'book.json').write_text(
        json.dumps({'title': 'Книга', 'author': 'Автор', 'rights': 'protected'},
                   ensure_ascii=False), encoding='utf-8')
    (root / 'books' / SLUG / 'bible.json').write_text(
        json.dumps({'characters': {'hero': {'name': 'Герой'}}, 'places': {}},
                   ensure_ascii=False), encoding='utf-8')
    (root / 'output').mkdir()
    (root / 'output' / 'frame.png').write_bytes(PNG)
    (root / 'styles' / 'directions').mkdir(parents=True)
    (root / 'styles' / 'directions' / 'tush.json').write_text(
        json.dumps({'name': 'Тушь', 'style_notes_en': 'ink', 'palette_en': 'black',
                    'refs': {'ref-01': {'file': 'refs/tush/ref-01.jpeg',
                                        'licence': 'generated-here', 'why': 'своё'}}},
                   ensure_ascii=False), encoding='utf-8')
    (root / 'cache' / 'panel').mkdir(parents=True)
    (root / 'cache' / 'panel' / 'settings.json').write_text(json.dumps({
        'codex_cmd': [sys.executable, str(desk / 'fake_codex.py'), '{root}', '{prompt}'],
        'timeout': 60, 'attempts': 1}), encoding='utf-8')
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)

    panel, httpd = panel_server.serve(root=root, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_port, panel, root
    httpd.shutdown()
    panel.queue.stop()
    httpd.server_close()


def call(port, path, method='GET', body=None):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    conn.request(method, path, json.dumps(body) if body is not None else None,
                 {'Content-Type': 'application/json'})
    answer = conn.getresponse()
    raw = answer.read()
    conn.close()
    try:
        return answer.status, json.loads(raw.decode('utf-8'))
    except ValueError:
        return answer.status, raw


def test_page_is_served_at_the_root(live):
    port, _, _ = live
    status, raw = call(port, '/')
    assert status == 200 and b'\xd0\xa0\xd0\xb0\xd1\x81\xd0\xba' in raw   # «Раск…»


def test_books_are_read_from_the_repository(live):
    port, _, _ = live
    status, data = call(port, '/api/books')
    assert status == 200
    book = data['books'][0]
    assert book['slug'] == SLUG and book['title'] == 'Книга'
    assert book['parsed'] is True and book['characters'] == 1 and book['sheets'] == 0


def test_unknown_book_is_404(live):
    port, _, _ = live
    assert call(port, '/api/books/nonesuch')[0] == 404


def test_book_screen_carries_validator_complaints(live):
    port, _, _ = live
    status, data = call(port, f'/api/books/{SLUG}')
    assert status == 200
    hero = data['characters'][0]
    assert hero['key'] == 'hero'
    assert any('нет поля audit' in c for c in hero['complaints'])


def test_bible_entry_job_runs_through_the_queue(live):
    port, panel, root = live
    status, data = call(port, f'/api/books/{SLUG}/bible/hero', 'POST', {'name': 'Герой'})
    assert status == 200 and data['job']
    job = panel.queue.wait(data['job'], timeout=30)
    assert job['status'] == 'done', job
    bible = json.loads((root / 'books' / SLUG / 'bible.json').read_text())
    assert bible['characters']['hero']['understanding'] == 9.0
    assert call(port, f'/api/books/{SLUG}')[1]['characters'][0]['complaints'] == []


def test_panel_keeps_the_accepted_sheet_the_agent_dropped(live):
    """Лист — бухгалтерия панели: агент переписывает запись целиком и роняет эти поля."""
    port, panel, root = live
    bible_file = root / 'books' / SLUG / 'bible.json'
    data = json.loads(bible_file.read_text())
    data['characters']['hero'].update({'sheet': 'characters/hero.png',
                                       'sheet_sha256': 'a' * 64,
                                       'sheet_prompt': 'чем лист сделан'})
    bible_file.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    job = panel.queue.wait(call(port, f'/api/books/{SLUG}/bible/hero', 'POST', {})[1]['job'],
                           timeout=30)
    assert job['status'] == 'done', job
    entry = json.loads(bible_file.read_text())['characters']['hero']
    assert entry['understanding'] == 9.0                     # запись собрана заново
    assert entry['sheet'] == 'characters/hero.png'           # а лист остался
    assert entry['sheet_prompt'] == 'чем лист сделан'
    assert 'вернула поля принятого листа' in panel.queue.tail(job['id'])


def test_job_log_is_readable(live):
    port, panel, _ = live
    job = panel.queue.wait(call(port, f'/api/books/{SLUG}/bible/hero', 'POST', {})[1]['job'],
                           timeout=30)
    status, data = call(port, f'/api/jobs/{job["id"]}/log?tail=50')
    assert status == 200 and 'попытка 1' in data['log']


def test_styles_are_listed(live):
    port, _, _ = live
    status, data = call(port, '/api/styles')
    assert status == 200 and data['styles'][0]['key'] == 'tush'
    ref = data['styles'][0]['refs'][0]
    assert ref['licence'] == 'generated-here'
    # Путь — из направления, а не угаданный `.png`: расширения у эталонов разные.
    assert ref['file'] == 'styles/refs/tush/ref-01.jpeg'


def test_frame_is_served(live):
    port, _, _ = live
    status, raw = call(port, '/file/output/frame.png')
    assert status == 200 and raw[:4] == b'\x89PNG'


def test_book_text_is_never_served(live):
    """Право на текст — читать, а не раздавать. Даже на локальном сервере."""
    port, _, _ = live
    assert call(port, f'/file/books/{SLUG}/source/book.txt')[0] == 404


def test_escaping_the_root_is_refused(live):
    port, _, _ = live
    assert call(port, '/file/../../../etc/passwd')[0] in (404, 400)
    assert call(port, '/file/output/../books/%s/source/book.txt' % SLUG)[0] == 404


def test_git_status_is_reported(live):
    port, _, _ = live
    status, data = call(port, '/api/git')
    assert status == 200 and isinstance(data['lines'], list)
