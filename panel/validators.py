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

REQUIRED = ('name', 'appearance', 'appearance_en', 'subject_en', 'locators',
            'understanding', 'audit')
CYRILLIC = re.compile(r'[а-яёА-ЯЁ]')


def _listed(values):
    """Числа и ключи для человека: «5, 6 и 7», а не «[5, 6, 7]». Список Python в тексте,
    который читает человек, — это протёкшая наружу структура данных, а не сообщение."""
    items = [str(v) for v in values]
    if len(items) < 2:
        return items[0] if items else ''
    return ', '.join(items[:-1]) + ' и ' + items[-1]


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
    """Разобранная книга из кеша. Кеш игнорируется git-ом, поэтому его может не быть.

    Пустые строки пропускаются. Пустой разбор — файл из одного перевода строки — не редкость,
    и `json.loads('')` на нём ронял весь экран книги сообщением про «line 1 column 1».
    """
    cache = Path(root) / 'cache' / slug / 'paragraphs.jsonl'
    if not cache.is_file():
        return None
    return [json.loads(line) for line in cache.read_text(encoding='utf-8').splitlines()
            if line.strip()]


def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_locators(items, book, out, where=''):
    """Локатор — полуинтервал `[a, b)` абзацев одной главы, конвенция одна на репозиторий.

    `book` — разобранная книга или None: без кеша проверяется только форма.
    """
    # Абзац без «i» — не повод ронять весь экран книги: проверяется то, что можно.
    index = ({p['i']: p for p in book if isinstance(p, dict) and 'i' in p}
             if book is not None else None)
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
        absent = [i for i in range(a, b) if i not in index]
        if absent:
            out.append(f'{tag}: в книге нет абзацев {_listed(absent)} — всего абзацев '
                       f'{len(index)}')
            continue
        chapters = sorted({index[i]['chapter'] for i in range(a, b)})
        if isinstance(chapter, int) and chapters != [chapter]:
            where = ('главе ' if len(chapters) == 1 else 'главах ') + _listed(chapters)
            out.append(f'{tag}: абзацы {a}–{b - 1} лежат в {where}, а в локаторе '
                       f'записана глава {chapter}')


def check_audit(audit, understanding, out, where=''):
    """Десять клеток по 0 / 0.5 / 1; `understanding` — их сумма, а не отдельное мнение."""
    if audit is None:
        return          # об отсутствии поля уже сказано выше, второй раз не повторяем
    if not isinstance(audit, dict):
        out.append(f'{where}audit: ожидается объект с десятью ключами {", ".join(AUDIT_KEYS)}')
        return
    absent = [k for k in AUDIT_KEYS if k not in audit]
    extra = [k for k in audit if k not in AUDIT_KEYS]
    if absent:
        out.append(f'{where}audit: нет клеток {", ".join(absent)}')
    if extra:
        out.append(f'{where}audit: лишние клетки {", ".join(extra)} — ключи ровно десять')
    bad = {k: v for k, v in audit.items() if k in AUDIT_KEYS and v not in AUDIT_SCORES}
    if bad:
        out.append(f'{where}audit: балл бывает только 0, 0.5 или 1; получено {bad}')
    if absent or bad:
        return
    total = sum(audit[k] for k in AUDIT_KEYS)
    if not isinstance(understanding, (int, float)):
        out.append(f'{where}understanding: должно быть числом, получено {understanding!r}')
    elif abs(total - understanding) > 1e-9:
        out.append(f'{where}understanding = {understanding}, а сумма клеток аудита = {total}; '
                   f'балл не мнение, а сумма')


def record_fingerprint(entry):
    """Отпечаток сужденческой части записи: внешность, указатели, аудит.

    По нему видно, что запись переписали после того, как пробелы объяснили: старый пробел
    может говорить «книга не даёт цвета глаз», когда новая запись его уже нашла.
    """
    payload = json.dumps({'appearance_en': entry.get('appearance_en'),
                          'locators': entry.get('locators'),
                          'audit': entry.get('audit')}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def fresh_gaps(entry):
    """Пробелы, относящиеся к нынешней записи. Устаревшие не в счёт: они описывают книгу,
    прочитанную для прежнего текста, и снова становятся вопросом.

    Живёт здесь, а не в панели, потому что читают отсюда двое: экран, который решает, устарел
    ли лист, и генератор, который лист рисует. Прочти они разное — свежий лист рождался бы
    помеченным «по прежней записи».
    """
    gaps = entry.get('gaps') or {}
    if not gaps or entry.get('gaps_for') != record_fingerprint(entry):
        return {}
    return gaps


# Клетка считается просевшей, пока она не полная: и 0, и 0.5 значат, что книгу по этой
# черте ещё не дочитали.
def sagging(audit):
    if not isinstance(audit, dict):
        return []
    return [k for k in AUDIT_KEYS if audit.get(k) != 1]


def check_gaps(gaps, audit, out, where=''):
    """Объяснённые пробелы: клетка, чего книга не даёт и где искали.

    Пробел — не отговорка, а результат работы: он говорит, что книгу по этой черте прочли
    и в ней ничего нет. Поэтому у него два обязательных поля — `why` и `looked`: без второго
    «книга не даёт» неотличимо от «не искал».
    """
    if gaps is None:
        return
    if not isinstance(gaps, dict):
        out.append(f'{where}gaps: ожидается объект {{клетка: {{why, looked}}}}, получено '
                   f'{type(gaps).__name__}')
        return
    extra = [k for k in gaps if k not in AUDIT_KEYS]
    if extra:
        out.append(f'{where}gaps: клетки {_listed(extra)} в аудите нет; ключи те же десять')
    for cell in AUDIT_KEYS:
        if cell not in gaps:
            continue
        note = gaps[cell]
        if not isinstance(note, dict):
            out.append(f'{where}gaps.{cell}: ожидается объект с полями why и looked')
            continue
        for field in ('why', 'looked'):
            value = note.get(field)
            if not isinstance(value, str) or len(value.strip()) < 15:
                out.append(f'{where}gaps.{cell}.{field}: непустая фраза по-русски, '
                           f'получено {value!r}. why — чего книга не даёт, '
                           f'looked — где искали')
            elif not CYRILLIC.search(value):
                out.append(f'{where}gaps.{cell}.{field} пишется по-русски: это объяснение '
                           f'человеку, а не текст промпта')
        if isinstance(audit, dict) and audit.get(cell) == 1:
            out.append(f'{where}gaps.{cell}: клетка полная — пробела в ней быть не может; '
                       f'либо уберите пробел, либо опустите балл')


def check_bible_refine(key, entry, slug=None, root=ROOT, book=None):
    """Запись после добора: та же проверка плюс требование закрыть каждую просевшую клетку.

    Закрыть — значит поднять до единицы или записать пробел. Третьего исхода у добора нет:
    иначе он превращается в «посмотрел и ничего не сделал», и панель снова предложит его же.
    """
    out = check_bible_entry(key, entry, slug, root, book)
    if not isinstance(entry, dict):
        return out
    audit, gaps = entry.get('audit'), entry.get('gaps')
    check_gaps(gaps, audit, out, f'{key}: ')
    open_cells = [c for c in sagging(audit) if c not in (gaps or {})]
    if open_cells:
        out.append(f'{key}: клетки {_listed(open_cells)} остались просевшими и без пробела — '
                   f'по каждой либо поднимите балл, найдя описание в книге, либо запишите '
                   f'в gaps, чего книга не даёт и где вы искали')
    return out


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

    for field in ('name', 'appearance', 'appearance_en', 'subject_en'):
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
    subject = entry.get('subject_en')
    if isinstance(subject, str) and CYRILLIC.search(subject):
        out.append(f'{where}subject_en пишется по-английски — он идёт в промпт листа')
    if isinstance(subject, str) and len(subject) > 200:
        out.append(f'{where}subject_en — одна фраза о том, кто это, а не пересказ внешности; '
                   f'{len(subject)} знаков это много')

    if book is None and slug:
        book = paragraphs(slug, root)
    if 'locators' in entry:
        check_locators(entry['locators'], book, out, where)
    if 'audit' in entry or 'understanding' in entry:
        check_audit(entry.get('audit'), entry.get('understanding'), out, where)
    check_gaps(entry.get('gaps'), entry.get('audit'), out, where)

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


# — карточка сцены —

FRAME_KEYS = ('setting', 'action', 'mood', 'details', 'composition')
CARD_KEYS = ('id', 'book', 'title', 'order', 'locator', 'excerpt', 'caption', 'brief',
             'frame', 'invariants')


def check_scene_card(card_id, card, slug=None, root=ROOT, book=None, bible=None):
    """Карточка сцены. Замысел кадра словами, с отрывком книги и указателем на абзацы."""
    out = Complaints()
    where = f'{card_id}: '
    if not isinstance(card, dict):
        out.append(f'{where}карточка должна быть объектом JSON')
        return out
    for field in CARD_KEYS:
        if field not in card:
            out.append(missing(f'{where}нет поля {field}'))
    if card.get('id') and card['id'] != card_id:
        out.append(f'{where}id внутри карточки — «{card["id"]}», а файл называется '
                   f'«{card_id}»: имя файла и есть id')
    if slug and card.get('book') and card['book'] != slug:
        out.append(f'{where}book: «{card["book"]}», а карточка лежит в книге «{slug}»')

    if 'locator' in card:
        check_locators([card['locator']] if isinstance(card.get('locator'), dict)
                       else card['locator'], book, out, where)
    excerpt = card.get('excerpt')
    if isinstance(excerpt, dict):
        if not (excerpt.get('text') or '').strip():
            out.append(f'{where}excerpt.text пуст — отрывок книги в карточке обязателен')
        if not (excerpt.get('attribution') or '').strip():
            out.append(missing(f'{where}excerpt.attribution: чей текст и какое издание'))
    elif 'excerpt' in card:
        out.append(f'{where}excerpt: ожидается {{"text": …, "attribution": …}}')

    frame = card.get('frame')
    if isinstance(frame, dict):
        for field in FRAME_KEYS:
            if not frame.get(field):
                out.append(f'{where}frame.{field} пуст — это и есть замысел кадра')
        people = frame.get('characters')
        if not isinstance(people, list) or not people:
            out.append(f'{where}frame.characters: кто в кадре и что делает')
        else:
            for n, person in enumerate(people, 1):
                if not isinstance(person, dict) or not person.get('ref'):
                    out.append(f'{where}frame.characters[{n}]: нужен ref — ключ героя в библии')
                elif bible is not None and person['ref'] not in bible:
                    out.append(f'{where}frame.characters[{n}]: героя «{person["ref"]}» '
                               f'нет в библии')
        if CYRILLIC.search(json.dumps(frame, ensure_ascii=False)):
            out.append(f'{where}frame пишется по-английски: он целиком уходит в промпт')
    elif 'frame' in card:
        out.append(f'{where}frame: ожидается объект с замыслом кадра')

    keys = card.get('invariants')
    if isinstance(keys, list):
        if not keys:
            out.append(missing(f'{where}invariants пуст — кадр без единого героя бывает, '
                               f'но чаще это забытые ключи'))
        for key in keys:
            if bible is not None and key not in bible:
                out.append(f'{where}invariants: героя «{key}» нет в библии')
    elif 'invariants' in card:
        out.append(f'{where}invariants: список ключей героев из библии')

    if card.get('composition'):
        file = Path(root) / 'compositions' / 'templates' / f'{card["composition"]}.json'
        ref = Path(root) / 'compositions' / 'refs' / f'{card["composition"]}.png'
        if not (file.is_file() or ref.is_file()):
            out.append(f'{where}composition: шаблона «{card["composition"]}» нет '
                       f'в compositions/')
    return out

