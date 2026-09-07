"""Печатает абзацы книги из кеша с индексами — чтобы читать только нужное.

Агент не читает книгу целиком: он смотрит окрестности кандидата и берёт отсюда индексы
для локатора карточки. Текст живёт в игнорируемом cache/ и в репозиторий не попадает.

    python3 scripts/show_paragraphs.py <slug> --chapter 2
    python3 scripts/show_paragraphs.py <slug> --range 119 140
    python3 scripts/show_paragraphs.py <slug> --grep "eyes|hair|face" --chapters 1-3
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(slug, root=ROOT):
    cache = root / 'cache' / slug / 'paragraphs.jsonl'
    if not cache.is_file():
        raise SystemExit(f'нет кеша: {cache} — сначала ingest_book.py')
    return [json.loads(line) for line in cache.read_text(encoding='utf-8').splitlines()]


def chapter_range(spec):
    if '-' in spec:
        a, b = spec.split('-', 1)
        return range(int(a), int(b) + 1)
    return range(int(spec), int(spec) + 1)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Печать абзацев книги из кеша')
    ap.add_argument('slug')
    ap.add_argument('--chapter', type=int)
    ap.add_argument('--chapters', help='диапазон глав, например 1-3')
    ap.add_argument('--range', nargs=2, type=int, metavar=('A', 'B'))
    ap.add_argument('--grep', help='регулярное выражение; печатаются только совпавшие абзацы')
    ap.add_argument('--width', type=int, default=0, help='обрезать абзац до N знаков')
    args = ap.parse_args(argv)

    paragraphs = load(args.slug)
    picked = paragraphs
    if args.range:
        a, b = args.range
        picked = [p for p in picked if a <= p['i'] < b]
    elif args.chapters:
        wanted = set(chapter_range(args.chapters))
        picked = [p for p in picked if p['chapter'] in wanted]
    elif args.chapter:
        picked = [p for p in picked if p['chapter'] == args.chapter]

    pattern = re.compile(args.grep, re.I) if args.grep else None
    shown = 0
    for p in picked:
        if pattern and not pattern.search(p['text']):
            continue
        text = p['text'][:args.width] if args.width else p['text']
        print(f"{p['i']:>5} гл{p['chapter']:>2} | {text}")
        shown += 1
    print(f'\n— показано {shown} из {len(picked)}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
