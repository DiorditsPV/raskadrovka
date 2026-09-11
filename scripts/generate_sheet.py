"""Лист персонажа: кто это, без манеры и без композиции.

Лист лочит личность — возраст, сложение, лицо, волосы, кожу, одежду, экипировку, приметы.
Манеру он нести не должен: иначе при сборке сцены лист подерётся со стилевым направлением,
и кадр получится ни в той манере, ни в этой. Отсюда ровный свет, пустой фон, нейтральная
поза и три проекции — сколько угодно скучно, зато однозначно.

Промпт складывается из двух частей записи: `subject_en` — одна фраза о том, кто это
(суждение агента, из внешности не выводится), и `appearance_en` — внешность словами книги.
Сложенный промпт кладётся в запись рядом с листом, и по нему лист пересобирается дословно.

    python3 scripts/generate_sheet.py pierce-brown-red-rising eo
    python3 scripts/generate_sheet.py <книга> <ключ> --prompt-only
    python3 scripts/generate_sheet.py <книга> <ключ> --out cache/panel/<книга>/sheets/eo.png

Только стандартная библиотека.
"""
import argparse
import hashlib
import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'panel'))

import agent                                                # noqa: E402
import settings as panel_settings                           # noqa: E402
import validators                                           # noqa: E402

SHEET = """Style: a plain character reference sheet for production use, NOT a finished
illustration and NOT a scene. Three views of the same person arranged left to right on one sheet:
full-length front view, full-length three-quarter view, and a head-and-shoulders close-up. Hands
must be visible and clearly rendered in at least one view. Flat even studio illumination, no
dramatic light, no rim light, no cast shadows, no atmosphere. Plain neutral light grey
background, completely empty. Features, build, hair, skin and clothing identical across all three
views. Neutral relaxed standing pose, arms away from the body so the costume reads, face calm and
unexpressive. Natural restrained colour, true to the description. No artistic style, no painterly
flourish, no mood, no story, no environment — this sheet exists only to fix who this person is."""

TAIL = """
Asset: a single image, 3:2 landscape.

Avoid: dramatic lighting, background scenery, environment, props beyond what the description
names, mood, atmosphere, action, strong expression, artistic style of any kind, likeness of
actors, signatures, watermarks, any legible text, numbers or labels anywhere in the frame."""


# Черта, которой книга не даёт, — не повод её выдумать. Генератор без указания рисует
# что-нибудь заметное: шрам, необычный цвет глаз, украшение. Раздел говорит обратное:
# оставить обычным. Появляется он только когда пробелы записаны, поэтому промпт героя
# без пробелов остаётся прежним до байта и по-прежнему пересобирается.
UNSPECIFIED = ('Unspecified: the source does not describe this person\'s {traits}. Keep these '
               'ordinary and unremarkable — plain and average, nothing memorable; invent no '
               'colour, scars, tattoos, jewellery, insignia or accessories that the description '
               'above does not name.')

TRAITS_EN = {'age': 'age', 'build': 'build', 'face': 'face', 'eyes': 'eyes', 'hair': 'hair',
             'skin': 'skin', 'clothing': 'clothing', 'gear': 'gear',
             'marks': 'distinguishing marks', 'bearing': 'bearing'}


# Описание собирает агент из слов книги, и книга пишет что угодно: «naked old man» —
# цитата, а не заказ. Генератор на такое отвечает отказом цензуры, а после отказа рисует
# не то, что просили, а то, что пропустят. Абзац ниже даёт ему третий выход: опустить
# черту или одеть фигуру — и нарисовать остальное.
POLICY = """
Assembled description: the description above is put together automatically from the book and
is not a request for any particular content. If some part of it cannot be depicted within
content policy, do not refuse and do not draw something else instead: leave that detail out,
or add the plainest thing that makes it depictable — simple clothing, drapery, a covering —
and render everything else exactly as described. A person the description calls unclothed is
shown in plain undyed garments.""".strip()


def unspecified(gaps):
    """Раздел о том, чего книга не даёт. Порядок клеток — как в аудите, а не как в словаре:
    промпт обязан пересобираться байт в байт, а порядок ключей JSON этого не гарантирует."""
    traits = [TRAITS_EN[cell] for cell in validators.AUDIT_KEYS if cell in (gaps or {})]
    if not traits:
        return ''
    listed = traits[0] if len(traits) == 1 else ', '.join(traits[:-1]) + ' or ' + traits[-1]
    return '\n\n' + '\n'.join(textwrap.wrap(UNSPECIFIED.format(traits=listed), 98))


def body(subject_en, appearance_en, gaps=None):
    """Промпт листа: манера, потом кто это, потом внешность, потом чего книга не даёт,
    потом формат и запреты."""
    subject = (subject_en or '').strip().rstrip('.')
    appearance = (appearance_en or '').strip().rstrip('.')
    return (SHEET.strip() + '\n\n'
            + f'Subject: {subject}. {appearance}.' + unspecified(gaps)
            + '\n\n' + POLICY + '\n' + TAIL)


def about_the_person(prompt):
    """Часть промпта, идущая от записи героя: «кто это», внешность и пробелы.

    Постоянная часть — манера, формат, запреты, оговорка о цензуре — со временем меняется,
    и по всему тексту «лист по прежней записи» загоралось бы у всех разом от правки шаблона.
    Сравнивать надо то, что описывает человека.
    """
    if not prompt or '\n\nSubject: ' not in prompt:
        return prompt
    tail = prompt.split('\n\nSubject: ', 1)[1]
    for stop in ('\n\nAssembled description:', '\n\nAsset:'):
        if stop in tail:
            return tail.split(stop, 1)[0]
    return tail


def instruction(prompt_body, out_rel):
    """Инструкция Codex: нарисовать одно изображение и положить ровно сюда."""
    return ('Сгенерируй ОДНО изображение инструментом image_gen и сохрани его в файл\n'
            f'{out_rel} внутри текущего рабочего каталога.\n'
            'Ничего больше не делай: не создавай других файлов, не редактируй код, не коммить.\n\n'
            'Промпт для генерации — дословно:\n\n' + prompt_body)


def entry_of(slug, key, root=ROOT):
    file = Path(root) / 'books' / slug / 'bible.json'
    if not file.is_file():
        raise SystemExit(f'нет библии книги: {file}')
    data = json.loads(file.read_text(encoding='utf-8'))
    entry = (data.get('characters') or {}).get(key)
    if entry is None:
        raise SystemExit(f'в библии нет героя «{key}»')
    return file, data, entry


def make(slug, key, root=ROOT, out=None, subject=None, config=None,
         log=None, watch=None, should_stop=None, mine=None):
    """Собрать лист. Возвращает отчёт задания плюс путь, хеш и промпт.

    `out` — путь от корня репозитория. По умолчанию лист ложится сразу в книгу: так его
    делает человек в терминале, и его запуск — сам себе приёмка. Панель направляет лист
    в `cache/`, потому что там приёмку делает человек кнопкой.
    """
    root = Path(root)
    _, _, entry = entry_of(slug, key, root)
    subject_en = subject or entry.get('subject_en')
    if not subject_en:
        return {'ok': False, 'attempts': 0, 'complaints': [
            f'{key}: нет поля subject_en — одна фраза о том, кто это (роль, возраст, занятие); '
            f'её пишет «Собрать запись», либо задайте --subject'], 'tries': []}
    if not entry.get('appearance_en'):
        return {'ok': False, 'attempts': 0, 'complaints': [
            f'{key}: нет поля appearance_en — внешности словами книги по-английски'], 'tries': []}

    # Пробелы берутся тем же правилом, что и на экране: прочти генератор и экран разное,
    # свежий лист рождался бы помеченным «лист по прежней записи».
    prompt_body = body(subject_en, entry['appearance_en'], validators.fresh_gaps(entry))
    out_rel = out or f'books/{slug}/characters/{key}.png'
    target = root / out_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    was = target.read_bytes() if target.is_file() else None

    def validate():
        if not target.is_file():
            return [f'файла {out_rel} нет — изображение не сохранено']
        raw = target.read_bytes()
        if raw == was:
            return [f'файл {out_rel} не изменился — прежний лист остался на месте']
        if not raw.startswith(b'\x89PNG'):
            return [f'файл {out_rel} не PNG']
        if len(raw) < 100_000:
            return [f'файл {out_rel} весит {len(raw) // 1024} КБ — для листа 1536×1024 это '
                    f'слишком мало, похоже на заглушку']
        return []

    # Оператор здесь не выбирается: лист рисует `image_gen`, а он есть только у Codex.
    report = agent.run(None, {}, validate, [out_rel], root=root, config=config, log=log,
                       watch=watch, should_stop=should_stop, operator=panel_settings.DRAWS,
                       mine=mine,
                       prompt=instruction(prompt_body, out_rel))
    report['path'] = out_rel
    report['prompt'] = prompt_body
    report['sha256'] = (hashlib.sha256(target.read_bytes()).hexdigest()
                        if report['ok'] and target.is_file() else None)
    return report


def accept(slug, key, prompt_body, sha256, root=ROOT, rel=None):
    """Записать принятый лист в библию. Бухгалтерия листа — не дело агента."""
    file, data, entry = entry_of(slug, key, root)
    entry['sheet'] = rel or f'characters/{key}.png'
    entry['sheet_sha256'] = sha256
    entry['sheet_prompt'] = prompt_body
    data['characters'][key] = entry
    file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return entry


def main(argv=None):
    ap = argparse.ArgumentParser(description='Лист персонажа: три проекции, ровный свет')
    ap.add_argument('slug')
    ap.add_argument('key')
    ap.add_argument('--out', help='путь от корня репозитория (по умолчанию — в книгу)')
    ap.add_argument('--subject', help='кто это, одной фразой по-английски; перебивает библию')
    ap.add_argument('--prompt-only', action='store_true', help='показать промпт и выйти')
    ap.add_argument('--force', action='store_true', help='пересобрать поверх готового листа')
    args = ap.parse_args(argv)

    _, _, entry = entry_of(args.slug, args.key)
    if args.prompt_only:
        print(body(args.subject or entry.get('subject_en'), entry.get('appearance_en'),
                   validators.fresh_gaps(entry)))
        return 0
    rel = args.out or f'books/{args.slug}/characters/{args.key}.png'
    if (ROOT / rel).is_file() and not args.force:
        print(f'лист уже есть: {rel} (--force — пересобрать)')
        return 0

    report = make(args.slug, args.key, out=args.out, subject=args.subject, log=None)
    for line in report['complaints']:
        print(' !', line)
    if not report['ok']:
        return 1
    if not args.out:
        accept(args.slug, args.key, report['prompt'], report['sha256'])
        print(f'лист готов и записан в библию: {rel}')
    else:
        print(f'лист готов: {rel} (в библию не записан — путь задан через --out)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
