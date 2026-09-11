"""Кадр сцены: карточка, направление, шаблон композиции и листы героев — в одно изображение.

Промпт собирает `build_prompt`, и он же решает, какие картинки уйдут на вход и в каком
порядке. Порядок важен: в промпте на входы ссылаются номерами «Image 1..N», и если подать
их иначе, текст будет говорить о другой картинке. Поэтому инструкция Codex перечисляет
пути по порядку и требует подать их так же.

Промпт кладётся в `<партия>/prompt/<кадр>.txt` до генерации: он часть провенанса, и по нему
кадр пересобирается. Запись в манифесте появляется только после того, как кадр получился.

    python3 scripts/generate_scene.py <книга> <партия> <карточка> --style tush-i-plashki
    python3 scripts/generate_scene.py … --refs ref-01 ref-03 --no-composition

Только стандартная библиотека.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'panel'))
sys.path.insert(0, str(ROOT / 'scripts'))

import agent                                                # noqa: E402
import settings as panel_settings                           # noqa: E402
import build_prompt                                         # noqa: E402


def frame_id(style, card_id, use_composition=True, suffix=None):
    """Имя кадра: направление, карточка и — если кадр отличается — чем именно."""
    tag = f'{style}--{card_id}'
    if not use_composition:
        tag += '--bez-kompozitsii'
    if suffix:
        tag += f'--{suffix}'
    return tag


def instruction(text, inputs, out_rel):
    paths = '\n'.join(f'{n}. {item["path"]}' for n, item in enumerate(inputs, 1))
    head = ('Сгенерируй ОДНО изображение инструментом image_gen и сохрани его в файл\n'
            f'{out_rel} внутри текущего рабочего каталога.\n'
            'Ничего больше не делай: не создавай других файлов, не редактируй код, '
            'не коммить.\n\n')
    if inputs:
        head += ('Передай инструменту эти изображения как референсы, СТРОГО в этом порядке — '
                 'нумерация в промпте на них и ссылается:\n' + paths + '\n\n')
    return head + 'Промпт для генерации — дословно:\n\n' + text


def manifest_entry(card, tag, style, refs, composition, batch_dir, out_rel, prompt_rel):
    card_file = batch_dir / 'scenes' / f'{card["id"]}.json'
    return {'id': tag,
            'title': card.get('title') or card['id'],
            'order': card.get('order'),
            'caption': card.get('caption'),
            'style': style,
            'style_refs': list(refs or []),
            'composition': composition,
            'card': f'scenes/{card["id"]}.json',
            'card_sha256': hashlib.sha256(card_file.read_bytes()).hexdigest(),
            'prompt': prompt_rel,
            'output': f'../../../{out_rel}'}


def remember(batch_dir, entry):
    """Записать кадр в манифест партии, заменив прежнюю запись с тем же id."""
    file = batch_dir / 'metadata' / 'request.json'
    manifest = json.loads(file.read_text(encoding='utf-8'))
    scenes = [s for s in manifest.get('scenes') or [] if s.get('id') != entry['id']]
    scenes.append(entry)
    scenes.sort(key=lambda s: (s.get('order') or 0, s['id']))
    manifest['scenes'] = scenes
    file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return manifest


def make(slug, batch, card_id, style, root=ROOT, refs=None, use_composition=True, suffix=None,
         config=None, log=None, watch=None, should_stop=None, mine=None):
    """Собрать промпт, нарисовать кадр, записать его в манифест."""
    root = Path(root)
    batch_dir = root / 'books' / slug / batch
    card_file = batch_dir / 'scenes' / f'{card_id}.json'
    if not card_file.is_file():
        return {'ok': False, 'attempts': 0, 'tries': [],
                'complaints': [f'нет карточки {card_file.relative_to(root)}']}
    manifest_file = batch_dir / 'metadata' / 'request.json'
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    card = json.loads(card_file.read_text(encoding='utf-8'))

    text, inputs = build_prompt.build(batch_dir, card_id, style, root=root,
                                      use_composition=use_composition, wanted_refs=refs)
    tag = frame_id(style, card_id, use_composition, suffix)
    base = manifest.get('path_base') or f'{slug}--{batch}'
    out_rel = f'output/{base}--{tag}.png'
    prompt_rel = f'prompt/{tag}.txt'
    # Промпт пишется до снимка дерева внутри `agent.run`: иначе он попадёт в «посторонние
    # правки» собственного задания.
    prompt_file = batch_dir / prompt_rel
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(text, encoding='utf-8')

    target = root / out_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    was = target.read_bytes() if target.is_file() else None

    def validate():
        if not target.is_file():
            return [f'файла {out_rel} нет — изображение не сохранено']
        raw = target.read_bytes()
        if raw == was:
            return [f'файл {out_rel} не изменился — прежний кадр остался на месте']
        if not raw.startswith(b'\x89PNG'):
            return [f'файл {out_rel} не PNG']
        if len(raw) < 100_000:
            return [f'файл {out_rel} весит {len(raw) // 1024} КБ — для кадра это слишком мало']
        return []

    # Оператор здесь не выбирается: кадр рисует `image_gen`, а он есть только у Codex.
    report = agent.run(None, {}, validate, [out_rel], root=root, config=config, log=log,
                       watch=watch, should_stop=should_stop, operator=panel_settings.DRAWS,
                       mine=mine,
                       prompt=instruction(text, inputs, out_rel))
    report.update(frame=tag, path=out_rel, prompt=prompt_rel, inputs=len(inputs))
    if report['ok']:
        entry = manifest_entry(card, tag, style, refs,
                               card.get('composition') if use_composition else None,
                               batch_dir, out_rel, prompt_rel)
        remember(batch_dir, entry)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description='Кадр сцены по карточке и направлению')
    ap.add_argument('slug')
    ap.add_argument('batch', help='папка партии внутри книги, например 01-proba-stiley')
    ap.add_argument('card', help='имя карточки без расширения')
    ap.add_argument('--style', required=True)
    ap.add_argument('--refs', nargs='*', help='эталоны манеры, например ref-01 ref-03')
    ap.add_argument('--no-composition', action='store_true')
    ap.add_argument('--suffix', help='чем этот кадр отличается от соседнего')
    ap.add_argument('--prompt-only', action='store_true')
    args = ap.parse_args(argv)

    if args.prompt_only:
        text, inputs = build_prompt.build(ROOT / 'books' / args.slug / args.batch, args.card,
                                          args.style, root=ROOT,
                                          use_composition=not args.no_composition,
                                          wanted_refs=args.refs)
        print(text)
        print('\n— входы —')
        for n, item in enumerate(inputs, 1):
            print(f'{n}. {item["role"]:22} {item["path"]}')
        return 0

    report = make(args.slug, args.batch, args.card, args.style, refs=args.refs,
                  use_composition=not args.no_composition, suffix=args.suffix)
    for line in report['complaints']:
        print(' !', line)
    if not report['ok']:
        return 1
    print(f'кадр готов: {report["path"]} (входов {report["inputs"]})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
