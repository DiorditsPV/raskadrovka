"""Настройки панели: значения по умолчанию в коде, переопределения — в `cache/panel/settings.json`.

Командная строка Codex живёт здесь, а не внутри раннера, по двум причинам: тест обязан
подсунуть поддельный `codex`, а человек — сменить профиль или модель, не правя панель.
Только стандартная библиотека.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULTS = {
    # {root} и {prompt} подставляет раннер; остальные аргументы идут как есть.
    'codex_cmd': ['codex', 'exec', '-s', 'workspace-write', '--skip-git-repo-check',
                  '-C', '{root}', '--ephemeral', '{prompt}'],
    'timeout': 1800,          # запись героя на настоящем Codex шла 969 с; 20 минут впритык
    'attempts': 2,
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
