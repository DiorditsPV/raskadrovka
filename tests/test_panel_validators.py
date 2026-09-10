"""Проверки записи библии: то, что валидатор обязан ловить, и то, что пропускать.

Фикстура — книга из трёх абзацев двух глав: этого хватает, чтобы локатор мог указать мимо,
не в ту главу и на пустой полуинтервал.
"""
import json

import pytest

import validators

SLUG = 'test-book'
PARAGRAPHS = [{'i': 0, 'chapter': 1, 'text': 'Первый абзац.'},
              {'i': 1, 'chapter': 1, 'text': 'Второй абзац, в нём про волосы.'},
              {'i': 2, 'chapter': 2, 'text': 'Третий абзац, другая глава.'}]

GOOD = {'name': 'Герой', 'appearance': 'Русое описание для человека.',
        'appearance_en': 'a plain english description for the prompt',
        'locators': [{'chapter': 1, 'paragraphs': [1, 2]}],
        'audit': {'age': 1, 'build': 1, 'face': 1, 'eyes': 0.5, 'hair': 1,
                  'skin': 1, 'clothing': 1, 'gear': 1, 'marks': 1, 'bearing': 0.5},
        'understanding': 9.0}


@pytest.fixture
def book(tmp_path):
    cache = tmp_path / 'cache' / SLUG
    cache.mkdir(parents=True)
    (cache / 'paragraphs.jsonl').write_text(
        '\n'.join(json.dumps(p, ensure_ascii=False) for p in PARAGRAPHS), encoding='utf-8')
    return tmp_path


def check(entry, book):
    return validators.check_bible_entry('hero', entry, SLUG, book)


def test_good_entry_passes(book):
    assert check(GOOD, book) == []


def test_missing_field_is_named_and_is_not_an_error(book):
    """Поле, которого нет, — «не хватает»; противоречие — «не сходится». Красным только второе."""
    entry = {k: v for k, v in GOOD.items() if k != 'appearance_en'}
    out = check(entry, book)
    assert any('нет поля appearance_en' in c for c in out)
    assert all(c.level == 'missing' for c in out)


def test_contradiction_is_an_error_not_a_gap(book):
    out = check(dict(GOOD, understanding=10.0), book)
    assert out and all(c.level == 'error' for c in out)


def test_empty_locators_rejected(book):
    assert any('непустой список' in c for c in check(dict(GOOD, locators=[]), book))


def test_point_locator_rejected_as_empty_interval(book):
    entry = dict(GOOD, locators=[{'chapter': 1, 'paragraphs': [1, 1]}])
    out = check(entry, book)
    assert any('полуинтервал' in c and '[1, 2]' in c for c in out)


def test_locator_beyond_the_book_rejected(book):
    entry = dict(GOOD, locators=[{'chapter': 1, 'paragraphs': [5, 6]}])
    assert any('в книге нет абзацев [5]' in c for c in check(entry, book))


def test_locator_with_wrong_chapter_rejected(book):
    """Именно этот случай и портит указатель незаметно: описание верное, ссылка врёт."""
    entry = dict(GOOD, locators=[{'chapter': 1, 'paragraphs': [2, 3]}])
    assert any('глава 1' in c and '[2]' in c for c in check(entry, book))


def test_locator_across_two_chapters_rejected(book):
    entry = dict(GOOD, locators=[{'chapter': 1, 'paragraphs': [1, 3]}])
    assert any('[1, 2]' in c for c in check(entry, book))


def test_audit_keys_must_be_exactly_ten(book):
    audit = {k: v for k, v in GOOD['audit'].items() if k != 'eyes'}
    out = check(dict(GOOD, audit=audit), book)
    assert any('нет клеток eyes' in c for c in out)


def test_audit_score_out_of_set_rejected(book):
    audit = dict(GOOD['audit'], eyes=0.7)
    assert any('только 0, 0.5 или 1' in c for c in check(dict(GOOD, audit=audit), book))


def test_understanding_must_equal_the_sum(book):
    out = check(dict(GOOD, understanding=10.0), book)
    assert any('сумма клеток аудита = 9' in c for c in out)


def test_language_of_the_two_descriptions_is_checked(book):
    out = check(dict(GOOD, appearance_en='описание по-русски'), book)
    assert any('appearance_en пишется по-английски' in c for c in out)
    out = check(dict(GOOD, appearance='an english description'), book)
    assert any('appearance пишется по-русски' in c for c in out)


def test_sheet_without_hash_rejected(book):
    (book / 'books' / SLUG / 'characters').mkdir(parents=True)
    sheet = book / 'books' / SLUG / 'characters' / 'hero.png'
    sheet.write_bytes(b'not really a png')
    entry = dict(GOOD, sheet='characters/hero.png')
    assert any('нет sheet_sha256' in c for c in check(entry, book))


def test_sheet_pointing_at_nothing_rejected(book):
    entry = dict(GOOD, sheet='characters/hero.png', sheet_sha256='0' * 64)
    assert any('файла characters/hero.png нет' in c for c in check(entry, book))


def test_without_cache_only_the_form_is_checked(tmp_path):
    """Кеш книги игнорируется git-ом: на чистом клоне проверяется хотя бы форма локатора."""
    assert validators.check_bible_entry('hero', GOOD, SLUG, tmp_path) == []
    entry = dict(GOOD, locators=[{'chapter': 1, 'paragraphs': [9, 9]}])
    assert any('полуинтервал' in c for c in validators.check_bible_entry(
        'hero', entry, SLUG, tmp_path))
