"""Настройки панели: значения по умолчанию в коде, переопределения — в `cache/panel/settings.json`.

Оператор — тот, кто исполняет шаг с суждением: читает книгу, собирает запись героя, пишет
карточку сцены. Их два, и разница между ними не в уме, а в песочнице: `codex exec
-s workspace-write` физически не может писать вне рабочего каталога, а `claude -p
--permission-mode bypassPermissions` может всё, и границы задания держит только проверка
после него. Поэтому оператор — видимая настройка, а не спрятанная константа.

Рисование к выбору не относится: инструмент `image_gen` есть только у Codex, и в
`generate_sheet` и `generate_scene` оператор прибит гвоздём (`DRAWS`).

Командная строка живёт здесь, а не внутри раннера, по двум причинам: тест обязан подсунуть
поддельный `codex`, а человек — сменить профиль или модель, не правя панель.
Только стандартная библиотека.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Кто исполняет шаги с суждением. Команда каждого лежит не здесь, а в настройке
# `<ключ>_cmd`: так её подменяют тесты и человек, не трогая эту таблицу.
OPERATORS = {
    'codex': {'title': 'Codex', 'short': 'в песочнице',
              'sandbox': 'песочница: пишет только в рабочий каталог'},
    'claude': {'title': 'Claude', 'short': 'без песочницы',
               'sandbox': 'без песочницы: пишет куда угодно, границы держит проверка'},
}

# Рисует всегда Codex — у Claude нет инструмента для картинки. Выбор оператора этого
# не касается, и менять здесь нечего, пока это не изменится.
DRAWS = 'codex'

DEFAULTS = {
    'operator': 'codex',
    # {root} и {prompt} подставляет раннер; остальные аргументы идут как есть.
    'codex_cmd': ['codex', 'exec', '-s', 'workspace-write', '--skip-git-repo-check',
                  '-C', '{root}', '--ephemeral', '{prompt}'],
    'claude_cmd': ['claude', '-p', '--permission-mode', 'bypassPermissions', '{prompt}'],
    'timeout': 1800,          # запись героя на настоящем Codex шла 969 с; 20 минут впритык
    'attempts': 2,
    # Сколько заданий идут рядом. Спорящие за один файл всё равно пойдут по очереди —
    # ширина решает только, сколько непересекающихся панель возьмёт разом. Цена прямая:
    # столько же одновременных прогонов Codex и столько же расхода в моменте.
    'jobs': 1,
    'max_style_refs': 3,
}


def file(root=ROOT):
    return Path(root) / 'cache' / 'panel' / 'settings.json'


def load(root=ROOT):
    values = dict(DEFAULTS)
    path = file(root)
    if path.is_file():
        values.update(json.loads(path.read_text(encoding='utf-8')))
    return values


def save(values, root=ROOT):
    path = file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def operator(name=None, config=None, root=ROOT):
    """Оператор по имени: заголовок, подпись о песочнице и команда.

    Пустое имя — тот, что выбран в настройках. Неизвестное имя — ошибка, а не тихий откат
    к Codex: молча подменённый оператор хуже упавшего задания, потому что в логе он будет
    назван правильно, а работать будет другой.
    """
    config = load(root) if config is None else config
    name = name or config.get('operator') or 'codex'
    if name not in OPERATORS:
        raise ValueError(f'неизвестный оператор: {name!r}; есть {", ".join(OPERATORS)}')
    command = config.get(f'{name}_cmd') or DEFAULTS.get(f'{name}_cmd')
    if not command:
        raise ValueError(f'у оператора {name} нет команды: нужна настройка {name}_cmd')
    return dict(OPERATORS[name], key=name, cmd=list(command))


def choices():
    """Операторы для окна выбора: ключ, заголовок, подпись о песочнице — без команд."""
    return [dict(spec, key=key) for key, spec in OPERATORS.items()]
