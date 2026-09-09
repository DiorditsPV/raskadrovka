"""Регистрирует результаты партии в манифесте: хеши, входы и снимок input/.

Манифест — не отчёт о том, что задумывалось, а запись о том, из чего получена картинка.
Поэтому список входов здесь не переписывается из головы, а пересобирается тем же кодом,
что собирал промпт: один раз записанные вручную входы уже расходились с настоящими.

    python3 scripts/register_result.py books/<книга>/<партия>
    python3 scripts/register_result.py books/<книга>/<партия> --check

Партия обязана быть самодостаточной: всё, что подавалось генератору, лежит в её input/.
Скрипт копирует туда недостающее и убирает лишнее — файл, на который не ссылается ни одна
сцена, в git не нужен. Только стандартная библиотека.
"""
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

import build_prompt

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'output'


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot_name(path, root=ROOT):
    """Имя копии внутри input/: путь источника, схлопнутый в плоское имя.

    Плоское имя, а не подпапки: так видно происхождение файла и исключены совпадения
    между направлениями, у которых эталоны нумеруются одинаково.
    """
    rel = Path(path).resolve().relative_to(root)
    parts = list(rel.parts)
    kind = {'styles': 'style', 'compositions': 'composition', 'books': 'character'}.get(parts[0], parts[0])
    return f'{kind}--' + '--'.join(parts[-2:])


def ref_record(source, target_rel, root=ROOT):
    """Запись о стилевом эталоне для refs.json — из направления, а не из головы.

    Лицензия и её обоснование живут в styles/directions/<направление>.json; партия обязана
    нести их копию, иначе по одной папке партии нельзя ответить, можно ли это публиковать.
    """
    rel = Path(source).resolve().relative_to(root)
    if rel.parts[:2] != ('styles', 'refs'):
        return None, None
    direction, ref_id = rel.parts[2], rel.stem
    style = json.loads((root / 'styles' / 'directions' / f'{direction}.json').read_text())
    entry = dict(style.get('refs', {}).get(ref_id) or {})
    if not entry:
        return None, None
    entry['file'] = target_rel
    entry['from_style'] = direction
    entry['style_notes_en'] = style['style_notes_en']
    entry['palette_en'] = style.get('palette_en', '')
    return f'{direction}--{ref_id}', entry


def without_builder(manifest):
    """Манифест без builder_sha256 — для сверки.

    Хеш сборщика меняется от любой правки build_prompt.py, вплоть до комментария. Если
    сверять и его, то первая же правка задним числом объявит все прежние партии
    разошедшимися — ровно то, чего контракт обещает не делать. Настоящий инвариант стережёт
    сверка самого промпта: она уже отказывается регистрировать кадр, чей промпт не
    пересобирается байт-в-байт.
    """
    return {**manifest, 'scenes': [{k: v for k, v in s.items() if k != 'builder_sha256'}
                                   for s in manifest.get('scenes', [])]}


MARK_OPEN, MARK_CLOSE = '<!--raskadrovka:scenes-->', '<!--/raskadrovka:scenes-->'


def scenes_block(kept):
    """Список кадров для README партии. Между маркерами — только машинный текст."""
    lines = ['| Кадр | Направление | Шаблон |', '|---|---|---|']
    for entry in sorted(kept, key=lambda e: (e.get('order', 0), e['id'])):
        image = Path(entry['output']).name
        lines.append(f'| [{entry["title"]}](../../../output/{image}) | `{entry["style"]}` | '
                     f'`{entry.get("composition") or "—"}` |')
    return '\n'.join(lines)


def _table_norm(text):
    text = re.sub(r'-{3,}', '---', text)
    text = re.sub(r'[ \t]+\|', '|', text)
    return re.sub(r'\|[ \t]+', '|', text)


def update_readme(batch, kept, check, problems):
    """Список кадров в README партии переписывается машиной: руками он устаревает молча."""
    file = batch / 'README.md'
    if not file.is_file():
        return
    text = file.read_text()
    if MARK_OPEN not in text or MARK_CLOSE not in text:
        problems.append('README.md: нет маркеров <!--raskadrovka:scenes-->')
        return
    head, rest = text.split(MARK_OPEN, 1)
    _, tail = rest.split(MARK_CLOSE, 1)
    fresh = f'{head}{MARK_OPEN}\n{scenes_block(kept)}\n{MARK_CLOSE}{tail}'
    if check:
        # Форматтер markdown выравнивает таблицу пробелами и удлиняет разделители; сверяем
        # содержимое ячеек, а не их набивку — иначе каждая правка README чужой рукой красная.
        if _table_norm(text) != _table_norm(fresh):
            problems.append('README.md: список кадров разошёлся с манифестом')
    else:
        file.write_text(fresh)


def register(batch, check=False):
    batch = Path(batch).resolve()
    manifest_file = batch / 'metadata' / 'request.json'
    manifest = json.loads(manifest_file.read_text())
    problems, kept, wanted, refs = [], [], set(), {}

    for entry in manifest['scenes']:
        entry_id = entry['id']
        output = OUTPUT / Path(entry['output']).name
        if not output.is_file():
            problems.append(f'{entry["id"]}: нет результата {output.name} — запись убрана')
            continue

        prompt_file = batch / entry['prompt']
        text, inputs = build_prompt.build(
            batch, Path(entry['card']).stem, entry['style'],
            use_composition=bool(entry.get('composition')),
            wanted_refs=entry.get('style_refs'))
        if not prompt_file.is_file():
            problems.append(f'{entry["id"]}: нет промпта {entry["prompt"]}')
            continue
        if prompt_file.read_text() != text:
            problems.append(f'{entry["id"]}: промпт на диске не совпадает со сборкой — '
                            f'входы и промпт описывают разное, перегенерируй кадр')
            continue

        recorded = []
        for item in inputs:
            source = Path(item['path'])
            name = snapshot_name(source)
            wanted.add(name)
            target = batch / 'input' / name
            if not check and (not target.is_file() or sha256_file(target) != sha256_file(source)):
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            if not target.is_file():
                problems.append(f'{entry["id"]}: нет снимка входа input/{name}')
                continue
            recorded.append({'path': f'input/{name}', 'sha256': sha256_file(target),
                             'role': item['role'], 'stored': True})
            if item['role'] == 'style-reference':
                ref_key, ref_entry = ref_record(source, f'input/{name}')
                if ref_key is None:
                    problems.append(f'{entry_id}: эталон {source.name} не найден в направлениях')
                else:
                    ref_entry['sha256'] = sha256_file(target)
                    refs[ref_key] = ref_entry

        entry['card_sha256'] = sha256_file(batch / entry['card'])
        entry['prompt_sha256'] = sha256_file(prompt_file)
        entry['builder_sha256'] = sha256_file(build_prompt.__file__)
        entry['output_sha256'] = sha256_file(output)
        entry['inputs'] = recorded
        kept.append(entry)

    orphans = sorted(p for p in (batch / 'input').iterdir() if p.name not in wanted)
    if not check:
        for path in orphans:
            path.unlink()
    manifest['scenes'] = kept
    refs_file = batch / 'metadata' / 'refs.json'
    refs_text = json.dumps(dict(sorted(refs.items())), ensure_ascii=False, indent=2) + '\n'
    if check:
        if not refs_file.is_file() or refs_file.read_text() != refs_text:
            problems.append('metadata/refs.json разошёлся с входами партии')
    else:
        refs_file.write_text(refs_text)

    update_readme(batch, kept, check, problems)

    if check:
        current = json.loads(manifest_file.read_text())
        if without_builder(current) != without_builder(manifest):
            problems.append('манифест разошёлся с тем, что на диске')
        problems += [f'лишний файл в input/: {p.name}' for p in orphans]
    else:
        manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')

    return kept, orphans, problems


def main(argv=None):
    ap = argparse.ArgumentParser(description='Регистрация результатов партии в манифесте')
    ap.add_argument('batch')
    ap.add_argument('--check', action='store_true', help='ничего не менять, 1 при расхождении')
    args = ap.parse_args(argv)

    kept, orphans, problems = register(args.batch, args.check)
    for line in problems:
        print(line)
    verb = 'сошлось' if args.check else 'записано'
    print(f'{verb}: сцен {len(kept)}, '
          f'{"лишних входов " + str(len(orphans)) if args.check else "убрано входов " + str(len(orphans))}')
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
