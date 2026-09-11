"""Раннер агента: инструкция, повтор с претензиями, посторонние изменения.

Настоящий Codex здесь не запускается. Вместо него — поддельный: скрипт, которому заранее
сказано, что писать на первой попытке, что на второй. Проверяется не Codex, а то, что
раннер верно решает, прошло задание или нет, — потому что решает именно он.
"""
import json
import subprocess
import sys
import time
import threading
from pathlib import Path

import pytest

from pathlib import Path as _P
ROOT = _P(__file__).resolve().parents[1]
import agent
import generate_sheet
import settings as panel_settings
import validators

# Хозяйство подделки лежит вне репозитория: файл, созданный ею внутри, раннер честно
# посчитал бы посторонней правкой — и тест ловил бы сам себя.
FAKE = '''import json, os, sys
from pathlib import Path

root, desk = Path(sys.argv[1]), Path(os.environ['FAKE_CODEX_DESK'])
plan = json.loads((desk / 'plan.json').read_text())
count = desk / 'calls'
n = int(count.read_text()) if count.is_file() else 0
count.write_text(str(n + 1))
for rel, content in (plan[n] if n < len(plan) else {}).items():
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding='utf-8')
(desk / 'prompt.txt').write_text(sys.argv[2], encoding='utf-8')
'''

SLUG = 'test-book'
PARAGRAPHS = [{'i': 0, 'chapter': 1, 'text': 'Первый абзац.'},
              {'i': 1, 'chapter': 1, 'text': 'Второй абзац, в нём про волосы.'},
              {'i': 2, 'chapter': 2, 'text': 'Третий абзац, другая глава.'}]

GOOD = {'name': 'Герой', 'appearance': 'Русое описание для человека.',
        'appearance_en': 'a plain english description for the prompt',
        'subject_en': 'a person of some sort in some place',
        'locators': [{'chapter': 1, 'paragraphs': [1, 2]}],
        'audit': {'age': 1, 'build': 1, 'face': 1, 'eyes': 0.5, 'hair': 1,
                  'skin': 1, 'clothing': 1, 'gear': 1, 'marks': 1, 'bearing': 0.5},
        'understanding': 9.0}


def bible(entry):
    return json.dumps({'characters': {'hero': entry}, 'places': {}}, ensure_ascii=False)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Временный репозиторий с кешем книги, пустой библией и поддельным Codex."""
    desk = tmp_path / 'desk'
    desk.mkdir()
    tmp_path = tmp_path / 'repo'
    tmp_path.mkdir()
    (tmp_path / '.gitignore').write_text('cache/\n', encoding='utf-8')
    (tmp_path / 'cache' / SLUG).mkdir(parents=True)
    (tmp_path / 'cache' / SLUG / 'paragraphs.jsonl').write_text(
        '\n'.join(json.dumps(p, ensure_ascii=False) for p in PARAGRAPHS), encoding='utf-8')
    (tmp_path / 'books' / SLUG).mkdir(parents=True)
    (tmp_path / 'books' / SLUG / 'bible.json').write_text(bible({}), encoding='utf-8')
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    subprocess.run(['git', 'add', '-A'], cwd=tmp_path, check=True)
    subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t',
                    'commit', '-qm', 'init'], cwd=tmp_path, check=True)
    (desk / 'fake_codex.py').write_text(FAKE, encoding='utf-8')
    monkeypatch.setenv('FAKE_CODEX_DESK', str(desk))
    return tmp_path


def desk_of(repo):
    return repo.parent / 'desk'


def config(repo, plan):
    desk = desk_of(repo)
    (desk / 'plan.json').write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
    return {'codex_cmd': [sys.executable, str(desk / 'fake_codex.py'), '{root}', '{prompt}'],
            'timeout': 60, 'attempts': 2}


def checker(repo):
    def validate():
        data = json.loads((repo / 'books' / SLUG / 'bible.json').read_text())
        return validators.check_bible_entry('hero', data['characters'].get('hero', {}),
                                            SLUG, repo)
    return validate


FIELDS = {'name': 'Герой', 'key': 'hero', 'slug': SLUG, 'title': 'Книга', 'hints': 'гл1 [1, 2)'}
EXPECTED = [f'books/{SLUG}/bible.json']


def test_instruction_names_skill_book_and_entity():
    text = agent.instruction('bible-entry', FIELDS)
    assert '.claude/skills/raskadrovka-characters/SKILL.md' in text
    assert SLUG in text and 'hero' in text and 'Герой' in text
    assert '$' not in text.replace('$ ', '')     # все поля подставлены


def test_good_result_passes_on_first_attempt(repo):
    plan = [{f'books/{SLUG}/bible.json': bible(GOOD)}]
    report = agent.run('bible-entry', FIELDS, checker(repo), EXPECTED,
                       root=repo, config=config(repo, plan))
    assert report['ok'] and report['attempts'] == 1


def test_bad_result_retries_with_verbatim_complaints(repo):
    broken = dict(GOOD, understanding=10.0)          # сумма клеток 9, а записано 10
    plan = [{f'books/{SLUG}/bible.json': bible(broken)},
            {f'books/{SLUG}/bible.json': bible(GOOD)}]
    report = agent.run('bible-entry', FIELDS, checker(repo), EXPECTED,
                       root=repo, config=config(repo, plan))
    assert report['ok'] and report['attempts'] == 2
    second = (desk_of(repo) / 'prompt.txt').read_text()
    assert 'сумма клеток аудита' in second
    assert 'Прошлая попытка не прошла проверку' in second


def test_two_failures_give_up_with_report(repo):
    broken = dict(GOOD, locators=[{'chapter': 1, 'paragraphs': [1, 1]}])
    plan = [{f'books/{SLUG}/bible.json': bible(broken)},
            {f'books/{SLUG}/bible.json': bible(broken)}]
    report = agent.run('bible-entry', FIELDS, checker(repo), EXPECTED,
                       root=repo, config=config(repo, plan))
    assert not report['ok'] and report['attempts'] == 2
    assert any('полуинтервал' in c for c in report['complaints'])


def test_a_stray_change_is_reported_but_does_not_undo_the_work(repo):
    """Отличить правку агента от правки человека, который те же десять минут работает
    в панели, по `git status` нельзя. Поэтому посторонняя правка — предупреждение, а не
    приговор: из-за такой догадки был выброшен уже нарисованный лист «Смерти»."""
    plan = [{f'books/{SLUG}/bible.json': bible(GOOD), 'README.md': 'кто-то правил рядом'}]
    report = agent.run('bible-entry', FIELDS, checker(repo), EXPECTED,
                       root=repo, config=config(repo, plan))
    assert report['ok'], report['complaints']       # работа сделана — значит сделана
    assert any('README.md' in c for c in report['strays'])
    assert not report['complaints']


def test_dirty_tree_before_start_is_not_a_stray_change(repo):
    """Дерево почти всегда грязное; провал даёт разница снимков, а не факт правок."""
    (repo / 'README.md').write_text('человек правил это до запуска', encoding='utf-8')
    plan = [{f'books/{SLUG}/bible.json': bible(GOOD)}]
    report = agent.run('bible-entry', FIELDS, checker(repo), EXPECTED,
                       root=repo, config=config(repo, plan))
    assert report['ok'], report['complaints']


def test_cancelling_stops_the_retry_instead_of_starting_it(repo):
    """Убитый Codex выглядит как неудачная попытка; без флага снятие стоило бы второго прогона."""
    stopped = threading.Event()          # человек снял задание, пока шла первая попытка
    broken = dict(GOOD, understanding=10.0)
    plan = [{f'books/{SLUG}/bible.json': bible(broken)},
            {f'books/{SLUG}/bible.json': bible(GOOD)}]

    def should_stop():
        if not stopped.is_set() and (desk_of(repo) / 'calls').is_file():
            stopped.set()
        return stopped.is_set()

    report = agent.run('bible-entry', FIELDS, checker(repo), EXPECTED,
                       root=repo, config=config(repo, plan), should_stop=should_stop)
    assert not report['ok'] and report['stopped'] is True
    assert report['complaints'] == ['задание снято человеком']
    assert (desk_of(repo) / 'calls').read_text() == '1'      # Codex позвали ровно один раз


def test_log_keeps_prompt_and_outcome(repo):
    plan = [{f'books/{SLUG}/bible.json': bible(GOOD)}]
    log = repo / 'cache' / 'panel' / 'jobs' / 'job.log'
    agent.run('bible-entry', FIELDS, checker(repo), EXPECTED,
              root=repo, config=config(repo, plan), log=log)
    assert 'проверка: годно' in log.read_text()
    assert 'raskadrovka-characters' in log.with_suffix('.prompt.txt').read_text()


# — выбор оператора —

def test_operator_takes_the_command_from_its_own_setting():
    """`codex_cmd` остаётся именем настройки Codex: им подменяют команду тесты и человек."""
    spec = panel_settings.operator(None, {'operator': 'codex', 'codex_cmd': ['мой-codex']})
    assert spec['key'] == 'codex' and spec['cmd'] == ['мой-codex']
    claude = panel_settings.operator('claude', {'operator': 'codex'})
    assert claude['cmd'][0] == 'claude' and '--permission-mode' in claude['cmd']
    assert claude['sandbox'] != spec['sandbox']              # разницу видно человеку


def test_unknown_operator_is_an_error_not_a_quiet_fallback():
    with pytest.raises(ValueError, match='неизвестный оператор'):
        panel_settings.operator('gpt', {'operator': 'codex'})


def test_chosen_operator_runs_and_is_named_in_the_log(repo):
    """Читает книгу тот, кого выбрали, и в шапке попытки написано кто именно."""
    plan = [{f'books/{SLUG}/bible.json': bible(GOOD)}]
    settings = dict(config(repo, plan), operator='claude')
    settings['claude_cmd'] = settings.pop('codex_cmd')       # подделка встала на место Claude
    log = repo / 'cache' / 'panel' / 'jobs' / 'job.log'
    report = agent.run('bible-entry', FIELDS, checker(repo), EXPECTED,
                       root=repo, config=settings, log=log)
    assert report['ok'] and report['operator'] == 'claude'
    assert 'оператор Claude — без песочницы' in log.read_text()


def test_sheet_is_drawn_by_codex_even_when_the_choice_says_claude(repo):
    """Картинку умеет только Codex. Выбор оператора на рисование не распространяется —
    иначе смена оператора тихо ломала бы листы и кадры."""
    (repo / 'books' / SLUG / 'bible.json').write_text(bible(GOOD), encoding='utf-8')
    rel = f'cache/panel/{SLUG}/sheets/hero.png'
    drawing = ('from pathlib import Path\nimport sys\n'
               'out = Path(sys.argv[1]) / %r\n'
               'out.parent.mkdir(parents=True, exist_ok=True)\n'
               'out.write_bytes(bytes([137, 80, 78, 71, 13, 10, 26, 10]) + b"0" * 200000)\n'
               % rel)
    (desk_of(repo) / 'fake_draw.py').write_text(drawing, encoding='utf-8')

    settings = {'operator': 'claude', 'attempts': 1, 'timeout': 60,
                'claude_cmd': ['несуществующая-команда', '{prompt}'],
                'codex_cmd': [sys.executable, str(desk_of(repo) / 'fake_draw.py'),
                              '{root}', '{prompt}']}
    report = generate_sheet.make(SLUG, 'hero', root=repo, out=rel, config=settings)
    assert report['ok'], report['complaints']
    assert report['operator'] == 'codex'


def test_a_deleted_file_is_caught_even_though_git_status_only_gets_shorter(repo):
    """Удаление неотслеживаемого файла убирает строку из `git status`, а не добавляет.
    Из-за этого пропажа трёх листов персонажей прошла мимо проверки."""
    victim = repo / 'books' / SLUG / 'characters' / 'hero.png'
    victim.parent.mkdir(parents=True, exist_ok=True)
    victim.write_bytes(b'\x89PNG')
    before = agent.git_status(repo)
    assert any('characters/hero.png' in line for line in before)

    victim.unlink()
    out = agent.stray_changes(before, agent.git_status(repo), [f'books/{SLUG}/bible.json'],
                              root=repo)
    assert any('удалило файл' in c and 'characters/hero.png' in c for c in out)


def test_a_commit_made_by_a_human_mid_job_is_not_called_a_deletion(repo):
    """Человек коммитит, пока задание идёт, — строки из `git status` тоже пропадают.
    Отличие простое: после коммита файл на месте."""
    kept = repo / 'books' / SLUG / 'characters' / 'hero.png'
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_bytes(b'\x89PNG')
    before = agent.git_status(repo)

    subprocess.run(['git', 'add', '-A'], cwd=repo, check=True)
    subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t',
                    'commit', '-qm', 'человек закоммитил на ходу'], cwd=repo, check=True)
    assert not agent.stray_changes(before, agent.git_status(repo),
                                   [f'books/{SLUG}/bible.json'], root=repo)


def test_a_stray_change_never_reaches_the_agent_as_an_order_to_fix(repo):
    """Пока задание идёт свои минуты, в том же дереве работают человек и панель. Их файл
    попадает в разницу снимков, и если отдать эту претензию агенту дословно — «исправь
    ровно это», — он поймёт «убери файл X» и уберёт. Так были стёрты чужие файлы."""
    theirs = repo / 'tests' / 'their_new_file.py'
    theirs.parent.mkdir(parents=True, exist_ok=True)

    def validate():
        theirs.write_text('# файл появился, пока шло задание\n', encoding='utf-8')
        return []                                   # к самой работе претензий нет

    log = repo / 'cache' / 'panel' / 'jobs' / 'job.log'
    plan = [{f'books/{SLUG}/bible.json': bible(GOOD)},
            {f'books/{SLUG}/bible.json': bible(GOOD)}]
    report = agent.run('bible-entry', FIELDS, validate, EXPECTED,
                       root=repo, config=config(repo, plan), log=log)

    assert report['ok'] and report['strays']
    assert 'their_new_file.py' in report['strays'][0]
    # Второй попытки нет: к работе претензий не было, а повтор — это ещё один прогон
    # агента, которому претензию пришлось бы передать.
    assert report['attempts'] == 1
    assert (desk_of(repo) / 'calls').read_text() == '1'
    assert 'their_new_file.py' not in log.with_suffix('.prompt.txt').read_text(encoding='utf-8')
    assert theirs.is_file()                         # и чужой файл на месте


def test_a_file_the_job_deleted_in_another_book_comes_back(repo):
    """Агент проверяет себя через `git status`, видит там чужой файл и «наводит порядок».
    Так был удалён лист Кирэна из соседней книги — во время задания по другой книге,
    на первой же попытке, без всякой подсказки от панели."""
    theirs = repo / 'books' / 'other-book' / 'characters' / 'kieran.png'
    theirs.parent.mkdir(parents=True, exist_ok=True)
    theirs.write_bytes(b'\x89PNG' + b'\x00' * 500)
    было = theirs.read_bytes()

    def validate():
        theirs.unlink()                     # ровно то, что сделал настоящий агент
        return []

    log = repo / 'cache' / 'panel' / 'jobs' / 'job.log'
    plan = [{f'books/{SLUG}/bible.json': bible(GOOD)}]
    report = agent.run('bible-entry', FIELDS, validate, EXPECTED,
                       root=repo, config=config(repo, plan), log=log)

    assert theirs.is_file() and theirs.read_bytes() == было
    assert not report['ok']
    assert any('удалило чужой файл' in c and 'kieran.png' in c for c in report['complaints'])
    assert 'панель вернула чужие файлы' in log.read_text(encoding='utf-8')


def test_the_job_is_told_not_to_tidy_the_tree(repo):
    plan = [{f'books/{SLUG}/bible.json': bible(GOOD)}]
    log = repo / 'cache' / 'panel' / 'jobs' / 'job.log'
    agent.run('bible-entry', FIELDS, checker(repo), EXPECTED,
              root=repo, config=config(repo, plan), log=log)
    sent = log.with_suffix('.prompt.txt').read_text(encoding='utf-8')
    assert 'Ничего не удаляй' in sent and 'не делай резервных копий' in sent


def test_the_book_text_gets_no_second_path_even_for_safekeeping(repo):
    """Право на текст книги — читать, а не копировать. Второй дороги к нему панель
    не заводит даже жёсткой ссылкой в собственном кеше."""
    source = repo / 'books' / SLUG / 'source' / 'book.fb2'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('весь текст книги', encoding='utf-8')
    store = repo / 'cache' / 'panel' / 'guard' / 'проба'
    store.mkdir(parents=True)

    kept = agent.guard(repo, [f'books/{SLUG}/bible.json'], store)
    assert not any('/source/' in rel for rel in kept)
    assert not list(store.rglob('*.fb2'))


def test_forgotten_guard_folders_are_swept(repo):
    """Панель убивают на ходу, и каталог страховки остаётся. Ссылки места не занимают,
    но держат данные удалённых файлов живыми — тихо и навсегда."""
    import os
    guard = repo / 'cache' / 'panel' / 'guard'
    stale = guard / 'guard-забытый'
    stale.mkdir(parents=True)
    (stale / 'file').write_text('x', encoding='utf-8')
    old = time.time() - agent.STALE_GUARD - 60
    os.utime(stale, (old, old))
    fresh = guard / 'guard-свежий'
    fresh.mkdir()

    agent._guard_dir(repo)
    assert not stale.exists() and fresh.exists()


REFUSAL = ('2026-09-11T11:05:31Z ERROR codex_core::tools::router: error=image generation '
           'failed: http 400 Bad Request: {"error": {"message": "Your request was rejected '
           'by the safety system. safety_violations=[sexual].", "code": "moderation_blocked"}}')


def test_a_refusal_to_draw_is_named_and_not_retried(repo, monkeypatch):
    """Цензура генератора приходит строкой в выводе, а код возврата нулевой. Для панели
    это выглядит как «файла нет», и повтор гонит агента нарисовать хоть что-нибудь: так
    вместо голого старика с косой появилась аниме-девушка «MAYA TANAKA»."""
    monkeypatch.setattr(agent, 'run_operator',
                        lambda *a, **kw: (0, REFUSAL, 1.0))
    report = agent.run(None, {}, lambda: ['файла нет — изображение не сохранено'],
                       ['cache/panel/x/sheets/hero.png'], root=repo,
                       config={'attempts': 2, 'codex_cmd': ['true'], 'timeout': 5},
                       prompt='нарисуй')
    assert not report['ok'] and report['refused'] is True
    assert report['attempts'] == 1                  # второй попытки нет
    assert 'отказался рисовать' in report['complaints'][0]
    assert 'safety' in report['complaints'][0]


def test_an_ordinary_failure_still_gets_its_second_try(repo):
    """Отказ цензуры — не всякая неудача: обычный провал по-прежнему даёт повтор."""
    broken = dict(GOOD, understanding=10.0)
    plan = [{f'books/{SLUG}/bible.json': bible(broken)},
            {f'books/{SLUG}/bible.json': bible(GOOD)}]
    report = agent.run('bible-entry', FIELDS, checker(repo), EXPECTED,
                       root=repo, config=config(repo, plan))
    assert report['ok'] and report['attempts'] == 2


def test_the_prompt_does_not_declare_itself_a_refusal():
    """В промпте листа есть оговорка «если это нельзя нарисовать по content policy…»,
    а Codex печатает промпт эхом в свой вывод. Проверка отказа ищет машинные коды ответа
    API — человеческими оборотами она объявляла отказом каждое удачное рисование."""
    import sys
    sys.path.insert(0, str(ROOT / 'scripts'))
    import generate_sheet
    body = generate_sheet.body('an old man', 'naked old man; rusty scythe')
    assert 'content policy' in body                 # оговорка на месте
    assert agent.refusal(generate_sheet.instruction(body, 'out.png')) is None
    assert agent.refusal(REFUSAL) is not None       # а настоящий отказ по-прежнему виден
