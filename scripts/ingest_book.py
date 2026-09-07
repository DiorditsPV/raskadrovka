"""Приём книги: FB2, EPUB или TXT → book.json без текста + разбор на абзацы в cache/.

В репозиторий попадает только манифест: выходные данные, права, оглавление и SHA-256
каждого нормализованного абзаца. Хеши текст не восстанавливают, но позволяют проверить
на любой копии, что отрывок в карточке сцены взят из абзацев локатора.

Сам текст живёт в cache/<книга>/paragraphs.jsonl — папка игнорируется git.
Только стандартная библиотека.
"""
import argparse
import hashlib
import json
import re
import unicodedata
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CHAPTER_RE = re.compile(r'^(Глава|ГЛАВА|Часть|Chapter|CHAPTER|Part|PART)\b|^[IVXLC]+\.?$')
MIN_CHAPTER_CHARS = 400          # короче — это титул, посвящение или колофон, не глава


def normalize(text):
    """Схлопывает пробелы и неразрывные пробелы, убирает края."""
    text = unicodedata.normalize('NFC', text or '')
    return re.sub(r'\s+', ' ', text.replace(' ', ' ')).strip()


def sha256_text(text):
    return hashlib.sha256(normalize(text).encode('utf-8')).hexdigest()


# ── FB2 ────────────────────────────────────────────────────────────────────

def parse_fb2(data):
    root = ET.fromstring(data)
    ns = {'fb': root.tag.split('}')[0].strip('{')} if '}' in root.tag else {}

    def tag(el):
        return el.tag.split('}')[-1]

    chapters = []

    def walk(section, inherited_title=None):
        title, paragraphs = inherited_title, []
        for child in section:
            name = tag(child)
            if name == 'title':
                title = normalize(' '.join(child.itertext()))
            elif name == 'p':
                p = normalize(''.join(child.itertext()))
                if p:
                    paragraphs.append(p)
            elif name == 'section':
                if paragraphs:
                    chapters.append({'title': title or '', 'paragraphs': paragraphs})
                    title, paragraphs = None, []
                walk(child, title)
                title = None
        if paragraphs:
            chapters.append({'title': title or '', 'paragraphs': paragraphs})

    for body in root.iter():
        if tag(body) == 'body' and body.get('name') != 'notes':
            for section in body:
                if tag(section) == 'section':
                    walk(section)
    return chapters


# ── EPUB ───────────────────────────────────────────────────────────────────

class Xhtml(HTMLParser):
    """Собирает заголовок и абзацы: <h1>–<h3> — заголовок, <p> — абзац."""

    BLOCK = {'p', 'h1', 'h2', 'h3', 'div', 'blockquote'}
    SKIP = {'script', 'style'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ''
        self.paragraphs = []
        self._buf = []
        self._tag = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self._flush()
            self._tag = tag
        elif tag == 'br':
            self._buf.append(' ')

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if not self._skip:
            self._buf.append(data)

    def _flush(self):
        text = normalize(''.join(self._buf))
        self._buf = []
        if not text:
            self._tag = None
            return
        if self._tag in ('h1', 'h2', 'h3') and not self.title:
            self.title = text
        else:
            self.paragraphs.append(text)
        self._tag = None

    def close(self):
        super().close()
        self._flush()


def parse_epub(data):
    import io
    z = zipfile.ZipFile(io.BytesIO(data))
    container = ET.fromstring(z.read('META-INF/container.xml'))
    opf_path = container.find('.//{*}rootfile').get('full-path')
    opf = ET.fromstring(z.read(opf_path))
    base = opf_path.rsplit('/', 1)[0] + '/' if '/' in opf_path else ''

    items = {i.get('id'): i.get('href') for i in opf.find('{*}manifest')}
    chapters = []
    for ref in opf.find('{*}spine'):
        href = items.get(ref.get('idref'))
        if not href:
            continue
        try:
            raw = z.read(base + href.split('#')[0])
        except KeyError:
            continue
        parser = Xhtml()
        parser.feed(raw.decode('utf-8', 'ignore'))
        parser.close()
        if not parser.paragraphs:
            continue
        chapters.append({'title': parser.title, 'paragraphs': parser.paragraphs})
    return chapters


# ── TXT ────────────────────────────────────────────────────────────────────

def parse_txt(text):
    chapters, title, paragraphs = [], '', []
    for block in re.split(r'\n\s*\n', text):
        block = block.strip()
        if not block:
            continue
        first = block.splitlines()[0].strip()
        if CHAPTER_RE.match(first) and len(block) < 120:
            if paragraphs:
                chapters.append({'title': title, 'paragraphs': paragraphs})
            title, paragraphs = normalize(block), []
            continue
        paragraphs.append(normalize(block))
    if paragraphs:
        chapters.append({'title': title, 'paragraphs': paragraphs})
    return chapters


# ── сборка ─────────────────────────────────────────────────────────────────

def parse(source):
    data = source.read_bytes()
    suffix = source.suffix.lower()
    if suffix == '.fb2':
        return 'fb2', parse_fb2(data)
    if suffix == '.epub':
        return 'epub', parse_epub(data)
    return 'txt', parse_txt(data.decode('utf-8', 'ignore'))


NUMBER_RE = re.compile(r'^\d{1,3}$')


def strip_running_header(chapters):
    """Убирает колонтитул: абзац, который повторяется первым в большинстве файлов."""
    firsts = [c['paragraphs'][0] for c in chapters if c['paragraphs']]
    if not firsts:
        return chapters
    common = max(set(firsts), key=firsts.count)
    if firsts.count(common) < len(firsts) * 0.6 or len(common) > 80:
        return chapters
    for c in chapters:
        if c['paragraphs'] and c['paragraphs'][0] == common:
            c['paragraphs'] = c['paragraphs'][1:]
    return chapters


def lift_numbered_titles(chapters):
    """Поднимает «12» + «Название» из тела главы в её заголовок.

    Так размечены книги, где номер и название стоят отдельными абзацами. Заодно это
    отделяет настоящие главы от титулов, оглавления и колофона: у тех номера нет.
    """
    for c in chapters:
        ps = c['paragraphs']
        if len(ps) >= 2 and NUMBER_RE.match(ps[0]) and len(ps[1]) <= 80:
            c['number'] = int(ps[0])
            c['title'] = ps[1]
            c['paragraphs'] = ps[2:]
    return chapters


def ingest(source, slug, meta, root=ROOT, min_chapter_chars=MIN_CHAPTER_CHARS,
           numbered_only=False):
    fmt, chapters = parse(Path(source))
    chapters = lift_numbered_titles(strip_running_header(chapters))
    if numbered_only:
        chapters = [c for c in chapters if 'number' in c]
    chapters = [c for c in chapters
                if sum(len(p) for p in c['paragraphs']) >= min_chapter_chars]

    book_dir = root / 'books' / slug
    cache_dir = root / 'cache' / slug
    book_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    lines, hashes, index, ranges = [], [], 0, []
    for n, chapter in enumerate(chapters, 1):
        start = index
        for paragraph in chapter['paragraphs']:
            lines.append(json.dumps({'i': index, 'chapter': n, 'text': paragraph},
                                    ensure_ascii=False))
            hashes.append(sha256_text(paragraph))
            index += 1
        ranges.append({'index': chapter.get('number', n), 'title': chapter['title'],
                       'paragraphs': [start, index]})
    (cache_dir / 'paragraphs.jsonl').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    book_file = book_dir / 'book.json'
    book = json.loads(book_file.read_text()) if book_file.is_file() else {}
    keep = ('title', 'author', 'translator', 'edition', 'year_published', 'rights', 'language')
    for key in keep:
        if key in meta and key not in book:
            book[key] = meta[key]
    book['slug'] = slug
    book['source'] = {
        'format': fmt,
        'sha256': hashlib.sha256(Path(source).read_bytes()).hexdigest(),
        'chars': sum(len(p) for c in chapters for p in c['paragraphs']),
        'paragraphs': index,
    }
    book['paragraph_sha256'] = hashes
    book['chapters'] = ranges
    ordered = {k: book[k] for k in ('slug', 'title', 'author', 'translator', 'language',
                                    'edition', 'year_published', 'rights', 'source',
                                    'paragraph_sha256', 'chapters') if k in book}
    book_file.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + '\n',
                         encoding='utf-8')
    return ordered


def main(argv=None):
    ap = argparse.ArgumentParser(description='Приём книги в book.json и кеш абзацев')
    ap.add_argument('source')
    ap.add_argument('--slug', required=True)
    ap.add_argument('--title')
    ap.add_argument('--author')
    ap.add_argument('--translator')
    ap.add_argument('--edition')
    ap.add_argument('--language', default='ru')
    ap.add_argument('--year', type=int)
    ap.add_argument('--rights', choices=['public-domain', 'protected'], required=True)
    ap.add_argument('--basis', default='')
    ap.add_argument('--numbered-only', action='store_true',
                    help='оставить только пронумерованные главы, отбросив титулы и оглавление')
    args = ap.parse_args(argv)

    meta = {'title': args.title, 'author': args.author, 'translator': args.translator,
            'edition': args.edition, 'language': args.language,
            'year_published': args.year,
            'rights': {'status': args.rights, 'basis': args.basis, 'checked': '2026-09-07'}}
    meta = {k: v for k, v in meta.items() if v is not None}
    book = ingest(Path(args.source), args.slug, meta, numbered_only=args.numbered_only)
    print(f"{book['slug']}: глав {len(book['chapters'])}, "
          f"абзацев {book['source']['paragraphs']}, знаков {book['source']['chars']}")
    for c in book['chapters'][:8]:
        n = c['paragraphs'][1] - c['paragraphs'][0]
        print(f"  {c['index']:>3}. {c['title'][:56]:<56} абзацев {n}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
