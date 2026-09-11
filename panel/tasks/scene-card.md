Ты пишешь карточку сцены для партии кадров в проекте «Раскадровка».

**Сначала прочти `.claude/skills/raskadrovka-scenes/SKILL.md` целиком и действуй строго по
нему.** Всё, что ниже, — адрес работы и то, что чаще всего портят.

## Что сделать

Книга: «$title», слаг `$slug`. Партия: `books/$slug/$batch/`.
Карточка: `books/$slug/$batch/scenes/$card.json`, её `id` — `$card`, порядковый номер `$order`.

Замысел человека, дословно: **$brief**

Место в книге: $where

## Где читать книгу

Текста книги в репозитории нет — есть разобранный кеш. Читай только через него, из корня
репозитория:

```bash
python3 scripts/show_paragraphs.py $slug --range A B          # абзацы [A, B)
python3 scripts/show_paragraphs.py $slug --chapter N --width 240
python3 scripts/show_paragraphs.py $slug --grep "слово" --width 240
```

Найди сам точные абзацы сцены: указание человека — ориентир, а не готовый локатор.

## Что записать

Один файл — `books/$slug/$batch/scenes/$card.json`. Форма:

```json
{
  "id": "$card",
  "book": "$slug",
  "title": "Название сцены по-русски",
  "order": $order,
  "locator": {"chapter": N, "paragraphs": [A, B]},
  "excerpt": {"text": "отрывок книги дословно", "attribution": "Автор, «Книга», издание, год"},
  "caption": "Одна фраза по-русски: что здесь происходит.",
  "brief": "Замысел кадра по-русски, три-четыре фразы, для человека.",
  "frame": {
    "setting": "where it happens, in english",
    "time": "time of day or shift",
    "characters": [{"ref": "ключ_героя", "state": "what they are doing, in english"}],
    "action": "what happens, in english",
    "mood": "in english",
    "details": ["…", "…"],
    "composition": "where the bodies stand and how the frame is cut, in english",
    "avoid": ["…"]
  },
  "composition": "01-dvoe-litsom",
  "style_refs": [],
  "invariants": ["ключ_героя"]
}
```

Правила, на которых карточки чаще всего ломаются:

- `locator` — **полуинтервал**: один абзац 57 записывается как `[57, 58]`, а `[57, 57]` пусто.
  Номер абзаца — тот, что печатает `show_paragraphs.py` в первой колонке.
- `excerpt.text` — дословный отрывок, **целыми абзацами**. У защищённой книги — не больше
  двух абзацев и не больше 1500 знаков.
- `frame` целиком пишется **по-английски**: он уходит в промпт слово в слово. `caption`,
  `brief` и `title` — по-русски, они для человека.
- `invariants` и `frame.characters[].ref` — ключи из `books/$slug/bible.json`. Героев,
  которых там нет, не выдумывай: $heroes
- `composition` — идентификатор шаблона из `compositions/templates/`, если он подходит;
  иначе `null`. Доступные: $compositions
- Манеру не описывай: манера живёт в направлении стиля, а не в карточке. Ни «watercolour»,
  ни «cinematic», ни имён художников.

## Границы

- Меняй только `books/$slug/$batch/scenes/$card.json`. Прочие карточки, библия, манифест и
  остальные файлы репозитория остаются нетронутыми.
- Ничего не коммить, `git add` не делай, картинок не генерируй.
- Если книга не даёт того, что просит замысел, — напиши об этом в ответе и опиши то, что
  в книге есть, а не то, чего хотелось.

В конце ответа скажи, какие абзацы взял и почему именно их.
