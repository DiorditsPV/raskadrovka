"""Раннер агента: инструкция, повтор с претензиями, посторонние изменения.

Настоящий Codex здесь не запускается. Вместо него — поддельный: скрипт, которому заранее
сказано, что писать на первой попытке, что на второй. Проверяется не Codex, а то, что
раннер верно решает, прошло задание или нет, — потому что решает именно он.
"""
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import agent
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


def test_stray_change_fails_the_job(repo):
    plan = [{f'books/{SLUG}/bible.json': bible(GOOD), 'README.md': 'агент полез не туда'},
            {f'books/{SLUG}/bible.json': bible(GOOD), 'README.md': 'и ещё раз'}]
    report = agent.run('bible-entry', FIELDS, checker(repo), EXPECTED,
                       root=repo, config=config(repo, plan))
    assert not report['ok']
    assert any('README.md' in c for c in report['complaints'])


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
