# Папка книги

```text
books/<книга>/
  book.json                 манифест книги: без текста
  bible.json                персонажи и места с локаторами
  source/                   файл книги — игнорируется git
  <партия>/
    README.md               что в партии, ссылки на результаты
    scenes/<сцена>.json     карточки сцен
    prompt/<сцена>.txt      точный промпт, собранный из карточки
    input/<сцена>/          использованные референсы и edit-target
    metadata/request.json   манифест партии
    metadata/refs.json      источники и лицензии референсов
```

Слаг книги — латиницей, `<автор>-<название>`: `gogol-shinel`. Слаг партии — с порядковым номером:
`01-first-batch`. Идентификатор сцены — номер и короткое имя: `03-akakiy-at-the-tailor`. Имя
результата: `output/gogol-shinel--01-first-batch--03-akakiy-at-the-tailor.png`.

## book.json

```json
{
  "slug": "gogol-shinel",
  "title": "Шинель",
  "author": "Николай Гоголь",
  "translator": null,
  "language": "ru",
  "edition": "Собрание сочинений в 7 томах, т. 3. М.: Художественная литература, 1977",
  "year_published": 1842,
  "rights": {"status": "public-domain", "basis": "автор умер в 1852 году, оригинал на русском", "checked": "2026-09-07"},
  "source": {"format": "fb2", "sha256": "…", "chars": 0, "paragraphs": 0},
  "chapters": [{"index": 1, "title": "Шинель", "paragraphs": [0, 118]}]
}
```

`rights.status` — `public-domain` или `protected`. `chapters[].paragraphs` — полуинтервал индексов
абзацев из локального разбора `cache/<книга>/paragraphs.jsonl`; индексы стабильны при том же
`source.sha256`.

## bible.json

```json
{
  "characters": {
    "akakiy": {
      "name": "Акакий Акакиевич Башмачкин",
      "appearance": "низенький, рябоват, рыжеват, подслеповат, с лысиной на лбу",
      "appearance_en": "short, pockmarked, reddish-haired, weak-sighted, balding at the forehead; a worn uniform coat",
      "locators": [{"chapter": 1, "paragraphs": [2, 2]}]
    }
  },
  "places": {
    "department": {
      "name": "департамент",
      "look_en": "a long clerks' hall with rows of desks, green baize, candles, stacks of papers",
      "locators": [{"chapter": 1, "paragraphs": [4, 5]}]
    }
  }
}
```

Русские поля — для людей, поля `_en` — для промпта: генераторы лучше слушают английский.

## Карточка сцены

```json
{
  "id": "03-akakiy-at-the-tailor",
  "book": "gogol-shinel",
  "title": "Акакий Акакиевич у Петровича",
  "order": 3,
  "locator": {"chapter": 1, "paragraphs": [31, 32]},
  "excerpt": {
    "text": "…один-два абзаца из указанных…",
    "attribution": "Н. В. Гоголь, «Шинель»"
  },
  "caption": "Одна фраза для подписи в галерее.",
  "brief": "Что происходит в кадре, по-русски, для людей.",
  "frame": {
    "setting": "a cramped tailor's room up a dark back staircase, a single window, winter light",
    "time": "late morning, grey Petersburg winter",
    "characters": [{"ref": "akakiy", "state": "holding the threadbare overcoat, anxious"}, {"ref": "petrovich", "state": "seated on the table, barefoot, one-eyed, examining the cloth"}],
    "action": "Petrovich turns the coat to the light and shakes his head; Akakiy waits with folded hands",
    "mood": "quiet dread, faintly comic",
    "details": ["a snuffbox with a general's face pasted over", "threads and scraps on the floor", "a bare foot with a misshapen nail"],
    "composition": "two figures at a table, window behind, coat as the visual centre",
    "avoid": ["modern furniture", "any legible text"]
  },
  "style_refs": ["ref-01"],
  "invariants": ["akakiy", "petrovich"]
}
```

`frame` пишется по-английски: из него собирается промпт. `style_refs` ссылаются на записи в
`metadata/refs.json`, `invariants` — на ключи библии, чьё описание должно попасть в промпт
дословно.

## metadata/refs.json

```json
{
  "ref-01": {
    "file": "input/03-akakiy-at-the-tailor/ref-01.png",
    "stored": true,
    "sha256": "…",
    "source": "https://commons.wikimedia.org/wiki/File:…",
    "author": "…",
    "license": "public-domain",
    "why": "приглушённая гуашь, тёплая бумага, тонкая штриховка",
    "style_notes_en": "muted gouache on warm paper, fine hatching, restrained palette of ochre, slate and brick red"
  }
}
```

`stored: false` означает, что файл лежит в `refs-local/` и в git не попадает; хеш всё равно
записывается.

## metadata/request.json

```json
{
  "schema_version": 2,
  "book": "gogol-shinel",
  "title": "Шинель — первая партия",
  "request": "Шесть ключевых сцен «Шинели» в манере референса ref-01.",
  "path_base": "request-directory",
  "scenes": [
    {
      "id": "03-akakiy-at-the-tailor",
      "title": "Акакий Акакиевич у Петровича",
      "order": 3,
      "latest": true,
      "caption": "Одна фраза для подписи в галерее.",
      "card": "scenes/03-akakiy-at-the-tailor.json",
      "card_sha256": "…",
      "prompt": "prompt/03-akakiy-at-the-tailor.txt",
      "prompt_sha256": "…",
      "output": "../../../output/gogol-shinel--01-first-batch--03-akakiy-at-the-tailor.png",
      "output_sha256": "…",
      "inputs": [
        {"path": "input/03-akakiy-at-the-tailor/ref-01.png", "sha256": "…", "role": "style-reference", "stored": true}
      ]
    }
  ]
}
```

Роли входов: `style-reference`, `edit-target`. Сборка галереи проверяет хеши всех файлов с
`stored: true` и то, что результат лежит в корневом `output/`.
