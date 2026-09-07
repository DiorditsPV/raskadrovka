"""Собирает статическую галерею из манифестов партий и проверяет их. Только стандартная библиотека.

Обходит books/<книга>/<партия>/metadata/request.json, сверяет SHA-256 карточек, промптов,
входов и результатов, проверяет локальные ссылки и пишет index.html в корень.
Унаследовано от scripts/build_gallery.py проекта «Окрестности»; группы и заголовки
берутся из books/<книга>/book.json, а не из констант в коде.
"""
import hashlib
import html
import json
import struct
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
BOOKS = ROOT / 'books'
OUTPUT = ROOT / 'output'
ESC = html.escape
SCHEMA_VERSION = 2


def verify_file(base, filename, expected, allowed=None):
    path = (base / filename).resolve()
    assert path.is_relative_to((allowed or base).resolve()), filename
    assert path.is_file(), path
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, path
    return path


def rel(path):
    return path.relative_to(ROOT).as_posix()


def load_book(slug):
    file = BOOKS / slug / 'book.json'
    assert file.is_file(), file
    book = json.loads(file.read_text())
    assert book['slug'] == slug, file
    return book


def card(base, scene):
    output = verify_file(base, scene['output'], scene['output_sha256'], OUTPUT)
    assert output.parent == OUTPUT, output
    prompt = verify_file(base, scene['prompt'], scene['prompt_sha256'])
    scene_card = verify_file(base, scene['card'], scene['card_sha256'])
    for source in scene['inputs']:
        if source.get('stored', True):
            verify_file(base, source['path'], source['sha256'])
    header = output.read_bytes()[:24]
    assert header[:8] == b'\x89PNG\r\n\x1a\n', output
    width, height = struct.unpack('>II', header[16:24])
    image = rel(output)
    title = ESC(scene['title'])
    caption = scene.get('caption', '')
    quote = f'<p class="quote">{ESC(caption)}</p>' if caption else ''
    return (
        f'<article><a class="scene" href="{ESC(image)}"><img src="{ESC(image)}" width="{width}" height="{height}" '
        f'loading="lazy" alt="{title}"></a><div class="caption"><h3>{title}</h3>{quote}'
        f'<nav aria-label="Материалы: {title}"><a href="{ESC(image)}" download>Скачать PNG</a>'
        f'<a href="{ESC(rel(scene_card))}">Карточка сцены</a><a href="{ESC(rel(prompt))}">Промпт</a>'
        f'<a href="{ESC(rel(base / "README.md"))}">Вся партия</a>'
        f'<a href="{ESC(rel(base / "metadata/request.json"))}">Метаданные</a></nav></div></article>'
    )


STYLE = (
    ':root{color-scheme:dark;background:#181a19;color:#eeeae1;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}'
    '*{box-sizing:border-box}body{margin:0}header,main,footer{max-width:1600px;margin:auto;padding:32px}header{padding-top:56px}'
    'h1{font-size:clamp(30px,4vw,56px);font-weight:550;letter-spacing:-.035em;margin:0 0 14px}p{line-height:1.6;color:#b8bbb4}'
    'header p{max-width:900px}.eyebrow{letter-spacing:.13em;font-size:12px;text-transform:uppercase;color:#cabea3;margin-bottom:14px}'
    '.grid{display:grid;grid-template-columns:1fr 1fr;gap:32px 28px}.scene{display:block;background:#252826;line-height:0}'
    '.scene img{display:block;width:100%;height:auto}article{min-width:0}.caption{padding:18px 2px 24px}'
    'h2{font-size:28px;font-weight:550;margin:0 0 28px}h3{font-size:21px;font-weight:540;line-height:1.3;margin:0 0 8px}'
    '.quote{font-style:italic;margin:0 0 6px}section{margin-bottom:48px;scroll-margin-top:24px}'
    'nav{display:flex;gap:14px 22px;flex-wrap:wrap;margin:14px 0}a{color:#e1c99a;text-underline-offset:4px}a:hover{color:#fff}'
    'a:focus-visible{outline:2px solid #e1c99a;outline-offset:5px}'
    'footer{border-top:1px solid #353b35;color:#969d94;font-size:14px;line-height:1.6}'
    '@media(max-width:900px){.grid{grid-template-columns:1fr}header,main,footer{padding-left:18px;padding-right:18px}header{padding-top:34px}}'
)


def main():
    requests = sorted(BOOKS.glob('*/*/metadata/request.json'))
    groups, books = {}, {}
    for file in requests:
        base = file.parent.parent
        assert all((base / folder).is_dir() for folder in ['input', 'prompt', 'scenes', 'metadata']), base
        manifest = json.loads(file.read_text())
        assert manifest['schema_version'] == SCHEMA_VERSION, file
        assert manifest['path_base'] == 'request-directory', file
        slug = base.parent.name
        assert manifest['book'] == slug, file
        books.setdefault(slug, load_book(slug))
        for scene in manifest['scenes']:
            key = (scene.get('order', 0), scene['id'])
            groups.setdefault(slug, []).append((key, card(base, scene)))
    count = sum(len(v) for v in groups.values())
    sections = []
    for slug in sorted(groups):
        book = books[slug]
        title = f"{book['author']}. «{book['title']}»"
        cards = ''.join(c for _, c in sorted(groups[slug]))
        sections.append(f'<section id="{ESC(slug)}"><h2>{ESC(title)}</h2><div class="grid">{cards}</div></section>')
    if not sections:
        sections.append('<p>Пока ни одной сцены: первая книга появится по плану ребилда.</p>')
    menu = ''.join(f'<a href="#{ESC(slug)}">{ESC(books[slug]["title"])}</a>' for slug in sorted(groups))
    page = (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>Раскадровка — сцены из книг</title><style>{STYLE}</style></head><body><header>'
        '<div class="eyebrow">Раскадровка</div><h1>Сцены из книг</h1>'
        f'<p>{count} сцен из книг. Все изображения собраны в общей папке output; карточки сцен, промпты и метаданные — по партиям. Исправление сцены — новая партия, прежняя уходит в локальный архив.</p>'
        f'<nav aria-label="Книги">{menu}</nav></header><main>' + ''.join(sections) +
        '</main><footer><a href="README.md">О проекте и структуре</a> · <a href="RIGHTS.md">Права и публикация</a></footer></body></html>'
    )

    class Links(HTMLParser):
        def handle_starttag(self, tag, attrs):
            for key, value in attrs:
                if key in ('href', 'src') and value and not urlsplit(value).scheme and not value.startswith('#'):
                    assert (ROOT / unquote(urlsplit(value).path)).is_file(), value

    Links().feed(page)
    (ROOT / 'index.html').write_text(page)
    print(f'Галерея собрана: партий {len(requests)}, сцен {count}; хеши и локальные ссылки сходятся.')


if __name__ == '__main__':
    main()
