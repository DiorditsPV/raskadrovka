"""Локальный сервер панели: JSON из файлов репозитория, действия — через очередь заданий.

Панель ничего не хранит у себя. Состояние — файлы репозитория по действующим контрактам;
сервер их читает, пишет и запускает те же скрипты, что человек в терминале. Любой шаг можно
сделать руками, и панель это увидит.

    python3 panel/server.py --port 8770

Только стандартная библиотека.
"""
import argparse
import json
import mimetypes
import re
import subprocess
import sys
import threading
import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'scripts'))

import agent                                                # noqa: E402
import jobs as jobs_module                                  # noqa: E402
import settings as panel_settings                           # noqa: E402
import validators                                           # noqa: E402

# Откуда разрешено отдавать файлы. Всё остальное — включая books/*/source/ с текстом книги —
# наружу не выходит, даже на локальном сервере: право на текст у нас на чтение, не на раздачу.
SERVED = ('output', 'styles/refs', 'compositions/refs')
SERVED_GLOBS = ('books/*/characters/*', 'books/*/*/input/*', 'books/*/*/prompt/*')


class Panel:
    """Состояние сервера: корень репозитория, очередь, настройки."""

    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.settings = panel_settings.load(self.root)
        self.queue = jobs_module.Queue(root=self.root, handlers=self.handlers())
        self.queue.recover()
        self.queue.start()

    # — задания —

    def handlers(self):
        return {'bible-entry': self.job_bible_entry}

    SHEET_FIELDS = ('sheet', 'sheet_sha256', 'sheet_prompt')

    def job_bible_entry(self, job, tools):
        slug, key = job['args']['slug'], job['args']['key']
        bible_rel = f'books/{slug}/bible.json'
        bible_file = self.root / bible_rel
        # Что было до агента: принятый лист — бухгалтерия панели, и агент, переписывая
        # запись целиком, роняет эти поля. Судить — ему, вести учёт — нам.
        was = (self.bible(slug).get('characters') or {}).get(key) or {}
        keep = {f: was[f] for f in self.SHEET_FIELDS if f in was}
        name, hints = self.hero_hints(slug, key, was.get('name'))

        def validate():
            data = json.loads(bible_file.read_text(encoding='utf-8'))
            entry = data.get('characters', {}).get(key)
            if entry is None:
                return [f'{key}: записи нет в {bible_rel} — файл не изменён']
            return validators.check_bible_entry(key, entry, slug, self.root)

        fields = {'key': key, 'slug': slug, 'name': name,
                  'title': self.book(slug).get('title') or slug, 'hints': hints}
        report = agent.run('bible-entry', fields, validate, [bible_rel], root=self.root,
                           config=self.settings, log=tools.log, watch=tools.watch,
                           should_stop=tools.stopped)
        if keep:
            # Не только при удаче: две неудачные попытки тоже оставляют запись переписанной,
            # и принятый лист потерялся бы вместе с ней.
            self.keep_sheet(bible_file, key, keep, tools)
        return report

    def index_of(self, slug):
        file = self.root / 'cache' / slug / 'index.json'
        return json.loads(file.read_text(encoding='utf-8')) if file.is_file() else {}

    def hero_hints(self, slug, key, russian=None):
        """Имя, которым книга зовёт героя, и абзацы, где индекс видел его внешность.

        Агенту нужно имя из книги, а не из библии: `--grep "Дэрроу"` по английскому тексту
        не найдёт ничего. Панель выводит его сама и браузеру не доверяет — из отметок
        человека в `panel.json`, иначе по ключу, иначе честно говорит, что не нашла.
        """
        characters = (self.index_of(slug).get('characters') or {})
        marked = (self.panel_state(slug).get('heroes') or {})
        candidates = [name for name, mark in marked.items()
                      if isinstance(mark, dict) and mark.get('key') == key]
        candidates += [key.replace('_', ' ').title(), key.split('_')[-1].title()]
        for name in candidates:
            spots = (characters.get(name) or {}).get('appearance') or []
            if name in characters:
                hints = ', '.join(f'гл{s["chapter"]} [{s["i"]}, {s["i"] + 1})'
                                  for s in spots[:12]) or 'индекс их не нашёл'
                return name, hints
        # Индекс знает не всех: короткие имена он отсеивает, а рассказчика от первого лица
        # почти не видит. Тогда имя ищет сам агент, и сказать об этом надо прямо.
        return (russian or key), ('индекс этого героя не нашёл — имя, которым его зовёт '
                                  'книга, найди сам поиском по тексту')

    def keep_sheet(self, bible_file, key, keep, tools):
        """Вернуть в запись поля принятого листа, если агент их не сохранил."""
        data = json.loads(bible_file.read_text(encoding='utf-8'))
        entry = data['characters'][key]
        lost = [f for f in self.SHEET_FIELDS if f in keep and f not in entry]
        if not lost:
            return
        entry.update(keep)
        data['characters'][key] = entry
        bible_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n',
                              encoding='utf-8')
        tools.say(f'панель вернула поля принятого листа: {", ".join(lost)}')

    # — чтение репозитория —

    def book(self, slug):
        file = self.root / 'books' / slug / 'book.json'
        return json.loads(file.read_text(encoding='utf-8')) if file.is_file() else {}

    def bible(self, slug):
        file = self.root / 'books' / slug / 'bible.json'
        return json.loads(file.read_text(encoding='utf-8')) if file.is_file() else {}

    def panel_state(self, slug):
        file = self.root / 'cache' / 'panel' / slug / 'panel.json'
        return json.loads(file.read_text(encoding='utf-8')) if file.is_file() else {}

    def batches(self, slug):
        folder = self.root / 'books' / slug
        if not folder.is_dir():
            return []
        out = []
        for batch in sorted(p for p in folder.iterdir()
                            if p.is_dir() and (p / 'metadata').is_dir()):
            manifest = batch / 'metadata' / 'request.json'
            data = json.loads(manifest.read_text(encoding='utf-8')) if manifest.is_file() else {}
            plan = batch / 'metadata' / 'plan.json'
            out.append({'name': batch.name,
                        'style': data.get('style'),
                        'scenes': len(data.get('scenes') or []),
                        'cards': len(list((batch / 'scenes').glob('*.json'))),
                        'planned': plan.is_file()})
        return out

    def batch(self, slug, name):
        """Партия целиком: замысел из карточек, факт из манифеста и кадры на диске.

        Карточки и манифест — разные вещи: карточка есть всегда, запись в манифесте
        появляется только после кадра. Поэтому список ведут карточки, а манифест их
        дополняет, а не наоборот.
        """
        folder = self.root / 'books' / slug / name
        if not folder.is_dir():
            return None
        manifest_file = folder / 'metadata' / 'request.json'
        manifest = (json.loads(manifest_file.read_text(encoding='utf-8'))
                    if manifest_file.is_file() else {})
        by_card = {}
        for entry in manifest.get('scenes') or []:
            by_card.setdefault(Path(entry['card']).stem, []).append(entry)

        scenes = []
        for card_file in sorted((folder / 'scenes').glob('*.json')):
            card = json.loads(card_file.read_text(encoding='utf-8'))
            frames = []
            for entry in by_card.get(card_file.stem, []):
                output = Path(entry['output']).name
                frames.append({'id': entry['id'], 'style': entry.get('style'),
                               'composition': entry.get('composition'),
                               'style_refs': entry.get('style_refs') or [],
                               'caption': entry.get('caption'),
                               'image': f'output/{output}'
                                        if (self.root / 'output' / output).is_file() else None,
                               'prompt': entry.get('prompt')})
            scenes.append({
                'id': card.get('id') or card_file.stem,
                'title': card.get('title') or card_file.stem,
                'order': card.get('order'),
                'caption': card.get('caption'),
                'brief': card.get('brief'),
                'locator': card.get('locator'),
                'excerpt': (card.get('excerpt') or {}).get('text'),
                'invariants': card.get('invariants') or [],
                'composition': card.get('composition'),
                'frames': frames,
            })
        scenes.sort(key=lambda s: (s['order'] or 0, s['id']))
        return {'name': name, 'request': manifest.get('request'),
                'style': manifest.get('style'), 'scenes': scenes}

    def books(self):
        folder = self.root / 'books'
        out = []
        for path in sorted(p for p in folder.iterdir() if p.is_dir()) if folder.is_dir() else []:
            if not (path / 'book.json').is_file():
                continue
            book, bible = self.book(path.name), self.bible(path.name)
            characters = bible.get('characters') or {}
            out.append({
                'slug': path.name,
                'title': book.get('title') or path.name,
                'author': book.get('author'),
                'rights': book.get('rights') or book.get('licence') or book.get('license'),
                'parsed': (self.root / 'cache' / path.name / 'paragraphs.jsonl').is_file(),
                'indexed': (self.root / 'cache' / path.name / 'index.json').is_file(),
                'characters': len(characters),
                'sheets': sum(1 for c in characters.values() if c.get('sheet')),
                'batches': len(self.batches(path.name)),
            })
        return out

    def styles(self):
        folder = self.root / 'styles' / 'directions'
        out = []
        for file in sorted(folder.glob('*.json')) if folder.is_dir() else []:
            data = json.loads(file.read_text(encoding='utf-8'))
            refs = data.get('refs') or {}
            out.append({'key': file.stem, 'name': data.get('name') or file.stem,
                        'style_notes_en': data.get('style_notes_en', ''),
                        'palette_en': data.get('palette_en', ''),
                        'fits': data.get('fits') or [],
                        # Путь берётся из самого направления: у эталонов разные расширения,
                        # и угаданный `.png` даёт битую картинку вместо файла, который есть.
                        'refs': [{'id': k,
                                  'file': 'styles/' + (v.get('file')
                                                       or f'refs/{file.stem}/{k}.png'),
                                  'licence': v.get('licence') or v.get('license'),
                                  'why': v.get('why') or v.get('note', '')}
                                 for k, v in sorted(refs.items())]})
        return out

    def git(self):
        done = subprocess.run(['git', 'status', '--porcelain'], cwd=str(self.root),
                              capture_output=True, text=True)
        return {'lines': [l for l in done.stdout.splitlines() if l.strip()]}


# — маршруты —

ROUTES = []


def route(method, pattern):
    def keep(fn):
        ROUTES.append((method, re.compile(f'^{pattern}$'), fn))
        return fn
    return keep


@route('GET', r'/api/books')
def api_books(panel, match, query, body):
    return {'books': panel.books()}


@route('GET', r'/api/books/([^/]+)')
def api_book(panel, match, query, body):
    slug = match.group(1)
    book = panel.book(slug)
    if not book:
        return 404, {'error': f'книги «{slug}» нет'}
    bible = panel.bible(slug)
    characters = bible.get('characters') or {}
    # Книга читается один раз на запрос, а не на героя: страница опрашивается, а в книге
    # тысячи абзацев.
    book_text = validators.paragraphs(slug, panel.root)
    return {'book': book, 'panel': panel.panel_state(slug), 'batches': panel.batches(slug),
            'characters': [{'key': k,
                            'name': c.get('name') or k,
                            'understanding': c.get('understanding'),
                            'audit': c.get('audit'),
                            'sheet': c.get('sheet'),
                            'sheet_file': (f'books/{slug}/' + c['sheet']) if c.get('sheet') else None,
                            'complaints': validators.check_bible_entry(
                                k, c, slug, panel.root, book_text)}
                           for k, c in sorted(characters.items())]}


@route('POST', r'/api/books/([^/]+)/bible/([^/]+)')
def api_bible_entry(panel, match, query, body):
    slug, key = match.group(1), match.group(2)
    if not panel.book(slug):
        return 404, {'error': f'книги «{slug}» нет'}
    args = {'slug': slug, 'key': key}
    already = panel.queue.open_job('bible-entry', args)
    if already:
        return 409, {'error': f'запись «{key}» уже собирается', 'job': already['id']}
    return {'job': panel.queue.add('bible-entry', args, label=key)['id']}


@route('GET', r'/api/books/([^/]+)/batches/([^/]+)')
def api_batch(panel, match, query, body):
    batch = panel.batch(match.group(1), match.group(2))
    return batch if batch else (404, {'error': 'партии нет'})


@route('GET', r'/api/styles')
def api_styles(panel, match, query, body):
    return {'styles': panel.styles()}


@route('GET', r'/api/jobs')
def api_jobs(panel, match, query, body):
    limit = int(query.get('limit', ['50'])[0])
    return {'jobs': panel.queue.all(limit=limit)}


@route('GET', r'/api/jobs/([^/]+)')
def api_job(panel, match, query, body):
    job = panel.queue.get(match.group(1))
    return job if job else (404, {'error': 'задания нет'})


@route('GET', r'/api/jobs/([^/]+)/log')
def api_job_log(panel, match, query, body):
    lines = int(query.get('tail', ['200'])[0])
    return {'log': panel.queue.tail(match.group(1), lines)}


@route('POST', r'/api/jobs/([^/]+)/cancel')
def api_job_cancel(panel, match, query, body):
    job = panel.queue.cancel(match.group(1))
    return job if job else (404, {'error': 'задания нет'})


@route('GET', r'/api/git')
def api_git(panel, match, query, body):
    return panel.git()


@route('GET', r'/api/settings')
def api_settings(panel, match, query, body):
    return panel.settings


def served(root, rel):
    """Путь разрешён к раздаче? Проверка после resolve(), иначе `..` уводит за корень."""
    target = (root / rel).resolve()
    try:
        inside = target.relative_to(root.resolve())
    except ValueError:
        return None
    if not target.is_file():
        return None
    text = str(inside)
    if any(text == folder or text.startswith(folder + '/') for folder in SERVED):
        return target
    if any(inside.match(pattern) for pattern in SERVED_GLOBS):
        return target
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = 'raskadrovka-panel'
    panel = None

    def log_message(self, fmt, *args):          # свой лог, без шума в консоли
        if not str(args[0]).startswith(('GET /api/jobs', 'GET /api/git')):
            sys.stderr.write(f'  {self.address_string()} {fmt % args}\n')

    def do_GET(self):
        self._serve('GET')

    def do_POST(self):
        self._serve('POST')

    def do_PUT(self):
        self._serve('PUT')

    def _body(self):
        length = int(self.headers.get('Content-Length') or 0)
        if not length:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return None

    def _serve(self, method):
        parsed = urlparse(self.path)
        path, query = unquote(parsed.path), parse_qs(parsed.query)

        if method == 'GET' and path in ('/', '/index.html'):
            return self._file(HERE / 'index.html')
        if method == 'GET' and path == '/mockup.html':
            return self._file(HERE / 'mockup.html')
        if method == 'GET' and path.startswith('/file/'):
            target = served(self.panel.root, path[len('/file/'):])
            return self._file(target) if target else self._json(404, {'error': 'нельзя'})

        for verb, pattern, fn in ROUTES:
            match = pattern.match(path)
            if match and verb == method:
                try:
                    result = fn(self.panel, match, query, self._body())
                except Exception as error:                  # ошибка обработчика — не падение сервера
                    return self._json(500, {'error': f'{type(error).__name__}: {error}'})
                status, payload = result if isinstance(result, tuple) else (200, result)
                return self._json(status, payload)
        self._json(404, {'error': f'нет маршрута {method} {path}'})

    def _json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(raw)

    def _file(self, path):
        if path is None or not Path(path).is_file():
            return self._json(404, {'error': 'нет файла'})
        raw = Path(path).read_bytes()
        kind = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
        self.send_response(200)
        self.send_header('Content-Type', kind + ('; charset=utf-8' if kind.startswith('text/')
                                                 or kind.endswith('json') else ''))
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(raw)


class Server(ThreadingHTTPServer):
    # Иначе после Ctrl+C порт минуту держится в TIME_WAIT, а панель перезапускают часто.
    allow_reuse_address = True
    daemon_threads = True


def serve(root=ROOT, port=8770, host='127.0.0.1', open_browser=False):
    panel = Panel(root)
    handler = partial(Handler)
    Handler.panel = panel
    try:
        httpd = Server((host, port), handler)
    except OSError as error:
        panel.queue.stop()
        raise SystemExit(f'порт {port} занят ({error}); задайте другой: --port {port + 1}')
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(f'http://{host}:{httpd.server_port}/')).start()
    return panel, httpd


def main(argv=None):
    ap = argparse.ArgumentParser(description='Панель управления «Раскадровки»')
    ap.add_argument('--port', type=int, default=8770)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--open', action='store_true', help='открыть браузер')
    args = ap.parse_args(argv)

    panel, httpd = serve(ROOT, args.port, args.host, args.open)
    print(f'Панель: http://{args.host}:{httpd.server_port}/   (корень {panel.root})')
    print('Ctrl+C — остановить')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nостановка…')
    finally:
        panel.queue.stop()
        httpd.server_close()


if __name__ == '__main__':
    main()
