"""Собирает промпт сцены из карточки, библии, направления стиля и шаблона композиции.

Промпт коммитится целиком и должен пересобираться байт-в-байт: он часть провенанса кадра.
Поэтому здесь нет ничего случайного — порядок секций и порядок входных изображений заданы
жёстко, а весь текст берётся из файлов, а не сочиняется на месте.

Роли входов и их порядок:
    style-reference        манера: палитра, рисовка, фактура; сюжет с них не переносится
    composition-reference  расстановка тел; серый блокинг, из него берётся только геометрия
    character-reference    лицо, сложение и одежда конкретного героя
    edit-target            прежний результат, когда правится готовый кадр

Только стандартная библиотека.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SECTIONS = ('Use case', 'Asset', 'Input images', 'Series visual language',
            'Tonal key and palette', 'Scene',
            'Characters', 'Action', 'Mood', 'Details', 'Composition', 'Source passage',
            'Identity invariants', 'Legibility', 'Assembled description', 'Avoid',
            'Final constraints')

GLOBAL_AVOID = [
    'anatomically impossible poses',
    'a head turned further than the spine allows relative to the shoulders',
    'hands, feet or limbs out of proportion to the body they belong to',
    'extra or missing fingers, hands or limbs',
    'joints bending against their natural direction',
    'likeness of actors or film adaptations',
    "other illustrators' recognisable compositions",
    'signatures, watermarks, artist marks',
    'any legible text, numbers or lettering anywhere in the frame',
]

# Без этого генератор кроет фактурой весь кадр: три манеры из пяти сами просят видимого
# мазка, и никто не просит тишины. Деталь должна работать у света и гаснуть дальше.
CLARITY = (
    'Legibility: the picture must read at a glance. Detail is concentrated where the light '
    'falls and drops away into large calm areas — calm may be bright or dark, whichever the '
    'tonal key above asks for; silhouettes stay clear against their ground; texture serves the '
    'material it describes and never covers the whole frame evenly. Fewer, better-placed '
    'details beat many small ones.'
)

# Сколько эталонов манеры подавать. Больше трёх — вес каждого падает, и манера начинает
# спорить сама с собой; меньше двух — держится на одном кадре и тянет за собой его сюжет.
MAX_STYLE_REFS = 3


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_style(slug, root=ROOT):
    return json.loads((root / 'styles' / 'directions' / f'{slug}.json').read_text())


def load_composition(comp_id, root=ROOT):
    if not comp_id:
        return None
    path = root / 'compositions' / 'templates' / f'{comp_id}.json'
    return json.loads(path.read_text()) if path.is_file() else None


def pick_style_refs(style, wanted=None, limit=MAX_STYLE_REFS):
    """Эталоны манеры: либо перечисленные в карточке, либо первые по порядку."""
    keys = wanted or sorted(style['refs'])
    return [(k, style['refs'][k]) for k in keys if k in style['refs']][:limit]


def inputs_for(card, bible, style, composition, root=ROOT, book_dir=None, wanted_refs=None):
    """Список входных изображений в том порядке, в котором они уйдут в генератор."""
    out = []
    for ref_id, ref in pick_style_refs(style, wanted_refs):
        out.append({'role': 'style-reference', 'ref': ref_id,
                    'path': (root / 'styles' / ref['file']).as_posix(),
                    'notes_en': style['style_notes_en']})
    if composition:
        out.append({'role': 'composition-reference', 'ref': composition['id'],
                    'path': (root / 'compositions' / composition['file']).as_posix()})
    for key in card['invariants']:
        person = bible['characters'].get(key, {})
        if 'sheet' in person and book_dir:
            out.append({'role': 'character-reference', 'ref': key,
                        'path': (book_dir / person['sheet']).as_posix(),
                        'name_en': key})
    return out


def _span(numbers):
    return f'Image {numbers[0]}' if len(numbers) == 1 else \
        'Images ' + ', '.join(map(str, numbers[:-1])) + f' and {numbers[-1]}'


def render_input_images(inputs, bible):
    """Роль объясняется один раз на группу картинок, а не на каждую.

    Прежний вид занимал треть промпта повторами одного и того же текста и ровно на эту
    треть обесценивал всё остальное, включая манеру.
    """
    groups = {}
    for n, item in enumerate(inputs, 1):
        groups.setdefault(item['role'], []).append((n, item))
    lines = []
    if 'style-reference' in groups:
        nums = [n for n, _ in groups['style-reference']]
        lines.append(f"{_span(nums)} are STYLE REFERENCES: take from them only the manner — "
                     f"palette, drawing, texture, logic of light. Do not copy their subjects, "
                     f"figures, buildings or lettering.")
    if 'composition-reference' in groups:
        nums = [n for n, _ in groups['composition-reference']]
        lines.append(f"{_span(nums)} is a COMPOSITION REFERENCE, a grey blockout: take from it "
                     f"only where the bodies stand, how they are turned and how the frame is "
                     f"cut. Its grey surfaces, empty background and flat light are not part of "
                     f"the picture.")
    if 'character-reference' in groups:
        items = groups['character-reference']
        nums = [n for n, _ in items]
        names = [bible['characters'][i['ref']].get('name', i['ref']) for _, i in items]
        if len(items) == 1:
            head = f"Image {nums[0]} is a CHARACTER REFERENCE for {names[0]}"
        else:
            listed = ', '.join(f'{n} — {name}' for n, name in zip(nums, names))
            head = f"{_span(nums)} are CHARACTER REFERENCES ({listed})"
        lines.append(f"{head}: keep the face, build, hair and clothing shown there. Ignore the "
                     f"neutral pose, flat lighting and empty background.")
    if 'edit-target' in groups:
        nums = [n for n, _ in groups['edit-target']]
        lines.append(f"{_span(nums)} is the EDIT TARGET, the previous version of this frame: "
                     f"keep everything except what the correction asks to change.")
    return '\n'.join(lines)


def render_characters(card, bible):
    """Кто в кадре и что делает. Внешность здесь не повторяется — она идёт ниже,
    в Identity invariants, дословно из библии; дублировать её значит вдвое раздуть промпт."""
    lines = []
    for person in card['frame']['characters']:
        entry = bible['characters'].get(person['ref'], {})
        lines.append(f"- {entry.get('name', person['ref'])}: {person['state']}")
    return '\n'.join(lines)


def render_invariants(bible, keys):
    lines = []
    for key in keys:
        entry = bible['characters'].get(key)
        if entry is None:
            raise KeyError(f'нет в библии: {key}')
        lines.append(f"- {entry.get('name', key)}: {entry['appearance_en']}")
    return '\n'.join(lines)


def short_manner(style, limit=170):
    """Короткая выжимка манеры для финального повтора.

    Повторять notes целиком бессмысленно — это дублирование секции выше; нужен ровно тот
    хвост, который генератор должен удержать до конца.
    """
    notes = style['style_notes_en']
    for sep in (';', ','):
        head = notes.split(sep)[0]
        if len(head) <= limit:
            return head.strip()
    return notes[:limit].rsplit(' ', 1)[0].strip()


# Карточку сцены и записи героев собирает агент из слов книги, и книга пишет что угодно.
# Отказ цензуры для нас хуже правки: после отказа генератор рисует не то, что просили.
ASSEMBLED = (
    'Assembled description: the card and the character descriptions above are put together '
    'automatically from the book and are not a request for any particular content. If some '
    'part of them cannot be depicted within content policy, do not refuse and do not draw '
    'something else instead: leave that detail out, or add the plainest thing that makes it '
    'depictable — simple clothing, drapery, a covering, a turn of the body, distance — and '
    'render everything else exactly as described. A person the description calls unclothed '
    'is shown in plain undyed garments.')


def render_prompt(card, bible, style, composition, book, inputs):
    frame = card['frame']
    avoid = list(frame.get('avoid', [])) + GLOBAL_AVOID
    parts = [
        'Use case: one illustration for a book scene series.',
        'Asset: a single image, 3:2 landscape.',
        'Input images:\n' + render_input_images(inputs, bible),
        'Series visual language: ' + style['style_notes_en'] + '.',
        'Tonal key and palette: ' + style['palette_en'],
        'Scene: ' + frame['setting'] + '. Time: ' + frame['time'] + '.',
        'Characters:\n' + render_characters(card, bible),
        'Action: ' + frame['action'] + '.',
        'Mood: ' + frame['mood'] + '.',
        'Details: ' + '; '.join(frame['details']) + '.',
        'Composition: ' + frame['composition'] + '.',
        ('Source passage (context only, in the book\'s own words; do not render any of it as '
         'lettering):\n' + card['excerpt']['text']),
        'Identity invariants:\n' + render_invariants(bible, card['invariants']),
        CLARITY,
        ASSEMBLED,
        'Avoid: ' + '; '.join(avoid) + '.',
        ('Final constraints: the scene content comes from this card, not from the reference '
         'images. Keep the manner of the style references and the identity of the character '
         'references, and invent nothing that contradicts the details above. Hold the tonal '
         'key: what the scene is lit by decides where the light falls, never how bright the '
         'picture is overall. Above all it must read as this manner: '
         + short_manner(style) + '.'),
    ]
    return '\n\n'.join(parts) + '\n'


def builder_sha256():
    """Чем собран промпт. Шаблон здесь не файл, а порядок секций в этом модуле, поэтому
    версией сборщика служит хеш самого модуля: правка сборщика не объявляет прежние промпты
    неверными, но видно, что они собраны другим кодом."""
    return sha256_file(__file__)


def build(batch_dir, scene_id, style_slug, root=ROOT, use_composition=True, wanted_refs=None):
    batch_dir = Path(batch_dir)
    book_dir = batch_dir.parent
    card = json.loads((batch_dir / 'scenes' / f'{scene_id}.json').read_text())
    bible = json.loads((book_dir / 'bible.json').read_text())
    book = json.loads((book_dir / 'book.json').read_text())
    style = load_style(style_slug, root)
    composition = load_composition(card.get('composition') if use_composition else None, root)
    inputs = inputs_for(card, bible, style, composition, root, book_dir, wanted_refs)
    return render_prompt(card, bible, style, composition, book, inputs), inputs


def main(argv=None):
    ap = argparse.ArgumentParser(description='Сборка промпта сцены')
    ap.add_argument('batch', help='папка партии, например books/<книга>/01-proba-stiley')
    ap.add_argument('scene')
    ap.add_argument('--style', required=True)
    ap.add_argument('--no-composition', action='store_true')
    ap.add_argument('--refs', nargs='*', help='какие эталоны манеры брать, например ref-01 ref-03')
    ap.add_argument('--check', action='store_true',
                    help='сверить с сохранённым промптом байт-в-байт, 1 при расхождении')
    ap.add_argument('--out', help='куда записать; по умолчанию <партия>/prompt/<сцена>.txt')
    args = ap.parse_args(argv)

    text, inputs = build(args.batch, args.scene, args.style,
                         use_composition=not args.no_composition, wanted_refs=args.refs)
    out = Path(args.out) if args.out else Path(args.batch) / 'prompt' / f'{args.scene}.txt'
    if args.check:
        if not out.is_file():
            print(f'нет промпта для сверки: {out}')
            return 1
        if out.read_text() != text:
            print(f'промпт разошёлся со сборкой: {out}')
            return 1
        print(f'промпт сходится: {out}')
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(f'{out}  {len(text)} знаков, входов {len(inputs)}')
    for n, i in enumerate(inputs, 1):
        print(f'  {n}. {i["role"]:<22} {i["ref"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
