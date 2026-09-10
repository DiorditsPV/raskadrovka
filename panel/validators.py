"""Контрактные проверки записей библии и карточек — общие для агента и редактора панели.

Проверка возвращает список претензий по-русски. Тот же текст показывается человеку в
редакторе и дословно дописывается в инструкцию агента на повторной попытке, поэтому
претензия обязана называть, что не так и чем чинится, а не «неверный формат».

Главная из проверок — локаторы. Указатель на книгу — единственное поле, чью неверность не
видно по результату: описание внешности остаётся правильным, а сослаться на него уже нельзя.
Один раз это уже стоило шести неверных локаторов из восьми, поэтому здесь локатор сверяется
с разобранной книгой, а не читается как число.

Только стандартная библиотека.
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Десять атрибутов аудита понимания, порядок как в скилле raskadrovka-characters.
AUDIT_KEYS = ('age', 'build', 'face', 'eyes', 'hair', 'skin',
              'clothing', 'gear', 'marks', 'bearing')
AUDIT_SCORES = (0, 0.5, 1)
AUDIT_PASS = 8

REQUIRED = ('name', 'appearance', 'appearance_en', 'locators', 'understanding', 'audit')
CYRILLIC = re.compile(r'[а-яёА-ЯЁ]')


class Complaint(str):
    """Претензия к записи. Строка — чтобы дописываться агенту дословно, но с уровнем.

    Уровня два, и разница не косметическая. `error` — запись противоречит себе или книге:
    локатор указывает не на ту главу, балл не сходится с клетками, английское поле написано
    кириллицей. Это чинят. `missing` — поля контракта в записи ещё нет: чаще всего оттого,
    что запись писали до того, как поле появилось. Это дописывают, и красным оно не горит,
    иначе «не доделано» и «сломано» становятся неразличимы, а на экране всё красное.
    """

    def __new__(cls, text, level='error'):
        out = super().__new__(cls, text)
        out.level = level
        return out


def missing(text):
    return Complaint(text, 'missing')


class Complaints(list):
    """Список претензий, в котором обычная строка становится «не сходится».

    Уровень по умолчанию — ошибка, а исключение называется явно через `missing()`. Иначе
    забытая обёртка молча делает противоречие безобидным, а это ровно тот класс дефектов,
    ради которого валидатор и написан.
    """

    def append(self, item):
        super().append(item if isinstance(item, Complaint) else Complaint(item))

    def extend(self, items):
        for item in items:
            self.append(item)

    def __iadd__(self, items):
        self.extend(items)
        return self


def paragraphs(slug, root=ROOT):
    """Разобранная книга из кеша. Кеш игнорируется git-ом, поэтому его может не быть."""
    cache = Path(root) / 'cache' / slug / 'paragraphs.jsonl'
    if not cache.is_file():
        return None
    return [json.loads(line) for line in cache.read_text(encoding='utf-8').splitlines()]


def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_locators(items, book, out, where=''):
    """Локатор — полуинтервал `[a, b)` абзацев одной главы, конвенция одна на репозиторий.

    `book` — разобранная книга или None: без кеша проверяется только форма.
    """
    index = {p['i']: p for p in book} if book is not None else None
    if not isinstance(items, list) or not items:
        out.append(f'{where}locators: должен быть непустой список — у каждой черты внешности '
                   f'нужен указатель на абзац книги')
        return
    for n, loc in enumerate(items, 1):
        tag = f'{where}locators[{n}]'
        if not isinstance(loc, dict) or set(loc) - {'chapter', 'paragraphs'}:
            out.append(f'{tag}: ожидается {{"chapter": N, "paragraphs": [a, b]}}, получено {loc!r}')
            continue
        chapter, span = loc.get('chapter'), loc.get('paragraphs')
        if not isinstance(chapter, int):
            out.append(f'{tag}: chapter должен быть числом, получено {chapter!r}')
        if (not isinstance(span, list) or len(span) != 2
                or not all(isinstance(v, int) for v in span)):
            out.append(f'{tag}: paragraphs — два целых числа [a, b], получено {span!r}')
            continue
        a, b = span
        if b <= a:
            out.append(f'{tag}: paragraphs — полуинтервал, [{a}, {b}] пуст; один абзац {a} '
                       f'записывается как [{a}, {a + 1}]')
            continue
        if index is None:
            continue
        missing = [i for i in range(a, b) if i not in index]
        if missing:
            out.append(f'{tag}: в книге нет абзацев {missing} — всего абзацев {len(index)}')
            continue
        chapters = sorted({index[i]['chapter'] for i in range(a, b)})
        if isinstance(chapter, int) and chapters != [chapter]:
            out.append(f'{tag}: абзацы {a}–{b - 1} лежат в главе {chapters}, а в локаторе '
                       f'записана глава {chapter}')


def check_audit(audit, understanding, out, where=''):
    """Десять клеток по 0 / 0.5 / 1; `understanding` — их сумма, а не отдельное мнение."""
    if audit is None:
        return          # об отсутствии поля уже сказано выше, второй раз не повторяем
    if not isinstance(audit, dict):
        out.append(f'{where}audit: ожидается объект с десятью ключами {", ".join(AUDIT_KEYS)}')
        return
    gaps = [k for k in AUDIT_KEYS if k not in audit]
    extra = [k for k in audit if k not in AUDIT_KEYS]
    if gaps:
        out.append(f'{where}audit: нет клеток {", ".join(gaps)}')
    if extra:
        out.append(f'{where}audit: лишние клетки {", ".join(extra)} — ключи ровно десять')
    bad = {k: v for k, v in audit.items() if k in AUDIT_KEYS and v not in AUDIT_SCORES}
    if bad:
        out.append(f'{where}audit: балл бывает только 0, 0.5 или 1; получено {bad}')
    if gaps or bad:
        return
    total = sum(audit[k] for k in AUDIT_KEYS)
    if not isinstance(understanding, (int, float)):
        out.append(f'{where}understanding: должно быть числом, получено {understanding!r}')
    elif abs(total - understanding) > 1e-9:
        out.append(f'{where}understanding = {understanding}, а сумма клеток аудита = {total}; '
                   f'балл не мнение, а сумма')


def check_bible_entry(key, entry, slug=None, root=ROOT, book=None):
    """Запись героя в `bible.json`. Возвращает список претензий; пустой — запись годна."""
    out = Complaints()
    where = f'{key}: '
    if not isinstance(entry, dict):
        out.append(f'{where}запись должна быть объектом JSON')
        return out

    for field in REQUIRED:
        if field not in entry:
            out.append(missing(f'{where}нет поля {field}'))

    for field in ('name', 'appearance', 'appearance_en'):
        value = entry.get(field)
        if field in entry and (not isinstance(value, str) or not value.strip()):
            out.append(f'{where}{field}: непустая строка, получено {value!r}')

    russian = entry.get('appearance')
    english = entry.get('appearance_en')
    if isinstance(russian, str) and russian.strip() and not CYRILLIC.search(russian):
        out.append(f'{where}appearance пишется по-русски — это описание для человека; '
                   f'английское идёт в appearance_en')
    if isinstance(english, str) and CYRILLIC.search(english):
        out.append(f'{where}appearance_en пишется по-английски — это текст промпта, '
                   f'кириллица в нём генератору не поможет')

    if book is None and slug:
        book = paragraphs(slug, root)
    if 'locators' in entry:
        check_locators(entry['locators'], book, out, where)
    if 'audit' in entry or 'understanding' in entry:
        check_audit(entry.get('audit'), entry.get('understanding'), out, where)

    sheet = entry.get('sheet')
    if sheet:
        path = Path(root) / 'books' / slug / sheet if slug else Path(root) / sheet
        if not path.is_file():
            out.append(f'{where}sheet: файла {sheet} нет — лист принимается панелью, '
                       f'запись о нём не пишется руками')
        elif entry.get('sheet_sha256') and _sha256_file(path) != entry['sheet_sha256']:
            out.append(f'{where}sheet_sha256 не совпадает с файлом {sheet}')
        elif not entry.get('sheet_sha256'):
            out.append(f'{where}есть sheet, но нет sheet_sha256')
    return out


def check_bible(bible, slug=None, root=ROOT, keys=None):
    """Вся библия или выбранные ключи. Возвращает список претензий по всем героям."""
    out = Complaints()
    characters = bible.get('characters')
    if not isinstance(characters, dict):
        out.append('bible.json: нет объекта characters')
        return out
    book = paragraphs(slug, root) if slug else None
    for key in (keys if keys is not None else sorted(characters)):
        if key not in characters:
            out.append(f'{key}: записи нет в bible.json')
            continue
        out += check_bible_entry(key, characters[key], slug, root, book)
    for key, place in (bible.get('places') or {}).items():
        if isinstance(place, dict) and 'locators' in place:
            check_locators(place['locators'], book, out, f'место {key}: ')
    return out
