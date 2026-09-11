"""Оператор как исполнитель шагов с суждением: библия, карточки сцен, стиль из книги.

Операторов два — Codex и Claude, — и выбирают их в настройках; кто исполняет, написано
в шапке каждой попытки в логе. Рисующие задания выбора не имеют: `image_gen` есть только
у Codex, и они называют его прямо.

Итог задания определяет не оператор, а валидатор. Оператор падает молча — файла просто нет,
а код возврата нулевой, — и это правило проекта, а не редкий случай. Поэтому после каждой попытки
проверяется результат на диске и то, что в дереве изменилось только ожидаемое; провал даёт
одну повторную попытку, в инструкцию дословно дописываются претензии валидатора.

Дерево во время работы почти всегда грязное, поэтому «посторонние изменения» ищутся не по
факту правок, а по разнице двух снимков `git status --porcelain` — до запуска и после.

Только стандартная библиотека.
"""
import os
import shlex
import shutil
import string
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import settings as panel_settings

ROOT = Path(__file__).resolve().parents[1]
TASKS = Path(__file__).resolve().parent / 'tasks'


def instruction(kind, fields, tasks=TASKS):
    """Инструкция из шаблона `tasks/<kind>.md`. Подстановка `$поле`, а не `{поле}`: в шаблонах
    есть фигурные скобки JSON, и формат с фигурными скобками на них спотыкается."""
    template = Path(tasks) / f'{kind}.md'
    if not template.is_file():
        raise FileNotFoundError(f'нет шаблона задания: {template}')
    return string.Template(template.read_text(encoding='utf-8')).safe_substitute(fields)


def git_status(root=ROOT):
    """Снимок дерева: множество строк `git status --porcelain`.

    `-uall` обязателен: без него git сворачивает новые файлы в имя папки — «output/»
    вместо самого кадра, — и ожидаемый путь перестаёт совпадать с показанным.
    """
    done = subprocess.run(['git', 'status', '--porcelain', '-uall'], cwd=str(root),
                          capture_output=True, text=True)
    return {line for line in done.stdout.splitlines() if line.strip()}


def _path_of(line):
    """Путь из строки porcelain: два знака статуса, пробел, путь; переименование — справа."""
    path = line[3:]
    if ' -> ' in path:
        path = path.split(' -> ', 1)[1]
    return path.strip().strip('"')


# Стол самой панели: логи заданий, промпты, листы на приёмке. Это её бухгалтерия, а не
# работа агента, и посторонней правкой она быть не может по определению.
OURS = ('cache/panel/',)


def _mine(path, expected, ours, mine=()):
    return (path in mine
            or any(path.startswith(prefix) for prefix in ours)
            or any(path.startswith(prefix) for prefix in expected))


def stray_changes(before, after, expected, ours=OURS, root=ROOT, mine=()):
    """Изменения вне ожидаемых путей — предупреждение человеку, а не задание агенту.

    Разницу двух снимков даёт не только агент: пока задание идёт свои минуты, в том же
    дереве работают человек и панель. Отличить их правку от агентской по `git status`
    нельзя, поэтому список отсюда никогда не уходит в инструкцию повтора — он только
    показывается человеку и роняет задание.

    `expected` — префиксы путей от корня репозитория.

    Смотреть только на появившиеся строки мало, и это уже стоило трёх листов персонажей.
    Удаление неотслеживаемого файла не добавляет строку в `git status`, а **убирает** её:
    был `?? books/…/characters/barlow.png` — и нет ничего. Поэтому исчезнувшие строки
    проверяются тоже, и проверяются по диску: строка пропадает и от честного коммита,
    который делает человек, пока задание идёт, — а вот файла после коммита не убывает.
    """
    out = []
    for line in sorted(after - before):
        path = _path_of(line)
        if not _mine(path, expected, ours, mine):
            out.append(f'посторонняя правка в дереве: {path} — задание меняет только '
                       f'{", ".join(expected)}')
    for line in sorted(before - after):
        path = _path_of(line)
        if _mine(path, expected, ours, mine) or (Path(root) / path).exists():
            continue
        out.append(f'задание удалило файл: {path} — его не было в работе задания, '
                   f'а теперь его нет и на диске; задание меняет только '
                   f'{", ".join(expected)}')
    return out


def operator_command(spec, prompt, root=ROOT):
    """Команда оператора: подставляются только `{root}` и `{prompt}`, прочее идёт как есть."""
    fill = {'{root}': str(root), '{prompt}': prompt}
    return [fill.get(arg, arg) for arg in spec['cmd']]


def run_operator(prompt, root=ROOT, config=None, log=None, watch=None, operator=None):
    """Один запуск оператора. stdin закрыт: с открытым stdin `codex exec` виснет, а
    `claude -p` ждёт ввода вместо того, чтобы ответить.

    `watch` получает запущенный процесс — так очередь может его убить по «снять задание».
    """
    config = config if config is not None else panel_settings.load(root)
    command = operator_command(panel_settings.operator(operator, config, root), prompt, root)
    started = time.monotonic()
    timeout = int(config.get('timeout', 1200))
    if log is not None:
        # Промпт в лог не идёт: он лежит рядом целиком, в `<лог>.prompt.txt`.
        _append(log, '$ ' + ' '.join(shlex.quote('<инструкция>' if arg is prompt else arg)
                                     for arg in command) + '\n')
    process = subprocess.Popen(command, cwd=str(root), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, bufsize=1)
    if watch is not None:
        watch(process)
    # Вывод пишется построчно, а не одним куском в конце: кадр идёт минуты, и хвост лога
    # в панели должен что-то показывать всё это время.
    killed = threading.Event()
    killer = threading.Timer(timeout, lambda: (killed.set(), process.kill()))
    killer.start()
    lines = []
    try:
        for line in process.stdout:
            lines.append(line)
            if log is not None:
                _append(log, line)
        process.wait()
    finally:
        killer.cancel()
        if watch is not None:
            watch(None)
    output = ''.join(lines)
    code = None if killed.is_set() else process.returncode
    if killed.is_set():
        output += f'\n— таймаут {timeout} с, процесс убит'
    spent = time.monotonic() - started
    if log is not None:
        _append(log, f'— код {code}, {spent:.0f} с\n')
    return code, output, spent


def _append(log, text):
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('a', encoding='utf-8') as fh:
        fh.write(text)


def _stopped(attempts, tries, log, operator=None):
    if log is not None:
        _append(log, 'задание снято человеком, следующей попытки не будет\n')
    return {'ok': False, 'attempts': attempts, 'stopped': True, 'operator': operator,
            'complaints': ['задание снято человеком'], 'tries': tries}


# Дописывается к любому заданию, шаблонному и собранному из данных. Агент проверяет свою
# работу через `git status` и видит там чужое: человек принял лист, панель записала пробелы.
# Без этого абзаца он считает чужой файл своим мусором и «наводит порядок» — так был удалён
# лист Кирэна из соседней книги, аккуратно, с резервной копией в /tmp.
HANDS_OFF = """

## Чужая работа в этом дереве

Пока ты работаешь, в этом же репозитории работают другие: человек принимает листы персонажей,
панель пишет свои файлы. В `git status` ты увидишь изменения, которых не делал, — и в других
книгах тоже.

Это не твоё дело и не твоя ошибка. Ничего не удаляй, не перемещай, не переименовывай и не
возвращай к прежнему виду — даже если файл выглядит посторонним, лишним или забытым. Не
«наводи порядок» в дереве и не делай резервных копий на стороне. Границы своей работы ты
получил выше; всё, что вне них, оставь ровно как есть.
"""

# Чужая работа, которую задание не должно трогать. Текста книги здесь нет нарочно: на него
# у нас право читать, а не копировать, и второй дороги к нему мы не заводим даже жёсткой
# ссылкой в кеше.
GUARDED = ('books',)
NEVER_LINK = ('/source/',)


def guard(root, expected, store):
    """Жёсткие ссылки на чужие файлы: страховка от удаления, которая ничего не стоит.

    Ссылка не занимает места и не копирует байты — она лишь вторая дорога к тем же данным.
    Удалить файл она не мешает, но данные после удаления остаются, и их можно вернуть.
    От правки на месте не спасает: у изменённого файла тот же inode. От удаления, замены
    и `git checkout` — спасает, а это ровно то, что уже случалось.
    """
    root, store = Path(root), Path(store)
    kept = {}
    for folder in GUARDED:
        base = root / folder
        if not base.is_dir():
            continue
        for path in base.rglob('*'):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(root).as_posix()
            if any(part in f'/{rel}' for part in NEVER_LINK):
                continue
            if any(rel.startswith(prefix) for prefix in expected):
                continue
            link = store / rel
            link.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(path, link)
            except OSError:
                continue            # другая файловая система или права — тогда без страховки
            kept[rel] = link
    return kept


def restore(root, kept, mine=()):
    """Вернуть то, что задание удалило. Возвращает список возвращённых путей.

    `mine` — то, что убрала сама панель, пока задание шло: «Вернуть прежний лист» забирает
    картинку из истории, и воскрешать её не надо.
    """
    root = Path(root)
    back = []
    for rel, link in sorted(kept.items()):
        target = root / rel
        if rel in mine or target.exists() or not Path(link).is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(link, target)
        except OSError:
            shutil.copy2(link, target)
        back.append(rel)
    return back


# Отказ цензуры генератора. Он приходит не кодом возврата, а строкой в выводе, и выглядит
# для панели как «файла нет». Повторная попытка после такого отказа вредна: агент, которому
# сказали «файла нет — исправь», второй раз рисует не то, что просили, а то, что пропустят.
# Так вместо голого старика со ржавой косой из «Between Two Fires» появилась аниме-девушка
# «MAYA TANAKA, Role: Protagonist» — картинка прошла все проверки: PNG, больше ста килобайт,
# файл изменился.
# Только машинные коды из ответа API. Человеческие обороты — «safety system», «content
# policy» — сюда не годятся: тем же языком написана оговорка в самом промпте, а Codex
# печатает промпт эхом в свой вывод. С ними проверка объявляла отказом каждое рисующее
# задание, включая удачное.
REFUSED = ('moderation_blocked', 'safety_violations=', 'image_generation_user_error')


def refusal(output):
    """Текст отказа, если генератор отказался рисовать. Иначе None."""
    if not output:
        return None
    low = output.lower()
    if not any(mark.lower() in low for mark in REFUSED):
        return None
    for line in output.splitlines():
        if '"message"' in line and 'safety' in line.lower():
            return line.strip().strip(',')[:400]
    for line in output.splitlines():
        if any(mark.lower() in line.lower() for mark in REFUSED):
            return line.strip()[:400]
    return 'генератор отказался рисовать'


def retry_note(complaints):
    return ('\n\n## Прошлая попытка не прошла проверку\n\n'
            'Претензии проверяющего, дословно:\n\n'
            + '\n'.join(f'- {c}' for c in complaints)
            + '\n\nИсправь ровно это и не переделывай остальное.\n')


def run(kind, fields, validate, expected, root=ROOT, config=None, log=None, watch=None,
        should_stop=None, prompt=None, operator=None, mine=None):
    """Задание с суждением: инструкция → Codex → проверка → при провале одна повторная попытка.

    `validate` — функция без аргументов, возвращающая список претензий (пустой = годно).
    `expected` — префиксы путей от корня репозитория, которые заданию позволено менять.
    `prompt` — готовая инструкция вместо шаблона: у рисующих заданий она складывается из
    данных (запись героя, карточка сцены, эталоны), а не лежит текстом в `tasks/`.
    `operator` — кем исполнять; пусто значит «тем, кого выбрали в настройках». Рисующие
    задания называют его прямо: картинку умеет только Codex.
    `mine` — функция «что панель тронула сама с такого-то времени». Пока задание идёт
    десять минут, человек в панели работает: принимает листы, возвращает прежние. Эти
    файлы попадают в разницу снимков, и без `mine` задание падало из-за чужой работы —
    так был выброшен уже нарисованный лист «Смерти».
    Возвращает отчёт: прошло ли, сколько попыток, кто исполнял, претензии последней попытки.
    """
    root = Path(root)
    config = config if config is not None else panel_settings.load(root)
    spec = panel_settings.operator(operator, config, root)
    attempts = max(1, int(config.get('attempts', 2)))
    base = (prompt if prompt is not None else instruction(kind, fields)) + HANDS_OFF
    complaints, tries, strays = [], [], []
    # Снимок дерева один на всё задание, а не на попытку: иначе посторонняя правка первой
    # попытки становится фоном второй и уже не видна.
    started = time.time()
    before = git_status(root)
    store = Path(tempfile.mkdtemp(prefix='guard-', dir=_guard_dir(root)))
    kept = guard(root, expected, store)
    ours = (lambda: set(mine(started))) if mine is not None else (lambda: set())
    try:
        return _attempts(kind, base, validate, expected, root, config, log, watch,
                         should_stop, spec, attempts, before, kept, complaints, tries,
                         strays, ours)
    finally:
        shutil.rmtree(store, ignore_errors=True)


STALE_GUARD = 6 * 3600


def _guard_dir(root):
    """Каталог страховки. Заодно подметаем забытые: панель убивают на ходу, и тогда
    `finally` не отрабатывает. Ссылки места не занимают, но держат данные удалённых
    файлов живыми — тихо и навсегда."""
    folder = Path(root) / 'cache' / 'panel' / 'guard'
    folder.mkdir(parents=True, exist_ok=True)
    old = time.time() - STALE_GUARD
    for left in folder.glob('guard-*'):
        try:
            if left.is_dir() and left.stat().st_mtime < old:
                shutil.rmtree(left, ignore_errors=True)
        except OSError:
            pass
    return folder


def _attempts(kind, base, validate, expected, root, config, log, watch, should_stop,
              spec, attempts, before, kept, complaints, tries, strays, ours):
    for attempt in range(1, attempts + 1):
        if should_stop is not None and should_stop():
            return _stopped(attempt - 1, tries, log, spec['key'])
        # В инструкцию идут только претензии проверяющего к самой работе. Посторонние
        # правки в неё не попадают никогда: агент не может знать, что файл не его, и
        # «исправь ровно это» превращается в удаление чужого.
        prompt = base if attempt == 1 else base + retry_note(complaints)
        if log is not None:
            _append(log, f'\n=== попытка {attempt} из {attempts}, оператор '
                         f'{spec["title"]} — {spec["sandbox"]}, '
                         f'{datetime.now():%Y-%m-%d %H:%M:%S} ===\n')
            _append(Path(log).with_suffix('.prompt.txt'),
                    f'=== попытка {attempt} ===\n{prompt}\n')
        code, output, spent = run_operator(prompt, root, config, log, watch,
                                           spec['key'])
        stop = refusal(output)
        if stop is not None:
            # Повтора не будет: рисовать отказались не по ошибке, а по правилу, и второй
            # заход даёт не тот рисунок, а любой, лишь бы файл появился.
            note = (f'генератор отказался рисовать: {stop}. Повтор не поможет — дело '
                    f'в самом описании, а не в попытке')
            if log is not None:
                _append(log, f'проверка:   ! {note}\n')
            tries.append({'attempt': attempt, 'returncode': code, 'seconds': round(spent),
                          'complaints': [note]})
            return {'ok': False, 'attempts': attempt, 'operator': spec['key'],
                    'refused': True, 'complaints': [note], 'strays': strays, 'tries': tries}
        if should_stop is not None and should_stop():
            # Убитый процесс неотличим от неудачной попытки, и без этой проверки снятие
            # задания запускало бы вторую попытку — ещё столько же минут работы Codex.
            return _stopped(attempt, tries, log, spec['key'])
        try:
            complaints = list(validate())
        except Exception as error:
            # Неразбираемый JSON — самый вероятный плохой исход, и это претензия к попытке,
            # а не крах задания: иначе повтор, существующий ровно для этого, не наступит.
            complaints = [f'результат не читается: {type(error).__name__}: {error} — '
                          f'файл должен существовать и разбираться как JSON']
        # Сначала вернуть удалённое, потом считать разницу: иначе в претензии попадёт
        # файл, который уже на месте, и человек пойдёт искать несуществующую пропажу.
        panel_did = ours()
        back = restore(root, kept, panel_did)
        if back and log is not None:
            _append(log, 'панель вернула чужие файлы, удалённые заданием: '
                         + ', '.join(back) + '\n')
        strays = stray_changes(before, git_status(root), expected, root=root, mine=panel_did)
        damage = [f'задание удалило чужой файл {rel} — панель вернула его на место'
                  for rel in back]
        complaints += damage
        tries.append({'attempt': attempt, 'returncode': code, 'seconds': round(spent),
                      'complaints': complaints + strays})
        if log is not None:
            _append(log, 'проверка: годно\n' if not complaints + strays
                    else 'проверка: ' + '\n'.join(f'  ! {c}' for c in complaints + strays)
                         + '\n')
        if not complaints:
            # Посторонняя правка работу не отменяет. Отличить правку агента от правки
            # человека, работающего в панели те же десять минут, по `git status` нельзя,
            # и уже нарисованный лист из-за такой догадки выбрасывать нельзя тем более.
            # Это предупреждение человеку; настоящий вред — удаление — ловит страховка
            # жёсткими ссылками и роняет задание отдельно, через `damage`.
            if strays and log is not None:
                _append(log, 'задание прошло; в дереве есть правки не от него — '
                             'посмотрите список выше\n')
            return {'ok': True, 'attempts': attempt, 'operator': spec['key'],
                    'complaints': [], 'strays': strays, 'tries': tries}
    return {'ok': False, 'attempts': attempts, 'operator': spec['key'],
            'complaints': complaints, 'strays': strays, 'tries': tries}
