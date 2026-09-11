"""Локальный сервер панели: JSON из файлов репозитория, действия — через очередь заданий.

Панель ничего не хранит у себя. Состояние — файлы репозитория по действующим контрактам;
сервер их читает, пишет и запускает те же скрипты, что человек в терминале. Любой шаг можно
сделать руками, и панель это увидит.

    python3 panel/server.py --port 8770

Только стандартная библиотека.
"""
import argparse
import hashlib
import json
import base64
import mimetypes
import re
import subprocess
import sys
import threading
import time
import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'scripts'))

import agent                                                # noqa: E402
import generate_sheet                                       # noqa: E402
import build_gallery                                        # noqa: E402
import check_rights                                         # noqa: E402
import generate_scene                                       # noqa: E402
import index_book                                           # noqa: E402
import ingest_book                                          # noqa: E402
import register_result                                      # noqa: E402
import jobs as jobs_module                                  # noqa: E402
import settings as panel_settings                           # noqa: E402
import validators                                           # noqa: E402

# Откуда разрешено отдавать файлы. Всё остальное — включая books/*/source/ с текстом книги —
# наружу не выходит, даже на локальном сервере: право на текст у нас на чтение, не на раздачу.
SERVED = ('output', 'styles/refs', 'compositions/refs')
# `cache/panel/*/sheets/*` — только эта ветка кеша: рядом в `cache/<книга>/` лежит разобранный
# текст книги, и он наружу не выходит никогда.
SERVED_GLOBS = ('books/*/characters/*', 'books/*/characters/history/*',
                'books/*/*/input/*', 'books/*/*/prompt/*', 'cache/panel/*/sheets/*')


def _lines(path):
    """Сколько непустых строк в файле. Нужно, чтобы «разобрана» означала абзацы,
    а не существование файла: пустой кеш — это файл из одного перевода строки."""
    path = Path(path)
    if not path.is_file():
        return 0
    with path.open('rb') as fh:
        return sum(1 for line in fh if line.strip())


class Panel:
    """Состояние сервера: корень репозитория, очередь, настройки."""

    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.settings = panel_settings.load(self.root)
        # Что панель тронула сама и когда. Пока задание идёт свои минуты, человек в панели
        # работает: принимает листы, возвращает прежние. Эти файлы попадают в разницу
        # снимков `git status`, и без этого списка задание объявляло бы чужую работу
        # своей посторонней правкой — так был выброшен уже нарисованный лист.
        self._touched = []
        self._touched_lock = threading.Lock()
        self.queue = jobs_module.Queue(root=self.root, handlers=self.handlers(),
                                       locks=locks_for,
                                       width=int(self.settings.get('jobs', 1) or 1))
        self.queue.recover()
        self.queue.start()

    # — задания —

    def note(self, *rels):
        """Запомнить, что панель тронула этот путь. Путь — от корня репозитория."""
        now = time.time()
        with self._touched_lock:
            self._touched.extend((now, rel) for rel in rels if rel)
            if len(self._touched) > 500:
                self._touched = self._touched[-500:]

    def touched_since(self, since):
        with self._touched_lock:
            return {rel for when, rel in self._touched if when >= since}

    def set_settings(self, values):
        """Сохранить переопределения. `self.settings` заменяется новым словарём, а не правится
        на месте: у идущего задания конфиг уже на руках, и оператор не должен смениться
        посреди работы."""
        path = panel_settings.file(self.root)
        stored = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
        stored.update(values)
        panel_settings.save(stored, self.root)
        self.settings = panel_settings.load(self.root)
        return self.settings

    def handlers(self):
        return {'ingest': self.job_ingest, 'index': self.job_index,
                'bible-entry': self.job_bible_entry, 'bible-refine': self.job_bible_refine,
                'sheet': self.job_sheet, 'scene-card': self.job_scene_card,
                'scene': self.job_scene, 'register': self.job_register}

    # Бухгалтерия панели внутри записи героя: принятый лист и объяснённые пробелы. Судит
    # агент, а учёт ведём мы, и переписывание записи агентом эти поля ронять не должно.
    SHEET_FIELDS = ('sheet', 'sheet_sha256', 'sheet_prompt')
    GAP_FIELDS = ('gaps', 'gaps_for', 'gaps_at')
    OURS = SHEET_FIELDS + GAP_FIELDS

    def job_bible_entry(self, job, tools):
        slug, key = job['args']['slug'], job['args']['key']
        bible_rel = f'books/{slug}/bible.json'
        bible_file = self.root / bible_rel
        # Что было до агента: принятый лист — бухгалтерия панели, и агент, переписывая
        # запись целиком, роняет эти поля. Судить — ему, вести учёт — нам.
        was = (self.bible(slug).get('characters') or {}).get(key) or {}
        keep = {f: was[f] for f in self.OURS if f in was}
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
                           should_stop=tools.stopped, mine=self.touched_since)
        if keep:
            # Не только при удаче: две неудачные попытки тоже оставляют запись переписанной,
            # и принятый лист потерялся бы вместе с ней.
            self.keep_sheet(bible_file, key, keep, tools)
        return report

    def job_bible_refine(self, job, tools):
        """Добор внешности: второй заход по просевшим клеткам, а не пересборка записи.

        У добора два законных исхода на клетку: балл поднят найденным в книге или записан
        пробел — чего книга не даёт и где искали. Пробел закрывает вопрос: панель перестаёт
        предлагать добор, а генератор листа получает указание оставить черту обычной,
        вместо того чтобы выдумать шрам.
        """
        slug, key = job['args']['slug'], job['args']['key']
        bible_rel = f'books/{slug}/bible.json'
        bible_file = self.root / bible_rel
        was = (self.bible(slug).get('characters') or {}).get(key) or {}
        cells = validators.sagging(was.get('audit'))
        if not cells:
            tools.say('все десять клеток полные — добирать нечего')
            return {'ok': True, 'attempts': 0, 'complaints': []}
        keep = {f: was[f] for f in self.SHEET_FIELDS if f in was}
        name, hints = self.hero_hints(slug, key, was.get('name'))
        spans = ', '.join(f'гл{loc.get("chapter")} {loc.get("paragraphs")}'
                          for loc in (was.get('locators') or [])[:20]) or 'их нет'
        tools.say(f'добираю клетки: {", ".join(cells)}')

        def validate():
            data = json.loads(bible_file.read_text(encoding='utf-8'))
            entry = data.get('characters', {}).get(key)
            if entry is None:
                return [f'{key}: записи нет в {bible_rel} — файл не изменён']
            return validators.check_bible_refine(key, entry, slug, self.root)

        fields = {'key': key, 'slug': slug, 'name': name, 'hints': hints, 'spans': spans,
                  'title': self.book(slug).get('title') or slug,
                  'score': was.get('understanding'), 'cells': ', '.join(cells),
                  'appearance': was.get('appearance') or 'её ещё нет'}
        report = agent.run('bible-refine', fields, validate, [bible_rel], root=self.root,
                           config=self.settings, log=tools.log, watch=tools.watch,
                           should_stop=tools.stopped, mine=self.touched_since)
        if keep:
            self.keep_sheet(bible_file, key, keep, tools)
        if report['ok']:
            self.stamp_gaps(bible_file, key, tools)
        return report

    def stamp_gaps(self, bible_file, key, tools):
        """Отметить пробелы: к какой записи они относятся и когда записаны.

        Отпечаток ставит панель, а не агент: он должен считаться от того, что в файле
        оказалось, иначе «пробелы по прежней записи» не отличить от свежих.
        """
        data = json.loads(bible_file.read_text(encoding='utf-8'))
        entry = data['characters'][key]
        if not entry.get('gaps'):
            for field in ('gaps', 'gaps_for', 'gaps_at'):
                entry.pop(field, None)
        else:
            entry['gaps_for'] = validators.record_fingerprint(entry)
            entry['gaps_at'] = jobs_module._now()
            tools.say(f'пробелов записано: {len(entry["gaps"])}')
        data['characters'][key] = entry
        bible_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n',
                              encoding='utf-8')

    # — книга: разбор и индекс —

    def job_ingest(self, job, tools):
        """Разбор книги: файл → `book.json` и кеш абзацев. Текст книги остаётся вне git."""
        args = job['args']
        source = Path(args['source'])
        if not source.is_file():
            return {'ok': False, 'complaints': [f'файла нет: {source}']}
        meta = {k: v for k, v in (args.get('meta') or {}).items() if v not in (None, '')}
        tools.say(f'разбираю {source.name} → books/{args["slug"]}/')
        try:
            book = ingest_book.ingest(source, args['slug'], meta, root=self.root,
                                      numbered_only=bool(args.get('numbered_only')))
        except ValueError as error:
            return {'ok': False, 'complaints': [str(error)]}
        tools.say(f'глав {len(book["chapters"])}, абзацев {book["source"]["paragraphs"]}, '
                  f'знаков {book["source"]["chars"]}')
        for chapter in book['chapters'][:12]:
            tools.say(f'  {chapter["index"]:>3}. {chapter["title"][:60]}')
        bible = self.root / 'books' / args['slug'] / 'bible.json'
        if not bible.is_file():
            bible.write_text(json.dumps({'characters': {}, 'places': {}},
                                        ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            tools.say('заведена пустая библия — записи героев пишутся с экрана «Персонажи»')
        if args.get('drop_source'):
            source.unlink(missing_ok=True)          # временный файл загрузки больше не нужен
        return {'ok': True, 'slug': args['slug'], 'chapters': len(book['chapters']),
                'paragraphs': book['source']['paragraphs']}

    def job_index(self, job, tools):
        """Индекс: кто в книге есть, где описан, какие абзацы просятся в кадр."""
        args = job['args']
        book = validators.paragraphs(args['slug'], self.root)
        if not book:
            # Индекс по пустому кешу строится мгновенно и «успешно», сообщая «лиц 0».
            # Это не результат, а пустая книга, и сказать надо именно это.
            return {'ok': False, 'complaints': [
                f'книга {args["slug"]} не разобрана: в кеше нет ни одного абзаца, '
                f'индексу нечего читать. Сначала разбор — «Завести и разобрать»']}
        tools.say(f'строю индекс книги {args["slug"]}, абзацев {len(book)}')
        index = index_book.build(args['slug'], root=self.root,
                                 per_chapter=int(args.get('per_chapter', 3)),
                                 window=int(args.get('window', 2)),
                                 min_mentions=int(args.get('min_mentions', 4)))
        names = index.get('characters') or {}
        places = index.get('places') or {}
        scenes = index.get('scenes') or []
        tools.say(f'лиц {len(names)}, мест {len(places)}, кандидатов в сцены {len(scenes)}')
        for name in list(names)[:12]:
            tools.say(f'  {name}')
        return {'ok': True, 'characters': len(names), 'places': len(places),
                'scenes': len(scenes)}

    def pending_dir(self, slug):
        return self.root / 'cache' / 'panel' / slug / 'sheets'

    def pending_sheet(self, slug, key):
        """Лист, ожидающий приёмки: картинка в кеше плюс промпт и хеш рядом."""
        card = self.pending_dir(slug) / f'{key}.json'
        png = self.pending_dir(slug) / f'{key}.png'
        if not (card.is_file() and png.is_file()):
            return None
        data = json.loads(card.read_text(encoding='utf-8'))
        data['file'] = f'cache/panel/{slug}/sheets/{key}.png'
        return data

    def job_sheet(self, job, tools):
        """Лист персонажа. Кладётся в кеш и ждёт человека: приёмка — не дело генератора."""
        slug, key = job['args']['slug'], job['args']['key']
        rel = f'cache/panel/{slug}/sheets/{key}.png'
        report = generate_sheet.make(slug, key, root=self.root, out=rel, config=self.settings,
                                     log=tools.log, watch=tools.watch, should_stop=tools.stopped,
                                     mine=self.touched_since)
        if report['ok']:
            card = self.pending_dir(slug) / f'{key}.json'
            card.parent.mkdir(parents=True, exist_ok=True)
            card.write_text(json.dumps({'key': key, 'prompt': report['prompt'],
                                        'sha256': report['sha256'],
                                        'made': jobs_module._now()},
                                       ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            tools.say('лист собран и ждёт приёмки на экране «Персонажи»')
        return report

    # — история листов —
    #
    # Лист героя — не файл, а решение: какой он. Решение меняют, и прежнее должно остаться
    # видимым, иначе сравнить не с чем, а вернуться некуда. Поэтому ни приёмка, ни отказ
    # картинку не стирают: она уходит в `books/<книга>/characters/history/` вместе
    # с карточкой — промпт, хеш, когда и почему ушла. Коммитить — человеку, как и всё
    # остальное в этом репозитории; панель только пишет файлы.

    def history_dir(self, slug):
        return self.root / 'books' / slug / 'characters' / 'history'

    def archive_sheet(self, slug, key, image, prompt, left, made=None):
        """Убрать картинку в историю. Возвращает путь от корня книги."""
        folder = self.history_dir(slug)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        name = f'{key}-{stamp}'
        # Два ухода в одну секунду — не выдумка: «Вернуть» убирает нынешний лист и достаёт
        # прежний одним нажатием, и без этого второй файл затёр бы первый.
        n = 2
        while (folder / f'{name}.png').exists():
            name, n = f'{key}-{stamp}-{n}', n + 1
        (folder / f'{name}.png').write_bytes(image)
        self.note(f'books/{slug}/characters/history/{name}.png',
                  f'books/{slug}/characters/history/{name}.json')
        (folder / f'{name}.json').write_text(json.dumps(
            {'key': key, 'file': f'characters/history/{name}.png', 'left': left,
             'at': jobs_module._now(), 'made': made, 'prompt': prompt,
             'sha256': hashlib.sha256(image).hexdigest()},
            ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return f'characters/history/{name}.png'

    def sheet_history(self, slug, key, prompt=None):
        """Прежние листы героя, новые сверху. `prompt` — нынешний, чтобы сказать, тем же
        он собран или запись с тех пор переписали."""
        folder = self.history_dir(slug)
        if not folder.is_dir():
            return []
        out = []
        for card in sorted(folder.glob(f'{key}-*.json'), reverse=True):
            if not card.with_suffix('.png').is_file():
                continue                     # карточка без картинки показывать нечего
            data = json.loads(card.read_text(encoding='utf-8'))
            out.append({'file': f'books/{slug}/' + data['file'],
                        'rel': data['file'], 'left': data.get('left'),
                        'at': data.get('at'), 'made': data.get('made'),
                        'sha256': data.get('sha256'),
                        'same_prompt': bool(prompt) and data.get('prompt') == prompt})
        return out

    def accept_sheet(self, slug, key):
        """Принять лист: картинка переезжает в книгу, запись о ней — в библию."""
        pending = self.pending_sheet(slug, key)
        if pending is None:
            return None
        self.put_sheet(slug, key, (self.pending_dir(slug) / f'{key}.png').read_bytes(),
                       pending['prompt'], pending['sha256'])
        self.forget_sheet(slug, key)
        return f'books/{slug}/characters/{key}.png'

    def put_sheet(self, slug, key, image, prompt, sha256):
        """Положить картинку листом героя, прежнюю убрав в историю."""
        target = self.root / 'books' / slug / 'characters' / f'{key}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        was = (self.bible(slug).get('characters') or {}).get(key) or {}
        if target.is_file():
            self.archive_sheet(slug, key, target.read_bytes(),
                               was.get('sheet_prompt'), 'replaced')
        target.write_bytes(image)
        self.note(f'books/{slug}/characters/{key}.png', f'books/{slug}/bible.json')
        generate_sheet.accept(slug, key, prompt, sha256, root=self.root)

    def reject_sheet(self, slug, key):
        """Отклонить лист: из приёмки он уходит не в небытие, а в историю."""
        pending = self.pending_sheet(slug, key)
        if pending is None:
            return None
        rel = self.archive_sheet(slug, key,
                                 (self.pending_dir(slug) / f'{key}.png').read_bytes(),
                                 pending['prompt'], 'rejected', made=pending.get('made'))
        self.forget_sheet(slug, key)
        return rel

    def restore_sheet(self, slug, key, rel):
        """Вернуть прежний лист. Нынешний уходит в историю, возвращаемый из неё — уходит:
        иначе один и тот же лист показывался бы разом и как нынешний, и как прежний."""
        folder = self.history_dir(slug).resolve()
        source = (self.root / 'books' / slug / (rel or '')).resolve()
        if source.parent != folder or not source.is_file():
            return None
        if not source.name.startswith(f'{key}-') or source.suffix != '.png':
            return None
        card = source.with_suffix('.json')
        if not card.is_file():
            return None
        data = json.loads(card.read_text(encoding='utf-8'))
        if not data.get('prompt'):
            return None                      # без промпта лист нечем повторить
        self.put_sheet(slug, key, source.read_bytes(), data['prompt'], data.get('sha256'))
        # «Вернуть» забирает картинку из истории: это след панели, а не пропажа.
        self.note(f'books/{slug}/' + rel, f'books/{slug}/' + rel.replace('.png', '.json'))
        source.unlink()
        card.unlink()
        return f'books/{slug}/characters/{key}.png'

    def forget_sheet(self, slug, key):
        for suffix in ('.png', '.json'):
            (self.pending_dir(slug) / f'{key}{suffix}').unlink(missing_ok=True)

    # — партия: карточка, кадр, регистрация —

    def job_scene_card(self, job, tools):
        """Карточка сцены: замысел кадра словами, с отрывком книги и указателем на абзацы."""
        a = job['args']
        slug, batch, card = a['slug'], a['batch'], a['card']
        card_rel = f'books/{slug}/{batch}/scenes/{card}.json'
        card_file = self.root / card_rel
        bible = self.bible(slug).get('characters') or {}
        book_text = validators.paragraphs(slug, self.root)

        def validate():
            data = json.loads(card_file.read_text(encoding='utf-8'))
            return validators.check_scene_card(card, data, slug, self.root, book_text, bible)

        templates = sorted(p.stem for p in
                           (self.root / 'compositions' / 'templates').glob('*.json'))
        heroes = ', '.join(f'{k} ({v.get("name", k)})' for k, v in sorted(bible.items()))
        fields = {'slug': slug, 'batch': batch, 'card': card,
                  'title': self.book(slug).get('title') or slug,
                  'order': a.get('order') or 1,
                  'brief': a.get('brief') or 'человек замысел не задал — выбери сам по книге',
                  'where': a.get('where') or 'человек места не назвал — найди сам по замыслу',
                  'heroes': heroes or 'библия пуста — сначала соберите записи героев',
                  'compositions': ', '.join(templates) or 'шаблонов нет'}
        return agent.run('scene-card', fields, validate, [card_rel], root=self.root,
                         config=self.settings, log=tools.log, watch=tools.watch,
                         should_stop=tools.stopped, mine=self.touched_since)

    # — партия: кадр и регистрация —

    def job_scene(self, job, tools):
        """Кадр сцены: промпт, генерация, запись в манифест."""
        a = job['args']
        tools.say(f'кадр: {a["card"]} в манере {a["style"]}'
                  + ('' if a.get('composition', True) else ', без шаблона композиции'))
        report = generate_scene.make(a['slug'], a['batch'], a['card'], a['style'],
                                     root=self.root, refs=a.get('refs') or None,
                                     use_composition=a.get('composition', True),
                                     suffix=a.get('suffix'), config=self.settings,
                                     log=tools.log, watch=tools.watch,
                                     should_stop=tools.stopped, mine=self.touched_since)
        if report['ok']:
            tools.say(f'кадр записан в манифест: {report["path"]}')
        return report

    def job_register(self, job, tools):
        """Регистрация партии: сверка промптов и хешей, права, README, галерея.

        Сверка — главное здесь: если промпт на диске не совпадает со сборкой, значит запись
        героя или карточку правили после кадра, и кадр показывает прежний замысел.
        """
        slug, batch = job['args']['slug'], job['args']['batch']
        folder = self.root / 'books' / slug / batch
        check = bool(job['args'].get('check'))
        kept, orphans, problems = register_result.register(folder, check=check)
        tools.say(f'кадров в манифесте: {len(kept)}'
                  + (', проверка без правок' if check else ', манифест переписан'))
        for line in problems:
            tools.say(f'  ! {line}')
        for path in orphans:
            tools.say(f'  ! лишний файл во входах: {path.name}')

        violations = check_rights.check_all(self.root)
        for line in violations:
            tools.say(f'  ! права: {line}')
        tools.say('права сходятся' if not violations else f'нарушений прав: {len(violations)}')

        # Галерея собирается по всему репозиторию и знает только свой корень: на чужом
        # корне (например, в тесте) её звать нельзя.
        if not check and self.root.resolve() == Path(build_gallery.__file__).resolve().parents[1]:
            build_gallery.main()
            tools.say('галерея пересобрана: styles/index.html и корневой README')

        complaints = list(problems) + [f'права: {v}' for v in violations]
        return {'ok': not complaints, 'frames': len(kept), 'complaints': complaints}

    def mark_hero(self, slug, name, key):
        file = self.root / 'cache' / 'panel' / slug / 'panel.json'
        file.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(file.read_text(encoding='utf-8')) if file.is_file() else {}
        data.setdefault('heroes', {})[name] = {'key': key}
        file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return data

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
        lost = [f for f in self.OURS if f in keep and f not in entry]
        if not lost:
            return
        entry.update(keep)
        data['characters'][key] = entry
        bible_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n',
                              encoding='utf-8')
        tools.say(f'панель вернула свои поля записи: {", ".join(lost)}')

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
                # Файл книги и её разбор — разные вещи: `cache/` вне git, и после клона
                # разобранной книги нет, а исходник на месте.
                'source': any((path / 'source').glob('*')) if (path / 'source').is_dir() else False,
                # «Разобрана» — это абзацы, а не файл: пустой кеш существует и лжёт.
                # Считаем сам кеш, а не заявленное в `book.json`: файл — правда, запись —
                # утверждение, и расходятся они именно в сломанных книгах.
                'paragraphs': _lines(self.root / 'cache' / path.name / 'paragraphs.jsonl'),
                'parsed': _lines(self.root / 'cache' / path.name / 'paragraphs.jsonl') > 0,
                'indexed': bool(self.index_of(path.name).get('characters')),
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


SLUG_OK = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
UPLOAD_LIMIT = 40 * 1024 * 1024


STAGE_STALE = 6 * 3600


def staged_dir(root):
    """Где лежит только что выбранный файл, пока человек смотрит на заполненную форму.

    Это единственное место вне `books/<slug>/source/`, где тексту книги позволено лежать,
    и живёт он там минуты: иначе файл пришлось бы слать на сервер дважды — сначала чтобы
    прочесть метаданные, потом чтобы завести книгу.
    """
    folder = Path(root) / 'cache' / 'panel' / 'staged'
    folder.mkdir(parents=True, exist_ok=True)
    old = time.time() - STAGE_STALE
    for left in folder.iterdir():
        try:
            if left.is_file() and left.stat().st_mtime < old:
                left.unlink()
        except OSError:
            pass
    return folder


def read_upload(body):
    """Файл из тела запроса: имя и байты. Возвращает (имя, байты) или (код, ошибка)."""
    name = Path((body.get('filename') or 'book.txt')).name
    if Path(name).suffix.lower() not in ('.fb2', '.epub', '.txt'):
        return None, (400, {'error': f'формат {Path(name).suffix or "без расширения"} '
                                     f'не читается: fb2, epub или txt'})
    try:
        raw = base64.b64decode(body.get('data') or '', validate=True)
    except Exception:
        return None, (400, {'error': 'файл не прочитался'})
    if not raw:
        return None, (400, {'error': 'файл пустой'})
    if len(raw) > UPLOAD_LIMIT:
        return None, (413, {'error': f'файл {len(raw) // 1024 // 1024} МБ — больше 40 МБ '
                                     f'панель не принимает'})
    return (name, raw), None


@route('POST', r'/api/books/meta')
def api_book_meta(panel, match, query, body):
    """Что книга знает о себе: название, автор, переводчик, язык, год, издание — и слаг.

    Спрашивать это у человека незачем: он переписывал бы их из того же файла. За ним
    остаются права — срок охраны из метаданных не выводится.
    """
    got, bad = read_upload(body or {})
    if bad:
        return bad
    name, raw = got
    token = hashlib.sha256(raw).hexdigest()[:16] + Path(name).suffix.lower()
    staged = staged_dir(panel.root) / token
    staged.write_bytes(raw)
    meta = ingest_book.describe(staged)
    taken = [p.name for p in (panel.root / 'books').iterdir() if p.is_dir()] \
        if (panel.root / 'books').is_dir() else []
    return {'staged': token, 'filename': name, 'size': len(raw),
            'slug': ingest_book.slug_for(meta['title'], meta['author'], taken),
            **meta}


@route('POST', r'/api/books')
def api_book_add(panel, match, query, body):
    """Завести книгу: файл кладётся в `books/<slug>/source/`, разбор — заданием.

    Файл приходит base64 в JSON: панель локальная, размеры книжные, а multipart в stdlib
    держится на устаревшем модуле. Текст книги в git не попадает — за этим следит ingest.
    """
    body = body or {}
    slug = (body.get('slug') or '').strip()
    if not SLUG_OK.match(slug):
        return 400, {'error': 'слаг — латиница, цифры и дефис: herbert-wells-voyna-mirov'}
    if (panel.root / 'books' / slug / 'book.json').is_file():
        return 409, {'error': f'книга «{slug}» уже заведена'}
    if body.get('rights') not in ('public-domain', 'protected'):
        return 400, {'error': 'права: public-domain или protected'}
    # Файл уже на сервере, если форму заполняли по нему: слать его второй раз незачем.
    token = Path((body.get('staged') or '')).name
    staged = staged_dir(panel.root) / token if token else None
    if staged is not None and staged.is_file():
        name, raw = Path((body.get('filename') or staged.name)).name, staged.read_bytes()
    else:
        got, bad = read_upload(body)
        if bad:
            return bad
        name, raw = got

    # Файл ложится сразу на своё место: `books/<slug>/source/` вне git, и это единственное
    # место, где тексту книги позволено лежать.
    source = panel.root / 'books' / slug / 'source' / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(raw)
    if staged is not None and staged.is_file():
        staged.unlink(missing_ok=True)      # книга заведена, черновику здесь делать нечего
    meta = {'title': body.get('title'), 'author': body.get('author'),
            'translator': body.get('translator'), 'edition': body.get('edition'),
            'language': body.get('language') or 'ru',
            'year_published': body.get('year'),
            'rights': {'status': body['rights'], 'basis': body.get('basis') or '',
                       'checked': datetime.now().strftime('%Y-%m-%d')}}
    args = {'slug': slug, 'source': str(source), 'meta': meta,
            'numbered_only': bool(body.get('numbered_only'))}
    return {'job': panel.queue.add('ingest', args, label=slug)['id'], 'slug': slug}


@route('POST', r'/api/books/([^/]+)/parse')
def api_book_parse(panel, match, query, body):
    """Разобрать заново по файлу, который уже лежит в книге: кеш вне git и после клона пуст."""
    slug = match.group(1)
    book = panel.book(slug)
    if not book:
        return 404, {'error': f'книги «{slug}» нет'}
    folder = panel.root / 'books' / slug / 'source'
    files = sorted(p for p in folder.glob('*') if p.is_file()) if folder.is_dir() else []
    if not files:
        return 409, {'error': f'файла книги нет: положите его в books/{slug}/source/'}
    meta = {k: book.get(k) for k in ('title', 'author', 'translator', 'edition',
                                     'language', 'year_published') if book.get(k)}
    meta['rights'] = book.get('rights') or {'status': 'protected', 'basis': ''}
    args = {'slug': slug, 'source': str(files[0]), 'meta': meta}
    already = panel.queue.open_job('ingest', args)
    if already:
        return 409, {'error': 'книга уже разбирается', 'job': already['id']}
    return {'job': panel.queue.add('ingest', args, label=slug)['id']}


@route('POST', r'/api/books/([^/]+)/index')
def api_index(panel, match, query, body):
    slug = match.group(1)
    if not panel.book(slug):
        return 404, {'error': f'книги «{slug}» нет'}
    if not (panel.root / 'cache' / slug / 'paragraphs.jsonl').is_file():
        return 409, {'error': 'книга ещё не разобрана — сначала «Разобрать»'}
    args = {'slug': slug}
    for field in ('per_chapter', 'window', 'min_mentions'):
        if (body or {}).get(field):
            args[field] = int(body[field])
    already = panel.queue.open_job('index', args)
    if already:
        return 409, {'error': 'индекс уже строится', 'job': already['id']}
    return {'job': panel.queue.add('index', args, label=slug)['id']}


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
            'found': found_characters(panel, slug, characters),
            'characters': [character_view(panel, slug, k, c, book_text)
                           for k, c in sorted(characters.items())]}


def locks_for(kind, args):
    """Что задание держит, пока идёт: (общее, исключительное).

    Исключительный замок — на то, что задание правит; общий — на то, чем пользуется, но
    не меняет. Спорят они за файлы, а не за процессор: почти всё время задание ждёт сеть.

    Записи героев одной книги правят один `bible.json` и потому идут по одной; записи
    разных книг — одновременно. Листы независимы: каждый пишет свою картинку в кеш,
    а в библию её вносит человек кнопкой, не задание. Кадры одной партии рисуются
    одновременно, но манифест сводит панель под своим замком; регистрация партии держит
    всю партию исключительно — она переписывает манифест и галерею целиком.
    """
    slug = (args or {}).get('slug') or ''
    key = (args or {}).get('key') or ''
    batch = (args or {}).get('batch') or ''
    book = f'книга:{slug}'
    if kind in ('ingest', 'index'):
        return (), (book,)                      # разбор и индекс правят книгу целиком
    if kind in ('bible-entry', 'bible-refine'):
        return (book,), (f'библия:{slug}',)
    if kind == 'sheet':
        return (book,), (f'лист:{slug}/{key}',)
    if kind == 'scene-card':
        return (book, f'партия:{slug}/{batch}'), (f'карточка:{slug}/{batch}/{args.get("card")}',)
    if kind == 'scene':
        return (book, f'партия:{slug}/{batch}'), (f'кадр:{slug}/{batch}/{args.get("card")}',)
    if kind == 'register':
        return (book,), (f'партия:{slug}/{batch}',)
    return (), (book or 'всё',)                 # незнакомое задание — в одиночку


# Порог листа. Восемь из десяти книга даёт немногим: даже у главных героев две-три черты
# остаются несказанными. Семь — с тем условием, что несказанное названо вслух: пробел
# в записи уходит в промпт листа отдельным разделом и велит оставить черту обычной.
# Больше четырёх одновременных прогонов Codex упираются не в панель, а в лимиты и расход.
MAX_JOBS = 4

SHEET_GATE = 7

# Закрытая запись порога не спрашивает: если каждая из десяти клеток либо полная, либо
# объяснена пробелом, книга отдала всё, что у неё есть, и ждать больше нечего. Барлоу
# так и стоит: 6.0 при семи пробелах, и выше ему не подняться никогда.
# Нижняя граница всё же нужна — иначе запись из одних пробелов (балл 0) объявила бы себя
# готовой, а рисовать было бы нечего, кроме subject_en.
CLOSED_FLOOR = 5


def found_characters(panel, slug, known):
    """Кого индекс нашёл в книге и кого из них в библии ещё нет.

    Это ответ на вопрос «а кто вообще в книге»: имена и абзацы находит индекс, а не
    человек — книгу читал он. Отмеченные людьми соответствия имя → ключ живут в
    `cache/panel/<книга>/panel.json` и здесь только читаются.
    """
    index = panel.index_of(slug).get('characters') or {}
    marks = (panel.panel_state(slug).get('heroes') or {})
    out = []
    for name, entry in list(index.items())[:60]:
        key = (marks.get(name) or {}).get('key') or index_book.key_for(name)
        out.append({'name': name, 'key': key,
                    'mentions': entry.get('mentions'),
                    'spots': len(entry.get('appearance') or []),
                    'known': key in known})
    return out


def character_view(panel, slug, key, entry, book_text):
    """Герой для экрана: запись, претензии, лист — принятый, ждущий приёмки или невозможный."""
    sheet, understanding = entry.get('sheet'), entry.get('understanding')
    gaps = validators.fresh_gaps(entry)
    # Клетка, по которой пробел уже записан, добора больше не просит: книгу по ней прочли.
    to_refine = [c for c in validators.sagging(entry.get('audit')) if c not in gaps]
    prompt = None
    if entry.get('subject_en') and entry.get('appearance_en'):
        prompt = generate_sheet.body(entry['subject_en'], entry['appearance_en'], gaps)
    # Почему кнопку нельзя нажать — говорится словом, а не серой кнопкой без объяснения.
    if not entry.get('subject_en'):
        why = ('нет subject_en — одной фразы о том, кто это. Её пишет «Собрать запись»: '
               'книгу читал агент, а не вы')
    elif not entry.get('appearance_en'):
        why = 'нет appearance_en — внешности по-английски'
    elif not isinstance(understanding, (int, float)):
        why = 'нет балла понимания — сначала «Собрать запись»'
    elif understanding < SHEET_GATE and (to_refine or understanding < CLOSED_FLOOR):
        why = (f'балл {understanding} из 10, порог для листа — {SHEET_GATE}. '
               + ('«Добрать внешность» пройдёт по просевшим клеткам второй раз'
                  if to_refine else
                  f'книга не даёт и половины: ниже {CLOSED_FLOOR} из 10 рисовать нечего — '
                  f'в листе останется одна фраза о том, кто это'))
    else:
        why = None
    return {'key': key,
            'name': entry.get('name') or key,
            'understanding': understanding,
            'audit': entry.get('audit'),
            'gaps': gaps,
            'gaps_stale': bool(entry.get('gaps') and not gaps),
            'refine': to_refine,
            # Запись закрыта: каждая клетка либо полная, либо объяснена. Пустой `refine`
            # сам по себе этого не значит — у записи без аудита он тоже пуст.
            'closed': bool(entry.get('audit') and not to_refine and gaps),
            # Запись целиком: человек должен видеть, из чего соберут лист, до того как
            # его соберут. Промпт — тот самый, что уйдёт генератору, а не его пересказ.
            'subject_en': entry.get('subject_en'),
            'appearance': entry.get('appearance'),
            'appearance_en': entry.get('appearance_en'),
            'locators': entry.get('locators') or [],
            'prompt': prompt,
            'sheet': sheet,
            'sheet_file': (f'books/{slug}/' + sheet) if sheet else None,
            # Запись переписали после листа — лист показывает прежнего человека. Сравнивается
            # то, что описывает человека, а не весь текст: постоянная часть промпта — манера,
            # формат, запреты — меняется сама по себе, и от такой правки «лист по прежней
            # записи» загоралось бы разом у всех, ничего при этом не означая.
            'sheet_stale': bool(sheet and prompt and entry.get('sheet_prompt')
                                and generate_sheet.about_the_person(entry['sheet_prompt'])
                                != generate_sheet.about_the_person(prompt)),
            'pending': panel.pending_sheet(slug, key),
            'history': panel.sheet_history(slug, key, prompt),
            'sheet_blocked': why,
            'complaints': [{'text': str(x), 'level': x.level}
                           for x in validators.check_bible_entry(
                               key, entry, slug, panel.root, book_text)]}


@route('POST', r'/api/books/([^/]+)/bible/([^/]+)')
def api_bible_entry(panel, match, query, body):
    slug, key = match.group(1), match.group(2)
    if not panel.book(slug):
        return 404, {'error': f'книги «{slug}» нет'}
    name = ((body or {}).get('name') or '').strip()
    if name:
        # Соответствие «имя из книги → ключ записи» — отметка человека, и живёт она рядом
        # с панелью: агенту искать по имени, каким книгу зовёт сама книга.
        panel.mark_hero(slug, name, key)
    args = {'slug': slug, 'key': key}
    already = panel.queue.open_job('bible-entry', args)
    if already:
        return 409, {'error': f'запись «{key}» уже собирается', 'job': already['id']}
    return {'job': panel.queue.add('bible-entry', args, label=key)['id']}


@route('POST', r'/api/books/([^/]+)/bible/([^/]+)/refine')
def api_bible_refine(panel, match, query, body):
    """Добрать внешность: второй заход по просевшим клеткам поверх собранной записи."""
    slug, key = match.group(1), match.group(2)
    entry = (panel.bible(slug).get('characters') or {}).get(key)
    if entry is None:
        return 404, {'error': f'записи «{key}» нет — сначала «Собрать запись»'}
    if not validators.sagging(entry.get('audit')):
        return 400, {'error': f'у «{key}» все десять клеток полные, добирать нечего'}
    args = {'slug': slug, 'key': key}
    already = panel.queue.open_job('bible-refine', args) or panel.queue.open_job('bible-entry',
                                                                                args)
    if already:
        return 409, {'error': f'запись «{key}» уже в работе', 'job': already['id']}
    return {'job': panel.queue.add('bible-refine', args, label=key)['id']}


@route('PUT', r'/api/books/([^/]+)/bible/([^/]+)/subject')
def api_subject(panel, match, query, body):
    """Одна фраза о том, кто это. Правится руками — остальную запись пишет агент."""
    slug, key = match.group(1), match.group(2)
    file = panel.root / 'books' / slug / 'bible.json'
    if not file.is_file():
        return 404, {'error': f'книги «{slug}» нет'}
    text = ((body or {}).get('subject_en') or '').strip().rstrip('.')
    if not text:
        return 400, {'error': 'пустая фраза'}
    if validators.CYRILLIC.search(text):
        return 400, {'error': 'фраза идёт в промпт листа — её пишут по-английски'}
    data = json.loads(file.read_text(encoding='utf-8'))
    entry = (data.get('characters') or {}).get(key)
    if entry is None:
        return 404, {'error': f'в библии нет героя «{key}»'}
    entry['subject_en'] = text
    file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'subject_en': text}


@route('POST', r'/api/books/([^/]+)/sheets/([^/]+)')
def api_sheet(panel, match, query, body):
    """Собрать лист. Кладётся в кеш и ждёт приёмки — в книгу его переносит «Принять»."""
    slug, key = match.group(1), match.group(2)
    if not panel.book(slug):
        return 404, {'error': f'книги «{slug}» нет'}
    entry = (panel.bible(slug).get('characters') or {}).get(key)
    if entry is None:
        return 404, {'error': f'в библии нет героя «{key}»'}
    view = character_view(panel, slug, key, entry, None)
    if view['sheet_blocked']:
        return 409, {'error': view['sheet_blocked']}
    args = {'slug': slug, 'key': key}
    already = panel.queue.open_job('sheet', args)
    if already:
        return 409, {'error': f'лист «{key}» уже собирается', 'job': already['id']}
    return {'job': panel.queue.add('sheet', args, label=key)['id']}


@route('POST', r'/api/books/([^/]+)/sheets/([^/]+)/accept')
def api_sheet_accept(panel, match, query, body):
    slug, key = match.group(1), match.group(2)
    rel = panel.accept_sheet(slug, key)
    if rel is None:
        return 404, {'error': 'принимать нечего: собранного листа нет'}
    return {'sheet': rel}


@route('POST', r'/api/books/([^/]+)/sheets/([^/]+)/reject')
def api_sheet_reject(panel, match, query, body):
    slug, key = match.group(1), match.group(2)
    return {'ok': True, 'archived': panel.reject_sheet(slug, key)}


@route('POST', r'/api/books/([^/]+)/sheets/([^/]+)/restore')
def api_sheet_restore(panel, match, query, body):
    """Вернуть прежний лист героя из истории."""
    slug, key = match.group(1), match.group(2)
    done = panel.restore_sheet(slug, key, (body or {}).get('file'))
    if done is None:
        return 400, {'error': 'такого прежнего листа у этого героя нет'}
    return {'ok': True, 'sheet': done}


@route('POST', r'/api/books/([^/]+)/batches')
def api_batch_add(panel, match, query, body):
    """Завести партию: папка с планом сцен. Номер — следующий свободный, чтобы порядок не спорил."""
    slug = match.group(1)
    if not panel.book(slug):
        return 404, {'error': f'книги «{slug}» нет'}
    body = body or {}
    name = (body.get('name') or '').strip()
    if not SLUG_OK.match(name):
        return 400, {'error': 'имя партии — латиница, цифры и дефис: proba-stiley'}
    folder = panel.root / 'books' / slug
    taken = [p.name for p in folder.iterdir() if p.is_dir()] if folder.is_dir() else []
    numbers = [int(n[:2]) for n in taken if n[:2].isdigit()]
    full = f'{max(numbers, default=0) + 1:02d}-{name}'
    if full in taken or any(n.endswith('-' + name) for n in taken):
        return 409, {'error': f'партия «{name}» уже есть'}
    style = (body.get('style') or '').strip() or None
    if style and not (panel.root / 'styles' / 'directions' / f'{style}.json').is_file():
        return 400, {'error': f'направления «{style}» нет'}
    short = (body.get('short') or name.split('-')[0]).strip()

    batch = folder / full
    for sub in ('scenes', 'prompt', 'input', 'metadata'):
        (batch / sub).mkdir(parents=True, exist_ok=True)
    (batch / 'metadata' / 'request.json').write_text(json.dumps({
        'schema_version': 1, 'book': slug,
        'title': (body.get('title') or full).strip(),
        'request': (body.get('request') or '').strip(),
        'style': style, 'path_base': f'{slug}--{short}', 'scenes': []},
        ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'batch': full}


@route('POST', r'/api/books/([^/]+)/batches/([^/]+)/cards')
def api_scene_card(panel, match, query, body):
    """Написать карточку сцены. Замысел и место в книге задаёт человек, текст — агент."""
    slug, batch = match.group(1), match.group(2)
    folder = panel.root / 'books' / slug / batch
    if not (folder / 'metadata' / 'request.json').is_file():
        return 404, {'error': f'партии «{batch}» нет'}
    body = body or {}
    card = (body.get('card') or '').strip()
    if not SLUG_OK.match(card.lstrip('0123456789-') or card):
        return 400, {'error': 'имя карточки — латиница, цифры и дефис: 01-vstrecha-v-depo'}
    if not (body.get('brief') or '').strip():
        return 400, {'error': 'скажите одной фразой, что в кадре: без замысла карточку '
                              'писать не из чего'}
    if (folder / 'scenes' / f'{card}.json').is_file() and not body.get('force'):
        return 409, {'error': f'карточка «{card}» уже есть'}
    order = body.get('order') or (len(list((folder / 'scenes').glob('*.json'))) + 1)
    args = {'slug': slug, 'batch': batch, 'card': card, 'order': int(order),
            'brief': body['brief'].strip(), 'where': (body.get('where') or '').strip()}
    already = panel.queue.open_job('scene-card', args)
    if already:
        return 409, {'error': f'карточка «{card}» уже пишется', 'job': already['id']}
    return {'job': panel.queue.add('scene-card', args, label=card)['id']}


@route('POST', r'/api/books/([^/]+)/batches/([^/]+)/frames')
def api_frame(panel, match, query, body):
    """Нарисовать кадр по карточке. Направление — своё у кадра, иначе общее у партии."""
    slug, batch = match.group(1), match.group(2)
    folder = panel.root / 'books' / slug / batch
    if not (folder / 'metadata' / 'request.json').is_file():
        return 404, {'error': f'партии «{batch}» нет'}
    body = body or {}
    card = (body.get('card') or '').strip()
    if not (folder / 'scenes' / f'{card}.json').is_file():
        return 404, {'error': f'нет карточки «{card}»'}
    manifest = json.loads((folder / 'metadata' / 'request.json').read_text(encoding='utf-8'))
    style = (body.get('style') or manifest.get('style') or '').strip()
    if not style:
        return 400, {'error': 'не задано направление: ни у кадра, ни у партии'}
    if not (panel.root / 'styles' / 'directions' / f'{style}.json').is_file():
        return 400, {'error': f'направления «{style}» нет'}
    args = {'slug': slug, 'batch': batch, 'card': card, 'style': style,
            'refs': body.get('refs') or None,
            'composition': body.get('composition', True) is not False,
            'suffix': (body.get('suffix') or '').strip() or None}
    already = panel.queue.open_job('scene', args)
    if already:
        return 409, {'error': 'такой кадр уже рисуется', 'job': already['id']}
    label = generate_scene.frame_id(style, card, args['composition'], args['suffix'])
    return {'job': panel.queue.add('scene', args, label=label)['id'], 'frame': label}


@route('GET', r'/api/books/([^/]+)/batches/([^/]+)/check')
def api_batch_check(panel, match, query, body):
    """Сверка партии, ничего не меняя: сколько кадров сойдётся и что мешает остальным.

    Нужна до перезаписи манифеста: `register` без `--check` выбрасывает из манифеста всё,
    что не сошлось, и переписывает README. Человек должен видеть число заранее.
    """
    slug, batch = match.group(1), match.group(2)
    folder = panel.root / 'books' / slug / batch
    manifest_file = folder / 'metadata' / 'request.json'
    if not manifest_file.is_file():
        return 404, {'error': f'партии «{batch}» нет'}
    было = len(json.loads(manifest_file.read_text(encoding='utf-8')).get('scenes') or [])
    kept, orphans, problems = register_result.register(folder, check=True)
    # `register(check=True)` уже перечисляет лишние входы в `problems` — второй раз не надо.
    return {'frames': len(kept), 'was': было, 'dropped': было - len(kept),
            'problems': list(problems), 'rights': check_rights.check_all(panel.root)}


@route('POST', r'/api/books/([^/]+)/batches/([^/]+)/register')
def api_register(panel, match, query, body):
    slug, batch = match.group(1), match.group(2)
    if not (panel.root / 'books' / slug / batch / 'metadata' / 'request.json').is_file():
        return 404, {'error': f'партии «{batch}» нет'}
    args = {'slug': slug, 'batch': batch, 'check': bool((body or {}).get('check'))}
    already = panel.queue.open_job('register', args)
    if already:
        return 409, {'error': 'партия уже проверяется', 'job': already['id']}
    return {'job': panel.queue.add('register', args, label=batch)['id']}


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
    jobs = panel.queue.all()
    names = {j['id']: j for j in jobs}
    for job in jobs[:limit]:
        if job['status'] != jobs_module.QUEUED:
            continue
        # Почему ждёт — говорится словом: «занята библия книги», а не «ждёт очереди».
        held = panel.queue.blocked_by(job)
        job['waiting_for'] = [{'lock': h['lock'],
                               'kind': (names.get(h['job']) or {}).get('kind'),
                               'label': jobs_module.subject_of(names.get(h['job']) or {})}
                              for h in held]
    return {'jobs': jobs[:limit], 'total': len(jobs), 'width': panel.queue.width}


@route('GET', r'/api/jobs/([^/]+)')
def api_job(panel, match, query, body):
    job = panel.queue.get(match.group(1))
    return job if job else (404, {'error': 'задания нет'})


@route('GET', r'/api/jobs/([^/]+)/log')
def api_job_log(panel, match, query, body):
    lines = int(query.get('tail', ['200'])[0])
    return {'log': panel.queue.tail(match.group(1), lines)}


@route('POST', r'/api/jobs/clear')
def api_jobs_clear(panel, match, query, body):
    return {'forgotten': panel.queue.forget_finished()}


@route('POST', r'/api/jobs/([^/]+)/cancel')
def api_job_cancel(panel, match, query, body):
    job = panel.queue.cancel(match.group(1))
    return job if job else (404, {'error': 'задания нет'})


@route('GET', r'/api/git')
def api_git(panel, match, query, body):
    return panel.git()


@route('GET', r'/api/settings')
def api_settings(panel, match, query, body):
    return dict(panel.settings, operators=panel_settings.choices(),
                draws=panel_settings.DRAWS, max_jobs=MAX_JOBS)


@route('POST', r'/api/settings')
def api_settings_set(panel, match, query, body):
    """Пока меняется одно — оператор. Остальное правится файлом: командная строка и таймаут
    в окне выбора не нужны, а ошибиться в них через сеть легко."""
    body = body or {}
    change = {}
    if 'operator' in body:
        try:
            change['operator'] = panel_settings.operator(
                (body.get('operator') or '').strip(), panel.settings, panel.root)['key']
        except ValueError as error:
            return 400, {'error': str(error)}
    if 'jobs' in body:
        try:
            width = int(body['jobs'])
        except (TypeError, ValueError):
            width = 0
        if not 1 <= width <= MAX_JOBS:
            return 400, {'error': f'рядом идут от 1 до {MAX_JOBS} заданий'}
        change['jobs'] = width
    if 'lang' in body:
        if body['lang'] not in ('ru', 'en'):
            return 400, {'error': 'язык: ru или en'}
        change['lang'] = body['lang']
    if not change:
        return 400, {'error': 'нечего менять: operator, jobs или lang'}
    values = panel.set_settings(change)
    if 'jobs' in change:
        # Новые полосы поднимаются сразу; лишние уходят сами, когда доработают своё.
        panel.queue.width = change['jobs']
        panel.queue.start()
    return dict(values, operators=panel_settings.choices(), draws=panel_settings.DRAWS,
                max_jobs=MAX_JOBS)


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
            # Страницу не кешируем совсем: панель правят и перезагружают, а `no-cache`
            # браузер всё равно читает из памяти и показывает вчерашнюю разметку.
            return self._file(HERE / 'index.html', store=False)
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

    def _file(self, path, store=True):
        if path is None or not Path(path).is_file():
            return self._json(404, {'error': 'нет файла'})
        # Кадры и листы весят мегабайты, а за один обход панели их запрашивают по два-три
        # раза. `no-store` заставлял качать всё заново; метка версии по времени и размеру
        # оставляет свежесть (файл на диске мог смениться) и убирает лишние мегабайты.
        stat = Path(path).stat()
        etag = f'"{int(stat.st_mtime):x}-{stat.st_size:x}"'
        if store and self.headers.get('If-None-Match') == etag:
            self.send_response(304)
            self.send_header('ETag', etag)
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            return
        raw = Path(path).read_bytes()
        kind = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
        self.send_response(200)
        self.send_header('Content-Type', kind + ('; charset=utf-8' if kind.startswith('text/')
                                                 or kind.endswith('json') else ''))
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('ETag', etag)
        self.send_header('Cache-Control', 'no-cache' if store else 'no-store')
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
