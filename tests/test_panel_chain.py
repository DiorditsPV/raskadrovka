"""Цепочка панели целиком: книга → разбор → индекс → карточка → кадр → регистрация.

Проверяется не каждый шаг по отдельности (это делают соседние файлы), а то, что шаги
стыкуются: что кладёт один, тем пользуется следующий, и в конце партия проходит сверку.
Codex поддельный — он пишет то, что настоящий пишет после раздумий.
"""
import base64
import http.client
import json
import subprocess
import sys
import threading
import time

import pytest

import server as panel_server

SLUG = 'jules-verne-test'
BATCH_NAME = 'proba'

# Книга нарочно не игрушечная: разбор отбрасывает слишком короткие главы, и на трёх
# фразах цепочка обрывалась бы не там, где её проверяют.
# Имя героя стоит и в середине фраз: индекс отбрасывает слова, которые встречаются только
# первыми в предложении, и на тексте без единого имени в середине не нашёл бы никого.
FILLER = ('Подземный ход уводил вниз, и свет фонаря выхватывал из темноты то мокрый камень, '
          'то ржавую скобу, вбитую в стену руками Героя много лет назад. Дальше шёл Герой, '
          'и рядом с ним шёл Капитан, и Капитан молчал. ') * 12
BOOK_TEXT = '\n\n'.join(
    ['Глава 1',
     'Первый абзац первой главы, в нём про подземный ход и про свет. ' + FILLER,
     'Второй абзац первой главы, в нём про руки и про лицо Героя. ' + FILLER,
     'Глава 2',
     'Первый абзац второй главы: Капитан бросает камешек. ' + FILLER,
     'Второй абзац второй главы: Герой кланяется и смотрит прямо. ' + FILLER])

CARD = {
    'id': '01-kapitan-brosaet-kamen', 'book': SLUG, 'title': 'Капитан бросает камешек',
    'order': 1, 'locator': {'chapter': 2, 'paragraphs': [3, 4]},
    'excerpt': {'text': 'Первый абзац второй главы: капитан бросает камешек.',
                'attribution': 'Автор, «Книга», издание, 1900'},
    'caption': 'Капитан швыряет камешек, шахтёр кланяется.',
    'brief': 'Пересменка в депо, капитан швыряет камешек.',
    'frame': {'setting': 'a grey depot of concrete and metal', 'time': 'shift change',
              'characters': [{'ref': 'hero', 'state': 'standing at the left, bowing'}],
              'action': 'the captain flicks a pebble at the boy',
              'mood': 'a small daily humiliation',
              'details': ['a pebble caught mid-air'],
              'composition': 'two figures at conversational distance',
              'avoid': ['daylight']},
    'composition': None, 'style_refs': [], 'invariants': ['hero'],
}

ENTRY = {'name': 'Герой', 'appearance': 'Описание для человека.',
         'appearance_en': 'a description for the prompt',
         'subject_en': 'a young miner in an underground colony',
         'locators': [{'chapter': 1, 'paragraphs': [1, 2]}],
         'audit': {k: 1 for k in ('age build face eyes hair skin clothing gear marks '
                                  'bearing').split()},
         'understanding': 10.0}

# Подделка Codex: рисующее задание кладёт картинку, «карточка сцены» — карточку,
# «запись в библию» — запись. Настоящий делает то же самое, только думает.
FAKE = '''import json, os, re, sys
from pathlib import Path

root, desk = Path(sys.argv[1]), Path(os.environ['FAKE_CODEX_DESK'])
prompt = sys.argv[2]
if 'image_gen' in prompt:
    out = root / re.search(r'^(\\S+\\.png)', prompt, re.M).group(1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b'\\x89PNG\\r\\n\\x1a\\n' + os.urandom(200_000))
    sys.exit(0)
target = re.search(r'`(books/\\S+\\.json)`', prompt)
if target and 'scenes/' in target.group(1):
    card = root / target.group(1)
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text(json.dumps(json.loads((desk / 'card.json').read_text()),
                               ensure_ascii=False, indent=2), encoding='utf-8')
    sys.exit(0)
bible = root / 'books' / '%s' / 'bible.json'
data = json.loads(bible.read_text())
data['characters']['hero'] = json.loads((desk / 'entry.json').read_text())
bible.write_text(json.dumps(data, ensure_ascii=False, indent=2))
''' % SLUG


@pytest.fixture
def live(tmp_path, monkeypatch):
    desk = tmp_path / 'desk'
    desk.mkdir()
    (desk / 'entry.json').write_text(json.dumps(ENTRY, ensure_ascii=False), encoding='utf-8')
    (desk / 'card.json').write_text(json.dumps(CARD, ensure_ascii=False), encoding='utf-8')
    (desk / 'fake_codex.py').write_text(FAKE, encoding='utf-8')
    monkeypatch.setenv('FAKE_CODEX_DESK', str(desk))

    root = tmp_path / 'repo'
    (root / 'cache' / 'panel').mkdir(parents=True)
    (root / 'cache' / 'panel' / 'settings.json').write_text(json.dumps({
        'codex_cmd': [sys.executable, str(desk / 'fake_codex.py'), '{root}', '{prompt}'],
        'timeout': 60, 'attempts': 1}), encoding='utf-8')
    (root / 'output').mkdir()
    (root / 'styles' / 'refs' / 'tush').mkdir(parents=True)
    (root / 'styles' / 'refs' / 'tush' / 'ref-01.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 99)
    (root / 'styles' / 'directions').mkdir(parents=True)
    (root / 'styles' / 'directions' / 'tush.json').write_text(json.dumps({
        'name': 'Тушь', 'style_notes_en': 'ink and flat colour', 'palette_en': 'black and red',
        'refs': {'ref-01': {'file': 'refs/tush/ref-01.png', 'license': 'generated-here',
                            'license_basis': 'сгенерировано здесь, права наши',
                            'why': 'своё'}}}, ensure_ascii=False), encoding='utf-8')
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)

    panel, httpd = panel_server.serve(root=root, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_port, panel, root
    httpd.shutdown()
    panel.queue.stop()
    httpd.server_close()


def call(port, path, method='GET', body=None):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=20)
    conn.request(method, path, json.dumps(body) if body is not None else None,
                 {'Content-Type': 'application/json'})
    answer = conn.getresponse()
    raw = answer.read()
    conn.close()
    try:
        return answer.status, json.loads(raw.decode('utf-8'))
    except ValueError:
        return answer.status, raw


def idle(port, kind, tries=300):
    """Дождаться, пока очередь опустеет, и вернуть последнее задание нужного вида.

    Вид называется явно: идентификаторы заданий одной секунды сортируются по имени, и
    «последнее в списке» — не то же самое, что «то, которое я только что поставил».
    """
    for _ in range(tries):
        status, data = call(port, '/api/jobs')
        jobs = data['jobs']
        mine = [j for j in jobs if j['kind'] == kind]
        if mine and all(j['status'] not in ('queued', 'running') for j in jobs):
            return mine[0]
        time.sleep(0.1)
    raise AssertionError(f'не дождались задания «{kind}»')


def test_whole_chain_from_a_file_to_a_registered_frame(live):
    port, panel, root = live

    # 1. книга: файл уходит в панель, разбор идёт заданием
    status, data = call(port, '/api/books', 'POST', {
        'slug': SLUG, 'filename': 'kniga.txt', 'title': 'Книга', 'author': 'Автор',
        'rights': 'public-domain', 'basis': 'срок истёк',
        'data': base64.b64encode(BOOK_TEXT.encode('utf-8')).decode()})
    assert status == 200 and data['slug'] == SLUG
    job = idle(port, 'ingest')
    assert job['status'] == 'done', job.get('error')
    assert (root / 'books' / SLUG / 'book.json').is_file()
    assert (root / 'cache' / SLUG / 'paragraphs.jsonl').is_file()
    # текст книги лежит в книге, но наружу не отдаётся ни он, ни его разбор
    assert (root / 'books' / SLUG / 'source' / 'kniga.txt').is_file()
    assert call(port, f'/file/books/{SLUG}/source/kniga.txt')[0] == 404
    assert call(port, f'/file/cache/{SLUG}/paragraphs.jsonl')[0] == 404

    # 2. индекс
    assert call(port, f'/api/books/{SLUG}/index', 'POST', {})[0] == 200
    job = idle(port, 'index')
    assert job['status'] == 'done', job.get('error')
    assert (root / 'cache' / SLUG / 'index.json').is_file()

    # 3. запись героя: имя даёт индекс, а не человек
    status, data = call(port, f'/api/books/{SLUG}')
    found = {f['name']: f for f in data['found']}
    assert found, 'индекс никого не нашёл — экран «Персонажи» новой книги остался бы пустым'
    assert all(not f['known'] for f in found.values())
    call(port, f'/api/books/{SLUG}/bible/hero', 'POST', {'name': 'Герой'})
    marks = json.loads((root / 'cache' / 'panel' / SLUG / 'panel.json')
                       .read_text(encoding='utf-8'))
    assert marks['heroes']['Герой']['key'] == 'hero'
    job = idle(port, 'bible-entry')
    assert job['status'] == 'done', job.get('error')
    # заведённый герой из списка находок уходит: он уже в библии
    assert [f for f in call(port, f'/api/books/{SLUG}')[1]['found']
            if f['name'] == 'Герой' and f['known']]
    call(port, f'/api/books/{SLUG}/sheets/hero', 'POST', {})
    job = idle(port, 'sheet')
    assert job['status'] == 'done', job.get('error')
    assert call(port, f'/api/books/{SLUG}/sheets/hero/accept', 'POST', {})[0] == 200

    # 4. партия и карточка сцены
    status, data = call(port, f'/api/books/{SLUG}/batches', 'POST', {
        'name': BATCH_NAME, 'title': 'Проба', 'style': 'tush', 'short': 'proba',
        'request': 'первые сцены'})
    assert status == 200
    batch = data['batch']
    assert batch == '01-' + BATCH_NAME
    status, data = call(port, f'/api/books/{SLUG}/batches/{batch}/cards', 'POST', {
        'card': CARD['id'], 'brief': 'капитан бросает камешек', 'where': 'глава 2'})
    assert status == 200, data
    job = idle(port, 'scene-card')
    assert job['status'] == 'done', job.get('error')
    assert (root / 'books' / SLUG / batch / 'scenes' / f'{CARD["id"]}.json').is_file()

    # 5. кадр
    status, data = call(port, f'/api/books/{SLUG}/batches/{batch}/frames', 'POST',
                        {'card': CARD['id'], 'style': 'tush'})
    assert status == 200, data
    job = idle(port, 'scene')
    assert job['status'] == 'done', job.get('error')
    frame = job['result']
    assert (root / frame['path']).is_file()
    assert (root / 'books' / SLUG / batch / frame['prompt']).is_file()
    # лист героя ушёл во входы кадра — ради него он и делался
    assert frame['inputs'] >= 2

    # экран партии показывает кадр
    status, data = call(port, f'/api/books/{SLUG}/batches/{batch}')
    scene = data['scenes'][0]
    assert scene['frames'] and scene['frames'][0]['image']
    assert call(port, '/file/' + scene['frames'][0]['image'])[0] == 200

    # 6. сверка ничего не меняет и говорит, сколько записей уберёт перезапись
    status, check = call(port, f'/api/books/{SLUG}/batches/{batch}/check')
    assert status == 200 and check['frames'] == 1 and check['dropped'] == 0, check
    assert len(json.loads((root / 'books' / SLUG / batch / 'metadata' / 'request.json')
                          .read_text(encoding='utf-8'))['scenes']) == 1

    # 7. регистрация: сверка промптов, хешей и прав
    assert call(port, f'/api/books/{SLUG}/batches/{batch}/register', 'POST', {})[0] == 200
    job = idle(port, 'register')
    assert job['status'] == 'done', (job.get('error'), job.get('result'))
    manifest = json.loads((root / 'books' / SLUG / batch / 'metadata' / 'request.json')
                          .read_text(encoding='utf-8'))
    assert len(manifest['scenes']) == 1
    assert manifest['scenes'][0]['card_sha256']


def test_a_book_cannot_be_added_twice(live):
    port, _, _ = live
    body = {'slug': SLUG, 'filename': 'kniga.txt', 'rights': 'public-domain',
            'data': base64.b64encode(BOOK_TEXT.encode('utf-8')).decode()}
    assert call(port, '/api/books', 'POST', body)[0] == 200
    idle(port, 'ingest')
    assert call(port, '/api/books', 'POST', body)[0] == 409


def test_a_book_of_an_unreadable_format_is_refused(live):
    port, _, root = live
    status, data = call(port, '/api/books', 'POST', {
        'slug': 'inaya-kniga', 'filename': 'kniga.pdf', 'rights': 'public-domain',
        'data': base64.b64encode(b'%PDF-1.4').decode()})
    assert status == 400 and 'fb2' in data['error']
    assert not (root / 'books' / 'inaya-kniga').exists()
