import hashlib
import json

import check_rights

PARAGRAPHS = ['Первый абзац книги.', 'Второй абзац книги.', 'Третий абзац книги.']


def sha(text):
    return hashlib.sha256(check_rights.normalize(text).encode('utf-8')).hexdigest()


def make_book(tmp_path, status='protected', chars=50000, scenes=(), refs=None, inputs=None):
    slug = 'test-book'
    batch = tmp_path / 'books' / slug / '01-batch'
    for folder in ('scenes', 'prompt', 'input', 'metadata'):
        (batch / folder).mkdir(parents=True, exist_ok=True)
    (tmp_path / 'books' / slug / 'book.json').write_text(json.dumps({
        'slug': slug, 'title': 'Книга', 'author': 'Автор',
        'rights': {'status': status, 'basis': 'проверено', 'checked': '2026-09-07'},
        'source': {'format': 'txt', 'sha256': 'x', 'chars': chars,
                   'paragraphs': len(PARAGRAPHS)},
        'paragraph_sha256': [sha(p) for p in PARAGRAPHS],
        'chapters': [{'index': 1, 'title': 'Глава', 'paragraphs': [0, 3]}],
    }, ensure_ascii=False), encoding='utf-8')
    entries = []
    for scene in scenes:
        (batch / 'scenes' / (scene['id'] + '.json')).write_text(
            json.dumps(scene, ensure_ascii=False), encoding='utf-8')
        entries.append({'id': scene['id'], 'card': 'scenes/%s.json' % scene['id'],
                        'inputs': list(inputs or [])})
    (batch / 'metadata' / 'request.json').write_text(json.dumps({
        'schema_version': 2, 'book': slug, 'scenes': entries}, ensure_ascii=False),
        encoding='utf-8')
    (batch / 'metadata' / 'refs.json').write_text(
        json.dumps(refs or {}, ensure_ascii=False), encoding='utf-8')
    return tmp_path


def scene(text, paragraphs=(0, 1), scene_id='01-scene'):
    return {'id': scene_id, 'book': 'test-book', 'title': 'Сцена', 'order': 1,
            'locator': {'chapter': 1, 'paragraphs': list(paragraphs)},
            'excerpt': {'text': text, 'attribution': 'Автор, «Книга»'}}


def test_protected_rejects_three_paragraphs(tmp_path):
    root = make_book(tmp_path, scenes=[scene('\n\n'.join(PARAGRAPHS), (0, 3))])
    violations = check_rights.check_all(root)
    assert any('01-scene' in v and 'абзац' in v for v in violations), violations


def test_protected_rejects_long_excerpt(tmp_path):
    root = make_book(tmp_path, scenes=[scene('а' * 1600)])
    assert any('1500' in v for v in check_rights.check_all(root))


def test_protected_rejects_share_over_three_percent(tmp_path):
    root = make_book(tmp_path, chars=50000, scenes=[
        scene('а' * 1000, scene_id='01-scene'),
        scene('б' * 1000, scene_id='02-scene')])
    assert any('3%' in v for v in check_rights.check_all(root))


def test_public_domain_lifts_limits(tmp_path):
    root = make_book(tmp_path, status='public-domain', scenes=[scene('а' * 1600)])
    assert check_rights.check_all(root) == []


def test_public_domain_without_basis_is_a_violation(tmp_path):
    root = make_book(tmp_path, status='public-domain')
    book = root / 'books' / 'test-book' / 'book.json'
    data = json.loads(book.read_text(encoding='utf-8'))
    del data['rights']['basis']
    book.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    assert any('basis' in v for v in check_rights.check_all(root))


def test_book_file_outside_source_is_a_violation(tmp_path):
    root = make_book(tmp_path)
    (root / 'books' / 'test-book' / 'book.fb2').write_bytes(b'x')
    assert any('файл книги' in v for v in check_rights.check_all(root))


def test_book_file_inside_source_is_fine(tmp_path):
    root = make_book(tmp_path)
    source = root / 'books' / 'test-book' / 'source'
    source.mkdir(parents=True, exist_ok=True)
    (source / 'book.fb2').write_bytes(b'x')
    assert check_rights.check_all(root) == []


def test_large_text_in_input_is_a_violation(tmp_path):
    root = make_book(tmp_path)
    notes = root / 'books' / 'test-book' / '01-batch' / 'input' / 'notes.txt'
    notes.write_text('x' * 5000, encoding='utf-8')
    assert any('4096' in v for v in check_rights.check_all(root))


def test_style_reference_without_refs_entry(tmp_path):
    root = make_book(tmp_path, scenes=[scene(PARAGRAPHS[0])],
                     inputs=[{'path': 'input/ref-01.png', 'role': 'style-reference',
                              'stored': True, 'sha256': 'x'}])
    assert any('refs.json' in v for v in check_rights.check_all(root))


def test_unfree_license_stored_is_a_violation(tmp_path):
    refs = {'ref-01': {'file': 'input/ref-01.png', 'stored': True,
                       'license': 'all-rights-reserved', 'license_basis': 'нет',
                       'source': 's', 'author': 'a'}}
    root = make_book(tmp_path, scenes=[scene(PARAGRAPHS[0])], refs=refs,
                     inputs=[{'path': 'input/ref-01.png', 'role': 'style-reference',
                              'stored': True, 'sha256': 'x'}])
    assert any('лицензия' in v for v in check_rights.check_all(root))


def test_unfree_license_not_stored_is_fine(tmp_path):
    refs = {'ref-01': {'file': 'refs-local/ref-01.png', 'stored': False,
                       'license': 'all-rights-reserved', 'license_basis': 'локальный',
                       'source': 's', 'author': 'a'}}
    root = make_book(tmp_path, scenes=[scene(PARAGRAPHS[0])], refs=refs,
                     inputs=[{'path': 'refs-local/ref-01.png', 'role': 'style-reference',
                              'stored': False, 'sha256': 'x'}])
    assert check_rights.check_all(root) == []


def test_free_license_without_basis_is_a_violation(tmp_path):
    refs = {'ref-01': {'file': 'input/ref-01.png', 'stored': True,
                       'license': 'CC0', 'source': 's', 'author': 'a'}}
    root = make_book(tmp_path, scenes=[scene(PARAGRAPHS[0])], refs=refs,
                     inputs=[{'path': 'input/ref-01.png', 'role': 'style-reference',
                              'stored': True, 'sha256': 'x'}])
    assert any('license_basis' in v for v in check_rights.check_all(root))


def test_excerpt_not_from_locator_paragraphs(tmp_path):
    root = make_book(tmp_path, scenes=[scene('Чужой текст.', (0, 1))])
    assert any('локатор' in v for v in check_rights.check_all(root))


def test_excerpt_matching_locator_is_fine(tmp_path):
    root = make_book(tmp_path, scenes=[scene(PARAGRAPHS[1], (1, 2))])
    assert check_rights.check_all(root) == []


def test_excerpt_survives_whitespace_differences(tmp_path):
    noisy = '  ' + PARAGRAPHS[0].replace(' ', '  ') + ' '
    root = make_book(tmp_path, scenes=[scene(noisy, (0, 1))])
    assert check_rights.check_all(root) == []


def test_violations_start_with_the_offending_path(tmp_path):
    root = make_book(tmp_path, scenes=[scene('а' * 1600)])
    for violation in check_rights.check_all(root):
        assert violation.startswith('books/test-book'), violation
