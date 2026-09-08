"""Проверка прав: текст книги не в репозитории, цитирование в пределах, референсы свободны.

Это единственная машинерия проекта, которая существует ради запрета, а не ради картинки.
Она отвечает на три вопроса: не утекла ли книга в git, не превратился ли набор отрывков в
переиздание и можно ли публиковать то, что лежит в input/.

    python3 scripts/check_rights.py            # весь репозиторий, 1 при нарушении

Пределы и полный список нарушений — в RIGHTS.md; здесь они только исполняются.
Только стандартная библиотека.
"""
import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BOOK_SUFFIXES = {'.fb2', '.epub', '.txt', '.mobi', '.pdf', '.docx', '.doc', '.rtf', '.djvu'}
FREE_LICENSES = {'CC0', 'CC BY', 'CC BY-SA', 'public-domain', 'own-work', 'generated-here'}
MAX_PARAGRAPHS = 2
MAX_CHARS = 1500
MAX_SHARE = 0.03
MAX_INPUT_TEXT = 4096


def normalize(text):
    """Схлопывает пробелы и неразрывные пробелы, убирает края. Как в ingest_book."""
    text = unicodedata.normalize('NFC', text or '')
    return re.sub(r'\s+', ' ', text.replace(' ', ' ')).strip()


def sha256_text(text):
    return hashlib.sha256(normalize(text).encode('utf-8')).hexdigest()


def paragraphs_of(excerpt):
    """Отрывок разбирается на абзацы так же, как книга при разборе: по пустой строке."""
    return [p for p in re.split(r'\n\s*\n', excerpt or '') if normalize(p)]


def check_licence(where, key, entry, out):
    """Общее для референсов партии и эталонов направления."""
    licence = entry.get('license')
    if entry.get('stored', True) and licence not in FREE_LICENSES:
        out.append(f'{where}: {key} — несвободная лицензия {licence!r} у файла, который лежит '
                   f'в репозитории; такому место в refs-local/ со stored: false')
    elif not entry.get('license_basis'):
        out.append(f'{where}: {key} — нет license_basis; одной строки license мало, свобода '
                   f'обосновывается и по российскому сроку, и по американскому')


def check_scene(rel, card, book, protected, out):
    """Отрывок сцены: целые абзацы локатора и, для защищённой книги, пределы цитирования."""
    excerpt = card.get('excerpt', {}).get('text', '')
    parts = paragraphs_of(excerpt)
    if not protected:
        # У свободного произведения пределов нет, а сверка с локатором существует только
        # ради них: она делает предел проверяемым. Без предела проверять нечего.
        return len(excerpt)
    if len(parts) > MAX_PARAGRAPHS:
        out.append(f'{rel}: отрывок в {len(parts)} абзаца, предел — {MAX_PARAGRAPHS}')
    if len(excerpt) > MAX_CHARS:
        out.append(f'{rel}: отрывок в {len(excerpt)} знаков, предел — {MAX_CHARS}')

    hashes = book.get('paragraph_sha256') or []
    start, end = (card.get('locator', {}).get('paragraphs') or [0, 0])[:2]
    expected = hashes[start:end]
    if [sha256_text(p) for p in parts] != expected:
        out.append(f'{rel}: отрывок не совпадает с абзацами локатора {start}..{end} по '
                   f'paragraph_sha256 — цитата из середины абзаца не проверяется и не годится')
    return len(excerpt)


def check_batch(batch, book, protected, out):
    rel = batch.relative_to(batch.parents[2]).as_posix()
    meta = batch / 'metadata'
    manifest_file, refs_file = meta / 'request.json', meta / 'refs.json'
    manifest = json.loads(manifest_file.read_text()) if manifest_file.is_file() else {}
    refs = json.loads(refs_file.read_text()) if refs_file.is_file() else {}
    by_file = {entry.get('file'): (key, entry) for key, entry in refs.items()}

    for path in sorted((batch / 'input').rglob('*')) if (batch / 'input').is_dir() else []:
        if path.is_file() and path.stat().st_size > MAX_INPUT_TEXT:
            try:
                path.read_text(encoding='utf-8')
            except (UnicodeDecodeError, ValueError):
                continue
            out.append(f'{rel}/input/{path.relative_to(batch / "input").as_posix()}: '
                       f'текстовый файл длиннее {MAX_INPUT_TEXT} знаков — так в репозиторий '
                       f'попадает книга, а не референс')

    chars = 0
    for entry in manifest.get('scenes', []):
        card_file = batch / entry['card']
        if card_file.is_file():
            chars += check_scene(f'{rel}/{entry["card"]}', json.loads(card_file.read_text()),
                                 book, protected, out)
        for source in entry.get('inputs', []):
            if source.get('role') != 'style-reference':
                continue
            if source['path'] not in by_file:
                out.append(f'{rel}/metadata/request.json: {entry["id"]}, вход '
                           f'{source["path"]} с ролью style-reference не описан в refs.json')
    for key, entry in sorted(refs.items()):
        check_licence(f'{rel}/metadata/refs.json', key, entry, out)
    return chars


def check_book(folder, out):
    book = json.loads((folder / 'book.json').read_text())
    slug = folder.name
    rel = f'books/{slug}'
    status = (book.get('rights') or {}).get('status')
    if not status:
        out.append(f'{rel}/book.json: нет rights.status')
    if status != 'protected' and not (book.get('rights') or {}).get('basis'):
        out.append(f'{rel}/book.json: нет rights.basis — свобода произведения должна быть '
                   f'обоснована, а не объявлена')

    for path in sorted(folder.rglob('*')):
        # prompt/ исключён нарочно: промпты по контракту .txt и коммитятся как часть
        # провенанса. Всё остальное .txt под книгой — подозрение на саму книгу.
        parts = path.relative_to(folder).parts
        if path.is_file() and path.suffix.lower() in BOOK_SUFFIXES \
                and 'source' not in parts and 'prompt' not in parts:
            out.append(f'{rel}/{path.relative_to(folder).as_posix()}: файл книги в '
                       f'репозитории; ему место в игнорируемой source/')

    chars = 0
    for meta in sorted(folder.glob('*/metadata/request.json')):
        chars += check_batch(meta.parent.parent, book, status == 'protected', out)

    total = (book.get('source') or {}).get('chars') or 0
    if status == 'protected' and total and chars / total > MAX_SHARE:
        out.append(f'{rel}: отрывки занимают {chars / total:.1%} книги при пределе '
                   f'{MAX_SHARE:.0%} — набор сцен перестал быть цитированием')
    return out


def check_all(root=ROOT):
    root = Path(root)
    out = []
    for book_file in sorted((root / 'books').glob('*/book.json')) if (root / 'books').is_dir() else []:
        check_book(book_file.parent, out)
    directions = root / 'styles' / 'directions'
    for file in sorted(directions.glob('*.json')) if directions.is_dir() else []:
        style = json.loads(file.read_text())
        for key, entry in sorted((style.get('refs') or {}).items()):
            check_licence(f'styles/directions/{file.name}', key, entry, out)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description='Проверка прав: книга, цитирование, референсы')
    ap.add_argument('--root', default=str(ROOT))
    args = ap.parse_args(argv)
    violations = check_all(args.root)
    for line in violations:
        print(line)
    print(f'\nнарушений: {len(violations)}' if violations else 'Права сходятся: нарушений нет.')
    return 1 if violations else 0


if __name__ == '__main__':
    raise SystemExit(main())
