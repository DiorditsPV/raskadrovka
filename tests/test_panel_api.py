"""Сервер панели: маршруты, задание через очередь, и то, что наружу не выходит.

Репозиторий временный, Codex поддельный. Проверяется, что сервер отвечает из файлов и что
раздача файлов не выпускает текст книги: право на текст у нас на чтение, не на раздачу.
"""
import hashlib
import http.client
import json
import subprocess
import sys
import threading
import time

import pytest

import agent
import server as panel_server

SLUG = 'test-book'
FAKE = '''import json, os, re, sys
from pathlib import Path

root, desk = Path(sys.argv[1]), Path(os.environ['FAKE_CODEX_DESK'])
prompt = sys.argv[2]
if 'image_gen' in prompt:                       # рисующее задание: кладём картинку куда велено
    out = root / re.search(r'^(\\S+\\.png)', prompt, re.M).group(1)
    out.parent.mkdir(parents=True, exist_ok=True)
    if os.environ.get('FAKE_CODEX_DRAWS') != 'no':
        out.write_bytes(b'\\x89PNG\\r\\n\\x1a\\n' + os.urandom(200_000))
    sys.exit(0)
bible = root / 'books' / '%s' / 'bible.json'
data = json.loads(bible.read_text())
# Добор и сборка — разные задания, и подделка отвечает на них по-разному, как настоящий.
written = 'refined.json' if 'добираешь внешность' in prompt else 'entry.json'
data['characters']['hero'] = json.loads((desk / written).read_text())
bible.write_text(json.dumps(data, ensure_ascii=False, indent=2))
''' % SLUG

ENTRY = {'name': 'Герой', 'appearance': 'Описание для человека.',
         'appearance_en': 'a description for the prompt',
         'subject_en': 'a person of some sort in some place',
         'locators': [{'chapter': 1, 'paragraphs': [1, 2]}],
         'audit': {'age': 1, 'build': 1, 'face': 1, 'eyes': 0.5, 'hair': 1,
                   'skin': 1, 'clothing': 1, 'gear': 1, 'marks': 1, 'bearing': 0.5},
         'understanding': 9.0}

# Каким добор возвращает запись: цвет глаз нашёлся в книге, осанка — нет, и про неё
# записан пробел. Третьего исхода у клетки после добора не бывает.
REFINED = json.loads(json.dumps(ENTRY))
REFINED['audit']['eyes'] = 1
REFINED['understanding'] = 9.5
REFINED['gaps'] = {'bearing': {'why': 'о походке и осанке книга не говорит ничего',
                               'looked': 'главы 1–2 по имени, поиск walked / stood / посадка'}}

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
    (desk / 'refined.json').write_text(json.dumps(REFINED, ensure_ascii=False), encoding='utf-8')
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
    gaps = [c for c in hero['complaints'] if c['level'] == 'missing']
    # Поля контракта, которого в записи нет, — «не хватает», а не «сломано»: разбивка
    # audit появилась позже самих записей.
    assert any('нет поля audit' in c['text'] for c in gaps)
    assert not [c for c in hero['complaints'] if c['level'] != 'missing']


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
    assert 'вернула свои поля записи' in panel.queue.tail(job['id'])


def test_batch_shows_cards_with_their_frames(live):
    """Экран партии — про картинки: карточка, кадр, кто в кадре, отрывок книги."""
    port, _, root = live
    batch = root / 'books' / SLUG / '01-proba'
    (batch / 'scenes').mkdir(parents=True)
    (batch / 'metadata').mkdir()
    (batch / 'scenes' / '01-scena.json').write_text(json.dumps({
        'id': '01-scena', 'title': 'Сцена', 'order': 1, 'caption': 'подпись',
        'locator': {'chapter': 1, 'paragraphs': [1, 2]},
        'excerpt': {'text': 'Второй абзац, в нём про волосы.'},
        'invariants': ['hero'], 'composition': '01-dvoe'}, ensure_ascii=False), encoding='utf-8')
    (root / 'output' / 'book--proba--tush--01-scena.png').write_bytes(PNG)
    (batch / 'metadata' / 'request.json').write_text(json.dumps({
        'request': 'проба', 'style': 'tush', 'scenes': [{
            'id': 'tush--01-scena', 'title': 'Сцена', 'order': 1, 'caption': 'подпись',
            'style': 'tush', 'style_refs': ['ref-01'], 'composition': '01-dvoe',
            'card': 'scenes/01-scena.json', 'prompt': 'prompt/tush--01-scena.txt',
            'output': '../../../output/book--proba--tush--01-scena.png'}]},
        ensure_ascii=False), encoding='utf-8')

    status, data = call(port, f'/api/books/{SLUG}/batches/01-proba')
    assert status == 200 and len(data['scenes']) == 1
    scene = data['scenes'][0]
    assert scene['invariants'] == ['hero'] and 'про волосы' in scene['excerpt']
    frame = scene['frames'][0]
    assert frame['image'] == 'output/book--proba--tush--01-scena.png'
    assert call(port, '/file/' + frame['image'])[1][:4] == b'\x89PNG'


def test_card_without_a_frame_is_still_listed(live):
    """Карточка есть всегда, запись в манифесте — только после кадра; список ведут карточки."""
    port, _, root = live
    batch = root / 'books' / SLUG / '02-plan'
    (batch / 'scenes').mkdir(parents=True)
    (batch / 'metadata').mkdir()
    (batch / 'scenes' / '01-bez-kadra.json').write_text(
        json.dumps({'id': '01-bez-kadra', 'title': 'Без кадра', 'order': 1},
                   ensure_ascii=False), encoding='utf-8')
    status, data = call(port, f'/api/books/{SLUG}/batches/02-plan')
    assert status == 200 and data['scenes'][0]['frames'] == []


def test_sheet_is_given_as_a_servable_path(live):
    """В библии путь от папки книги; странице нужен путь, по которому картинку отдадут."""
    port, _, root = live
    (root / 'books' / SLUG / 'characters').mkdir()
    (root / 'books' / SLUG / 'characters' / 'hero.png').write_bytes(PNG)
    bible_file = root / 'books' / SLUG / 'bible.json'
    data = json.loads(bible_file.read_text())
    data['characters']['hero'].update({'sheet': 'characters/hero.png',
                                       'sheet_sha256': 'a' * 64, 'sheet_prompt': 'чем'})
    bible_file.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    hero = call(port, f'/api/books/{SLUG}')[1]['characters'][0]
    assert hero['sheet_file'] == f'books/{SLUG}/characters/hero.png'
    assert call(port, '/file/' + hero['sheet_file'])[1][:4] == b'\x89PNG'


def test_second_click_does_not_start_a_second_codex(live):
    """Задание с суждением идёт минутами: два запуска — два Codex на одном файле."""
    port, panel, _ = live
    panel.queue.stop()                                   # ничего не разбирать: смотрим очередь
    first = call(port, f'/api/books/{SLUG}/bible/hero', 'POST', {})
    second = call(port, f'/api/books/{SLUG}/bible/hero', 'POST', {})
    assert first[0] == 200
    assert second[0] == 409 and second[1]['job'] == first[1]['job']
    assert len(panel.queue.all()) == 1


def test_job_log_is_readable(live):
    port, panel, _ = live
    job = panel.queue.wait(call(port, f'/api/books/{SLUG}/bible/hero', 'POST', {})[1]['job'],
                           timeout=30)
    status, data = call(port, f'/api/jobs/{job["id"]}/log?tail=50')
    assert status == 200 and 'попытка 1' in data['log']


def test_the_instruction_uses_the_name_the_book_uses(live):
    """В браузере лежит русское имя из библии; по английскому тексту оно не найдёт ничего."""
    port, panel, root = live
    (root / 'cache' / SLUG / 'index.json').write_text(json.dumps(
        {'characters': {'Hero': {'appearance': [{'i': 1, 'chapter': 1, 'score': 3}]}}},
        ensure_ascii=False), encoding='utf-8')
    name, hints = panel.hero_hints(SLUG, 'hero', 'Герой')
    assert name == 'Hero' and hints == 'гл1 [1, 2)'


def test_unknown_hero_says_so_instead_of_inventing_a_name(live):
    """Индекс знает не всех: короткие имена он отсеивает, рассказчика почти не видит."""
    port, panel, _ = live
    name, hints = panel.hero_hints(SLUG, 'eo', 'Ио')
    assert name == 'Ио' and 'найди сам' in hints


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


# — лист персонажа —


def wait_for(port, path, ready, tries=120):
    """Задание идёт в другом потоке: ждём, пока сервер начнёт отвечать нужное."""
    import time
    for _ in range(tries):
        status, data = call(port, path)
        if ready(data):
            return data
        time.sleep(0.1)
    raise AssertionError(f'не дождались: {path}')


def hero_of(port):
    return call(port, f'/api/books/{SLUG}')[1]['characters'][0]


def test_sheet_is_refused_while_the_record_is_not_ready(live):
    port, _, _ = live
    # У героя из фикстуры одно поле `name`: ни балла, ни subject_en — рисовать нечего.
    status, data = call(port, f'/api/books/{SLUG}/sheets/hero', 'POST', {})
    assert status == 409 and 'subject_en' in data['error']
    assert hero_of(port)['sheet_blocked']


def test_sheet_waits_for_a_verdict_and_only_then_enters_the_book(live):
    port, panel, root = live
    call(port, f'/api/books/{SLUG}/bible/hero', 'POST', {})       # запись собирается подделкой
    wait_for(port, '/api/jobs', lambda d: all(j['status'] not in ('queued', 'running')
                                              for j in d['jobs']))
    assert hero_of(port)['sheet_blocked'] is None

    status, data = call(port, f'/api/books/{SLUG}/sheets/hero', 'POST', {})
    assert status == 200 and data['job']
    hero = wait_for(port, f'/api/books/{SLUG}', lambda d: d['characters'][0]['pending'])
    hero = hero['characters'][0]
    # Лист собран, но в книге его ещё нет: приёмка — человеком, кнопкой.
    assert hero['pending']['file'] == f'cache/panel/{SLUG}/sheets/hero.png'
    assert hero['sheet'] is None
    assert not (root / 'books' / SLUG / 'characters' / 'hero.png').exists()
    # И картинка на приёмке раздаётся, а разобранный текст книги рядом — нет.
    assert call(port, '/file/' + hero['pending']['file'])[0] == 200
    assert call(port, f'/file/cache/{SLUG}/paragraphs.jsonl')[0] == 404

    assert call(port, f'/api/books/{SLUG}/sheets/hero/accept', 'POST', {})[0] == 200
    hero = hero_of(port)
    assert hero['sheet'] == 'characters/hero.png' and hero['pending'] is None
    assert (root / 'books' / SLUG / 'characters' / 'hero.png').is_file()
    entry = json.loads((root / 'books' / SLUG / 'bible.json')
                       .read_text(encoding='utf-8'))['characters']['hero']
    assert entry['sheet_prompt'].startswith('Style: a plain character reference sheet')
    assert len(entry['sheet_sha256']) == 64


def test_rejected_sheet_leaves_no_trace(live):
    port, _, root = live
    call(port, f'/api/books/{SLUG}/bible/hero', 'POST', {})
    wait_for(port, '/api/jobs', lambda d: all(j['status'] not in ('queued', 'running')
                                              for j in d['jobs']))
    call(port, f'/api/books/{SLUG}/sheets/hero', 'POST', {})
    wait_for(port, f'/api/books/{SLUG}', lambda d: d['characters'][0]['pending'])
    assert call(port, f'/api/books/{SLUG}/sheets/hero/reject', 'POST', {})[0] == 200
    assert hero_of(port)['pending'] is None
    assert not (root / 'cache' / 'panel' / SLUG / 'sheets' / 'hero.png').exists()
    assert not (root / 'books' / SLUG / 'characters' / 'hero.png').exists()


def test_silent_failure_of_the_generator_is_a_complaint_not_a_sheet(live, monkeypatch):
    port, _, _ = live
    call(port, f'/api/books/{SLUG}/bible/hero', 'POST', {})
    wait_for(port, '/api/jobs', lambda d: all(j['status'] not in ('queued', 'running')
                                              for j in d['jobs']))
    monkeypatch.setenv('FAKE_CODEX_DRAWS', 'no')          # генерация падает молча — так бывает
    call(port, f'/api/books/{SLUG}/sheets/hero', 'POST', {})
    jobs = wait_for(port, '/api/jobs', lambda d: any(
        j['kind'] == 'sheet' and j['status'] in ('done', 'failed') for j in d['jobs']))
    sheet = [j for j in jobs['jobs'] if j['kind'] == 'sheet'][0]
    assert sheet['status'] == 'failed'
    assert any('нет' in c for c in sheet['result']['complaints'])
    assert hero_of(port)['pending'] is None


# — добор внешности —

def collect_entry(port, panel):
    answer = call(port, f'/api/books/{SLUG}/bible/hero', 'POST', {})[1]
    job = panel.queue.wait(answer['job'], timeout=30)
    # Ждать можно и чужое задание: на занятый ключ маршрут отвечает 409 с чужим id,
    # и тогда «готово» относится не к записи. Пусть падает с внятной причиной.
    assert job['kind'] == 'bible-entry', answer
    assert job['status'] == 'done', job


def test_refine_raises_what_the_book_gives_and_writes_down_what_it_does_not(live):
    """У просевшей клетки после добора два исхода: поднятый балл или объяснённый пробел."""
    port, panel, root = live
    collect_entry(port, panel)
    assert sorted(hero_of(port)['refine']) == ['bearing', 'eyes']

    status, data = call(port, f'/api/books/{SLUG}/bible/hero/refine', 'POST', {})
    assert status == 200
    job = panel.queue.wait(data['job'], timeout=30)
    assert job['status'] == 'done', job

    entry = json.loads((root / 'books' / SLUG / 'bible.json')
                       .read_text(encoding='utf-8'))['characters']['hero']
    assert entry['audit']['eyes'] == 1 and entry['understanding'] == 9.5
    assert list(entry['gaps']) == ['bearing']
    # Отпечаток и время ставит панель: агент судит, учёт ведём мы.
    assert entry['gaps_for'] and entry['gaps_at']

    hero = hero_of(port)
    assert hero['refine'] == []                  # добирать больше нечего, и панель не просит
    assert hero['gaps_stale'] is False
    assert hero['gaps']['bearing']['looked']


def test_rewriting_the_record_makes_the_explained_gaps_stale_instead_of_losing_them(live):
    """Пробел — дорогая улика: агент прочёл книгу и ничего не нашёл. Пересборка записи его
    не выбрасывает, но и не выдаёт за свежий: он относится к прежнему тексту."""
    port, panel, root = live
    collect_entry(port, panel)
    panel.queue.wait(call(port, f'/api/books/{SLUG}/bible/hero/refine', 'POST', {})[1]['job'],
                     timeout=30)
    collect_entry(port, panel)                   # запись переписали целиком

    entry = json.loads((root / 'books' / SLUG / 'bible.json')
                       .read_text(encoding='utf-8'))['characters']['hero']
    assert list(entry['gaps']) == ['bearing']    # не потеряли
    hero = hero_of(port)
    assert hero['gaps_stale'] is True            # но и не выдаём за свежий
    assert sorted(hero['refine']) == ['bearing', 'eyes']


def test_refine_is_refused_when_every_cell_is_full(live):
    port, panel, root = live
    collect_entry(port, panel)
    bible_file = root / 'books' / SLUG / 'bible.json'
    data = json.loads(bible_file.read_text(encoding='utf-8'))
    data['characters']['hero']['audit'] = {k: 1 for k in data['characters']['hero']['audit']}
    data['characters']['hero']['understanding'] = 10.0
    bible_file.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    status, answer = call(port, f'/api/books/{SLUG}/bible/hero/refine', 'POST', {})
    assert status == 400 and 'добирать нечего' in answer['error']


def test_a_sheet_drawn_over_gaps_is_not_born_stale(live):
    """Промпт листа и проверка «лист устарел» читают пробелы одним правилом.

    Читай они разное — только что принятый лист сразу помечался бы «по прежней записи»,
    и метка, которая должна ловить переписанную запись, перестала бы что-либо значить.
    """
    port, panel, root = live
    collect_entry(port, panel)
    panel.queue.wait(call(port, f'/api/books/{SLUG}/bible/hero/refine', 'POST', {})[1]['job'],
                     timeout=30)

    panel.queue.wait(call(port, f'/api/books/{SLUG}/sheets/hero', 'POST', {})[1]['job'],
                     timeout=30)
    hero = wait_for(port, f'/api/books/{SLUG}', lambda d: d['characters'][0]['pending'])
    assert 'Unspecified' in hero['characters'][0]['pending']['prompt']

    assert call(port, f'/api/books/{SLUG}/sheets/hero/accept', 'POST', {})[0] == 200
    hero = hero_of(port)
    assert hero['sheet'] and hero['sheet_stale'] is False


def closed_record(root, understanding, gaps_count):
    """Запись, где каждая клетка либо полная, либо объяснена пробелом."""
    import validators
    bible_file = root / 'books' / SLUG / 'bible.json'
    data = json.loads(bible_file.read_text(encoding='utf-8'))
    entry = data['characters']['hero']
    cells = list(validators.AUDIT_KEYS)
    full = int(understanding)
    entry['audit'] = {k: (1 if i < full else 0) for i, k in enumerate(cells)}
    entry['understanding'] = float(full)
    entry['gaps'] = {k: {'why': 'книга об этом не говорит ничего',
                         'looked': 'все главы по имени и по частям тела'}
                     for k in cells[full:full + gaps_count]}
    entry['gaps_for'] = validators.record_fingerprint(entry)
    entry['gaps_at'] = '2026-09-10T00:00:00'
    data['characters']['hero'] = entry
    bible_file.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def test_a_closed_record_below_the_gate_may_still_be_drawn(live):
    """Книга отдала всё: каждая клетка полная или объяснена. Ждать больше нечего, и порог,
    который ждёт, превращается в тупик."""
    port, panel, root = live
    collect_entry(port, panel)
    closed_record(root, understanding=6, gaps_count=4)
    hero = hero_of(port)
    assert hero['understanding'] == 6.0 and hero['refine'] == [] and hero['closed'] is True
    assert hero['sheet_blocked'] is None


def test_a_record_of_almost_nothing_but_gaps_is_still_refused(live):
    """Нижняя граница: из записи, где книга не дала и половины, рисовать нечего."""
    port, panel, root = live
    collect_entry(port, panel)
    closed_record(root, understanding=3, gaps_count=7)
    hero = hero_of(port)
    assert hero['refine'] == [] and 'ниже 5 из 10' in hero['sheet_blocked']


# — история листов —

def history_of(port):
    return hero_of(port)['history']


def test_accepting_a_second_sheet_keeps_the_first_instead_of_overwriting_it(live):
    """Лист героя — решение, а не файл. Прежнее решение должно остаться видимым."""
    port, panel, root = live
    collect_entry(port, panel)
    for _ in range(2):
        panel.queue.wait(call(port, f'/api/books/{SLUG}/sheets/hero', 'POST', {})[1]['job'],
                         timeout=30)
        wait_for(port, f'/api/books/{SLUG}', lambda d: d['characters'][0]['pending'])
        call(port, f'/api/books/{SLUG}/sheets/hero/accept', 'POST', {})

    old = history_of(port)
    assert len(old) == 1 and old[0]['left'] == 'replaced'
    kept = root / 'books' / SLUG / old[0]['rel']
    assert kept.is_file() and kept.stat().st_size > 100_000
    # Карточка рядом с картинкой: без промпта лист нечем повторить и некуда вернуть.
    assert json.loads(kept.with_suffix('.json').read_text(encoding='utf-8'))['prompt']
    assert call(port, '/file/' + old[0]['file'])[0] == 200


def test_a_rejected_sheet_goes_to_history_rather_than_nowhere(live):
    port, panel, root = live
    collect_entry(port, panel)
    panel.queue.wait(call(port, f'/api/books/{SLUG}/sheets/hero', 'POST', {})[1]['job'],
                     timeout=30)
    wait_for(port, f'/api/books/{SLUG}', lambda d: d['characters'][0]['pending'])
    assert call(port, f'/api/books/{SLUG}/sheets/hero/reject', 'POST', {})[0] == 200

    hero = hero_of(port)
    assert hero['sheet'] is None and hero['pending'] is None
    assert len(hero['history']) == 1 and hero['history'][0]['left'] == 'rejected'


def test_restoring_swaps_the_current_sheet_with_the_chosen_one(live):
    port, panel, root = live
    collect_entry(port, panel)
    for _ in range(2):
        panel.queue.wait(call(port, f'/api/books/{SLUG}/sheets/hero', 'POST', {})[1]['job'],
                         timeout=30)
        wait_for(port, f'/api/books/{SLUG}', lambda d: d['characters'][0]['pending'])
        call(port, f'/api/books/{SLUG}/sheets/hero/accept', 'POST', {})

    current = (root / 'books' / SLUG / 'characters' / 'hero.png').read_bytes()
    older = history_of(port)[0]
    assert call(port, f'/api/books/{SLUG}/sheets/hero/restore', 'POST',
                {'file': older['rel']})[0] == 200

    now = (root / 'books' / SLUG / 'characters' / 'hero.png').read_bytes()
    assert hashlib.sha256(now).hexdigest() == older['sha256']    # вернулся выбранный
    entry = json.loads((root / 'books' / SLUG / 'bible.json')
                       .read_text(encoding='utf-8'))['characters']['hero']
    assert entry['sheet_sha256'] == older['sha256']              # и библия знает об этом
    # Сменённый ушёл в историю, а вернувшийся из неё пропал: один лист не бывает разом
    # и нынешним, и прежним.
    after = history_of(port)
    assert len(after) == 1 and hashlib.sha256(current).hexdigest() == after[0]['sha256']


def test_restore_refuses_a_path_outside_this_hero_history(live):
    port, panel, root = live
    collect_entry(port, panel)
    for bad in ('../bible.json', 'characters/history/../../bible.json', 'characters/hero.png'):
        assert call(port, f'/api/books/{SLUG}/sheets/hero/restore', 'POST',
                    {'file': bad})[0] == 400


# — пустой разбор —

EPUB_LIKE = ('Глава без номера\n\nПервый абзац этой главы, достаточно длинный, чтобы пройти '
             'порог в четыреста знаков. ' + 'Слова, слова, слова. ' * 25 + '\n\n'
             'Второй абзац, тоже не короткий. ' + 'И ещё слова. ' * 40 + '\n')


def test_ingest_refuses_to_write_an_empty_parse(live):
    """Книга, у которой главы не пронумерованы, с галочкой «только пронумерованные»
    разбирается в ничто. Такой разбор на диск не ложится: пустой кеш неотличим
    от разобранной книги, и всё, что идёт следом, работает вхолостую."""
    import ingest_book
    port, panel, root = live
    source = root / 'books' / SLUG / 'source' / 'novel.txt'
    source.write_text(EPUB_LIKE, encoding='utf-8')
    было = (root / 'cache' / SLUG / 'paragraphs.jsonl').read_text(encoding='utf-8')

    with pytest.raises(ValueError, match='ни одного абзаца'):
        ingest_book.ingest(source, SLUG, {}, root=root, numbered_only=True)
    # Прежний разбор не тронут — это половина смысла отказа.
    assert (root / 'cache' / SLUG / 'paragraphs.jsonl').read_text(encoding='utf-8') == было
    # И причина названа так, чтобы её можно было устранить.
    try:
        ingest_book.ingest(source, SLUG, {}, root=root, numbered_only=True)
    except ValueError as error:
        assert 'снимите галочку' in str(error)

    book = ingest_book.ingest(source, SLUG, {}, root=root)     # без галочки — разбирается
    assert book['source']['paragraphs'] == 2


def test_index_refuses_an_unparsed_book_instead_of_reporting_success(live):
    """Индекс по пустому кешу строится мгновенно и рапортует «готово, лиц 0»."""
    port, panel, root = live
    (root / 'cache' / SLUG / 'paragraphs.jsonl').write_text('\n', encoding='utf-8')

    job = panel.queue.wait(call(port, f'/api/books/{SLUG}/index', 'POST', {})[1]['job'],
                           timeout=30)
    assert job['status'] == 'failed', job
    assert 'не разобрана' in ' '.join(job['result']['complaints'])


def test_an_empty_cache_does_not_pass_for_a_parsed_book(live):
    """Экран книг считает абзацы, а не файлы: пустой кеш существует и этим лжёт."""
    port, panel, root = live
    (root / 'cache' / SLUG / 'paragraphs.jsonl').write_text('\n', encoding='utf-8')
    book = call(port, '/api/books')[1]['books'][0]
    assert book['parsed'] is False and book['paragraphs'] == 0
    # И экран книги при этом открывается, а не падает с JSONDecodeError.
    assert call(port, f'/api/books/{SLUG}')[0] == 200


def test_accepting_a_sheet_while_a_job_runs_does_not_fail_that_job(live):
    """Задание идёт минуты, и всё это время человек работает в панели. Его принятый лист
    попадает в разницу снимков `git status` — и раньше ронял задание, которое уже сделало
    свою работу. Так был выброшен нарисованный лист «Смерти»."""
    port, panel, root = live
    collect_entry(port, panel)
    # лист принят «во время задания»: панель помечает свой след сама
    panel.queue.wait(call(port, f'/api/books/{SLUG}/sheets/hero', 'POST', {})[1]['job'],
                     timeout=30)
    wait_for(port, f'/api/books/{SLUG}', lambda d: d['characters'][0]['pending'])

    started = time.time()

    def validate():
        call(port, f'/api/books/{SLUG}/sheets/hero/accept', 'POST', {})
        return []

    report = agent.run('bible-entry', {'key': 'hero', 'slug': SLUG, 'name': 'Герой',
                                       'title': 'Книга', 'hints': 'нет'},
                       validate, [f'books/{SLUG}/bible.json'], root=root,
                       config=panel.settings, mine=panel.touched_since)
    assert report['ok'], report['complaints']
    assert not report['strays'], report['strays']
    assert (root / 'books' / SLUG / 'characters' / 'hero.png').is_file()
    assert started <= time.time()


# — книга сама о себе —

def test_the_book_fills_the_form_from_its_own_metadata(live):
    """Название, автора, год и язык книга знает о себе сама: переписывать их из файла
    руками — это возврат работы человеку."""
    import base64 as b64
    port, panel, root = live
    fb2 = ('<?xml version="1.0" encoding="utf-8"?>'
           '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"><description>'
           '<title-info><author><first-name>Герберт</first-name><last-name>Уэллс</last-name>'
           '</author><book-title>Война миров</book-title><lang>ru</lang>'
           '<translator><last-name>Зенкевич</last-name></translator><date>1898</date>'
           '</title-info><publish-info><publisher>Гослитиздат</publisher><year>1935</year>'
           '</publish-info></description><body><section><p>Абзац.</p></section></body>'
           '</FictionBook>').encode('utf-8')
    status, meta = call(port, '/api/books/meta', 'POST',
                        {'filename': 'voyna.fb2', 'data': b64.b64encode(fb2).decode()})
    assert status == 200, meta
    assert meta['title'] == 'Война миров'
    assert meta['author'] == 'Герберт Уэллс'
    assert meta['translator'] == 'Зенкевич'
    assert meta['year_published'] == '1898' and meta['language'] == 'ru'
    assert meta['edition'] == 'Гослитиздат, 1935'
    assert meta['slug'] == 'voyna-mirov'                # слаг сложен из названия
    assert meta['staged']                               # файл уже на сервере


def test_a_staged_file_is_not_sent_twice(live):
    """Файл, по которому заполнили форму, уже лежит на сервере: слать его второй раз незачем."""
    import base64 as b64
    port, panel, root = live
    text = 'Глава\n\n' + ('Длинный абзац книги. ' * 40) + '\n'
    _, meta = call(port, '/api/books/meta', 'POST',
                   {'filename': 'kniga.txt', 'data': b64.b64encode(text.encode()).decode()})
    status, answer = call(port, '/api/books', 'POST',
                          {'slug': 'novaya-kniga', 'rights': 'public-domain',
                           'staged': meta['staged'], 'filename': 'kniga.txt',
                           'title': meta['title']})
    assert status == 200, answer
    job = panel.queue.wait(answer['job'], timeout=30)
    assert job['status'] == 'done', job
    assert (root / 'books' / 'novaya-kniga' / 'source' / 'kniga.txt').is_file()
    # Черновик убран: текст книги лежит там, где ему положено, и только там.
    assert not list((root / 'cache' / 'panel' / 'staged').glob('*'))


def test_a_slug_that_is_taken_gets_the_author(live):
    import ingest_book
    assert ingest_book.slug_for('Война миров', 'Герберт Уэллс', []) == 'voyna-mirov'
    assert ingest_book.slug_for('Война миров', 'Герберт Уэллс',
                                ['voyna-mirov']) == 'uells-voyna-mirov'
    assert ingest_book.slug_for('Война миров', '', ['voyna-mirov']) == 'voyna-mirov-2'
