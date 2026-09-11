"""Страница панели — один файл без сборки, и опечатку в нём ловить нечему.

Дважды правка по номерам строк молча уносила лишнее: в первый раз незакрытым остался
`<div class="audit-block">` и браузер заглотил внутрь него половину ячейки, во второй —
вместе с двумя удалёнными функциями уехала третья, `disclose`, и экран «Персонажи»
перестал открываться совсем. Ни то, ни другое не видно ни в одном тесте, пока экран
не откроют руками.

Проверки здесь дешёвые и грубые, но ловят ровно этот класс: разметку, которую браузер
молча починит по-своему, и имя, которого больше нет.
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / 'panel' / 'index.html').read_text(encoding='utf-8')
SCRIPT = PAGE[PAGE.index('<script>'):PAGE.rindex('</script>')]

# То, что даёт сам язык и браузер. Список короткий нарочно: чем он длиннее, тем меньше
# проверка ловит.
BUILTIN = {
    'if', 'for', 'while', 'switch', 'catch', 'return', 'function', 'typeof', 'await', 'new',
    'async', 'delete', 'void', 'yield', 'in', 'of',
    'parseInt', 'parseFloat', 'decodeURIComponent', 'encodeURIComponent', 'isNaN',
    'setTimeout', 'setInterval', 'clearTimeout', 'clearInterval', 'requestAnimationFrame',
    'fetch', 'confirm', 'alert', 'btoa', 'atob', 'structuredClone', 'queueMicrotask',
}


def test_tags_opened_in_templates_are_closed():
    """Незакрытый тег браузер чинит по-своему: `<div class="audit-block">` без пары
    проглотил и плашки, и раскрывашку, и вся раскладка ячейки перестала работать."""
    for tag in ('div', 'span', 'button', 'table', 'tr', 'td'):
        opened = len(re.findall(rf'<{tag}\b', SCRIPT))
        closed = len(re.findall(rf'</{tag}>', SCRIPT))
        assert opened == closed, f'<{tag}>: открыто {opened}, закрыто {closed}'


def test_every_called_function_exists():
    """Имя, которого больше нет, страница не покажет до первого открытия экрана."""
    declared = set(re.findall(r'\bfunction\s+(\w+)\s*\(', SCRIPT))
    declared |= set(re.findall(r'\b(?:const|let|var)\s+(\w+)', SCRIPT))
    declared |= set(re.findall(r'\bcatch\s*\(\s*(\w+)', SCRIPT))
    declared |= set(re.findall(r'\bfunction\s+\w+\s*\(([^)]*)\)', SCRIPT)
                    ) and set(re.findall(r'[\w$]+', ' '.join(
                        re.findall(r'\bfunction\s+\w+\s*\(([^)]*)\)', SCRIPT))))
    # Вызовы вида `имя(` в начале выражения: методы (`.map(`) отсеяны взглядом назад.
    called = set(re.findall(r'(?<![.\w$])([a-z][A-Za-z0-9_$]{2,})\s*\(', SCRIPT))
    missing = sorted(called - declared - BUILTIN)
    assert not missing, f'вызываются, но не объявлены: {", ".join(missing)}'


def test_every_action_has_a_handler():
    """Список действий и разбор нажатия живут в разных местах и расходятся молча:
    так уже случилось с половиной кнопок цепочки — кнопка есть, нажатие не ловится."""
    listed = re.search(r'const ACTIONS = \[(.*?)\];', SCRIPT, re.S)
    assert listed, 'списка ACTIONS в странице нет'
    actions = re.findall(r"'(\w+)'", listed.group(1))
    assert len(actions) > 10
    handler = SCRIPT[SCRIPT.index('const ACTION_SELECTOR'):]
    blind = [a for a in actions if f'd.{a}' not in handler]
    assert not blind, f'кнопки без обработчика: {", ".join(blind)}'


def test_every_handler_action_is_listed():
    """И наоборот: обработчик, которого нет в списке, не поймает ни одного нажатия —
    селектор собирается из списка."""
    handler = SCRIPT[SCRIPT.index('const ACTION_SELECTOR'):]
    listed = set(re.findall(r"'(\w+)'", re.search(r'const ACTIONS = \[(.*?)\];',
                                                  SCRIPT, re.S).group(1)))
    used = set(re.findall(r'\bd\.(\w+)\b', handler)) - {'key', 'file', 'was'}
    assert not used - listed, f'разбираются, но не перечислены: {", ".join(sorted(used - listed))}'


@pytest.mark.skipif(shutil.which('node') is None, reason='node не установлен')
def test_the_script_parses():
    """Опечатка в скрипте не ломает ни один экран по отдельности — она ломает страницу
    целиком: браузер не выполняет ничего, и человек видит голый фон. Так уже случилось
    с `const` внутри `if` без скобок, и ни одна из проверок выше этого не заметила:
    теги были сбалансированы, имена объявлены.

    Разбор делает `node --check`, если он есть. Это единственное место, где панели нужен
    не Python; без node проверка пропускается, а не врёт.
    """
    with tempfile.NamedTemporaryFile('w', suffix='.js', encoding='utf-8', delete=False) as fh:
        fh.write(SCRIPT[len('<script>'):])
        path = fh.name
    try:
        done = subprocess.run(['node', '--check', path], capture_output=True, text=True)
    finally:
        Path(path).unlink(missing_ok=True)
    assert done.returncode == 0, done.stderr.strip()[:600]
