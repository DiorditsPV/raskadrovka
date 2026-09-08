# Папка книги

```text
books/<книга>/
  book.json                 манифест книги: без текста, с хешами абзацев
  bible.json                персонажи и места с локаторами и листами
  characters/<ключ>.png     лист персонажа: один на книгу, общий для всех её сцен
  source/                   файл книги — игнорируется git
  <партия>/
    README.md               что в партии; список кадров между маркерами пишет машина
    scenes/<сцена>.json     карточки сцен
    prompt/<сцена>.txt      точный промпт, собранный из карточки
    input/                  стилевые референсы партии: одна манера — одна копия
    input/<сцена>/          то, что принадлежит одному кадру: edit-target
    metadata/request.json   манифест партии
    metadata/refs.json      источники и лицензии референсов
```

Слаг книги — латиницей, `<автор>-<название>`: `gogol-shinel`. Слаг партии — с порядковым
номером: `01-first-batch`. Идентификатор сцены — номер и короткое имя:
`03-akakiy-at-the-tailor`. Имя результата:
`output/gogol-shinel--01-first-batch--03-akakiy-at-the-tailor.png`.

Одна сцена в партии — одна версия. Исправление, которое нужно сохранить рядом с прежним,
делается новой партией (`02-<что-исправляли>`): прежняя партия целиком уезжает в локальный
игнорируемый `archive/`. Поэтому в манифесте нет флага актуальности — в `output/` и в
галерее лежит только то, что опубликовано сейчас.

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
  "paragraph_sha256": ["…", "…"],
  "chapters": [{"index": 1, "title": "Шинель", "paragraphs": [0, 118]}]
}
```

`rights.status` — `public-domain` или `protected`. `chapters[].paragraphs` — полуинтервал
индексов абзацев из локального разбора `cache/<книга>/paragraphs.jsonl`; индексы стабильны
при том же `source.sha256`.

`paragraph_sha256[i]` — SHA-256 абзаца `i` после нормализации пробелов. Хеши не
восстанавливают текст, поэтому книга в репозиторий по-прежнему не попадает, — но по ним
проверяется, что отрывок в карточке взят из абзацев локатора. Без них эта проверка работала
бы только там, где лежит игнорируемый `cache/`, то есть ни у кого, кроме автора.

## bible.json

```json
{
  "characters": {
    "akakiy": {
      "name": "Акакий Акакиевич Башмачкин",
      "appearance": "низенький, рябоват, рыжеват, подслеповат, с лысиной на лбу",
      "appearance_en": "short, pockmarked, reddish-haired, weak-sighted, balding at the forehead; a worn uniform coat",
      "locators": [{"chapter": 1, "paragraphs": [2, 2]}],
      "sheet": "characters/akakiy.png",
      "sheet_sha256": "…",
      "sheet_prompt": "prompt-sheet-akakiy.txt"
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

`sheet` — лист персонажа: одно изображение, сгенерированное по описанию внешности из книги
и выбранному направлению стиля. Он общий для всех сцен книги и подаётся в каждый промпт,
где герой в кадре, с ролью `character-reference`. Описание словами удерживает героя хуже,
чем картинка, поэтому `appearance_en` остаётся, но опорой служит лист.

## Карточка сцены

```json
{
  "id": "03-akakiy-at-the-tailor",
  "book": "gogol-shinel",
  "title": "Акакий Акакиевич у Петровича",
  "order": 3,
  "locator": {"chapter": 1, "paragraphs": [31, 32]},
  "excerpt": {
    "text": "…целиком абзацы 31 и 32, без цитат из середины…",
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

Отрывок — **целые абзацы локатора** после нормализации пробелов, без цитат из середины
абзаца. Иначе его нельзя сверить по `paragraph_sha256`, и проверка прав перестаёт работать
везде, кроме машины автора.

## metadata/refs.json

```json
{
  "tush-i-plashki--ref-01": {
    "file": "input/style--tush-i-plashki--ref-01.png",
    "stored": true,
    "sha256": "…",
    "source": "https://commons.wikimedia.org/wiki/File:…",
    "author": "…",
    "license": "public-domain",
    "license_basis": "автор умер в 1927 году: свободно в РФ (70 лет) и в США (публикация до 1930)",
    "why": "приглушённая гуашь, тёплая бумага, тонкая штриховка",
    "style_notes_en": "muted gouache on warm paper, fine hatching, restrained palette of ochre, slate and brick red",
    "from_style": "sovetskaya-knizhnaya-grafika"
  }
}
```

Ключ — `<направление>--<эталон>`: в одной партии могут встретиться несколько направлений, а
у каждого нумерация эталонов своя, и голого `ref-01` на всех не хватит.

Файл пишет `scripts/register_result.py` по тем эталонам, которые действительно ушли в
промпты: лицензия и `license_basis` копируются из `styles/directions/<направление>.json`.
Копия, а не ссылка, — чтобы по одной папке партии можно было ответить, публикуется ли это,
не открывая остального репозитория.

`file` — путь относительно папки партии. Стилевой референс лежит в `input/` без подпапки:
партия по определению делает серию в одной манере, и копировать один и тот же файл в
`input/<сцена>/` на каждую сцену значит класть его в git по разу на кадр. В `input/<сцена>/`
попадает только принадлежащее одному кадру — `edit-target`.

`stored: false` означает, что файл лежит в `refs-local/` и в git не попадает; в `file` тогда
пишется путь туда (`refs-local/<имя>`), хеш записывается всё равно.

`license_basis` обязателен: одной строки `license` мало, потому что свобода проверяется и по
российскому сроку, и по американскому. `from_style` — направление из `styles/`, снимком
которого взят референс.

## metadata/request.json

```json
{
  "schema_version": 2,
  "book": "gogol-shinel",
  "title": "Шинель — первая партия",
  "request": "Шесть ключевых сцен «Шинели» в манере направления sovetskaya-knizhnaya-grafika.",
  "style": "sovetskaya-knizhnaya-grafika",
  "path_base": "request-directory",
  "scenes": [
    {
      "id": "03-akakiy-at-the-tailor",
      "title": "Акакий Акакиевич у Петровича",
      "order": 3,
      "caption": "Одна фраза для подписи в галерее.",
      "card": "scenes/03-akakiy-at-the-tailor.json",
      "card_sha256": "…",
      "prompt": "prompt/03-akakiy-at-the-tailor.txt",
      "prompt_sha256": "…",
      "builder_sha256": "…",
      "output": "../../../output/gogol-shinel--01-first-batch--03-akakiy-at-the-tailor.png",
      "output_sha256": "…",
      "inputs": [
        {"path": "input/ref-01.png", "sha256": "…", "role": "style-reference", "stored": true},
        {"path": "../characters/akakiy.png", "sha256": "…", "role": "character-reference", "stored": true}
      ]
    }
  ]
}
```

Роли входов: `style-reference`, `character-reference`, `edit-target`. Сборка проверяет хеши
всех файлов с `stored: true` и то, что результат лежит в корневом `output/`.

`builder_sha256` — хеш `scripts/build_prompt.py`, которым собран этот промпт. Отдельного
файла-шаблона нет: шаблон — это порядок секций в самом сборщике, поэтому его версией и
служит хеш модуля. Правка сборщика не объявляет прежние промпты неверными задним числом,
иначе закоммиченный промпт перестал бы быть тем, из которого получена картинка, — но по
хешу видно, что кадр собран другим кодом.

Манифест заполняет `scripts/register_result.py`: он пересобирает список входов тем же
кодом, что собирал промпт, копирует недостающее в `input/` и удаляет оттуда файлы, на
которые не ссылается ни одна сцена. Вручную манифест не правится — так в него уже
попадали входы, которых в промпте не было.

Схема остаётся второй: манифестов по прежней форме не существует, мигрировать нечего.
