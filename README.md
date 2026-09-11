# Raskadrovka — book scenes drawn to a style reference

*English · [Русский](README.ru.md)*

A book goes to an agent, the agent cuts it into the scenes worth drawing, each scene is
described by a card, and the card together with style references becomes the prompt for an
image. The result is a series of illustrations for one book in one manner, with the full
history kept: which scene, which prompt, which references, which result.

The project grew out of [Okrestnosti](https://github.com/DiorditsPV/okrestnosti), a series
of posters about Moscow districts. All of the machinery comes from there: how a batch is
laid out, the manifest with hashes, the roles references play in a prompt, the gallery with
its checks, and the rules for the agent.

<table>
<tr>
<td width="50%"><img src="docs/screens/scene-realism.jpg" alt="A Helldiver at the drill face, cinematic realism"></td>
<td width="50%"><img src="docs/screens/scene-ink.jpg" alt="Ugly Dan flicks a pebble, ink and flat colour"></td>
</tr>
<tr>
<td><em>One book, two style directions: the same series machinery, a different manner.</em></td>
<td><em>Frames carry the scene card; the manner comes from the direction.</em></td>
</tr>
</table>

## How it works

1. **Intake.** An FB2, EPUB or TXT file is split into chapters and paragraphs. The file
   itself stays in a local, git-ignored folder; only `book.json` enters the repository —
   author, edition, rights status, file hash, table of contents and paragraph hashes.
2. **Cutting into scenes.** The agent reads the book and writes scene cards. For long books,
   where reading everything is expensive, a cheap script first picks candidates by heuristics
   — descriptiveness, a change of place, light and colour, little dialogue — and the agent
   looks only at their surroundings.
3. **The bible and character sheets.** Once per book, the appearance of the characters and
   the look of the places are collected with locators into the text, and a reference sheet is
   generated for every character. The sheet is mixed into every prompt so that the character
   is the same person across ten pictures: a description in words does not hold that.
4. **Style direction.** The manner comes from `styles/<direction>/` — a folder where the
   manner is described in words and backed by freely licensed references. A batch takes its
   own snapshot of the direction, so the provenance of each series is self-contained.
5. **The prompt.** Assembled deterministically from the card, the bible, the sheets and the
   reference records, and committed in full. References set the palette and the drawing;
   the sheet sets the character's face; the card sets what is in the frame.
6. **Generation and gallery.** A built-in image tool, one call per scene, corrections through
   an edit target. The result is registered in the manifest, the checker verifies rights and
   hashes, the gallery is rebuilt.

![A character reference sheet: three views of the same person](docs/screens/sheet-darrow.jpg)

*A character sheet is drawn once per character, from the record, with no manner and no scene —
three views and visible hands. It is mixed into every frame prompt so that the character is
the same person across ten pictures: a description in words does not hold that.*

## Rights

**This repository is public, and its design accounts for that.** It holds four books, all of
them in copyright: what goes into git is the manifest without text, paragraph hashes,
appearance descriptions in the book's own words with locators, and character sheets generated
here. The quoting limits are set as constants and verified by `scripts/check_rights.py` —
they are not kept in anyone's head.

The text of a book is never stored in the repository. A scene card may carry an excerpt of
no more than two paragraphs — whole paragraphs, with author, translator and edition named;
for public-domain books the limit is lifted. That the excerpt matches the paragraphs of its
locator is verified against paragraph hashes, so the check works on any copy, not only on the
author's machine. Style references are committed only under a free licence with the freedom
justified in both Russia and the United States; the rest live locally and are referred to by
hash. Details are in [RIGHTS.md](RIGHTS.md) (in Russian).

## Layout

```text
index.html                      gallery
output/<book>--<batch>--<scene>.png
scripts/
  ingest_book.py                FB2/EPUB/TXT -> book.json without the text; metadata from the file
  index_book.py                 mechanical index over the whole book: names, places, scenes
  show_paragraphs.py            print the paragraphs you need from the local cache
  build_prompt.py               scene prompt from card, style, template and sheets
  generate_sheet.py             character sheet: prompt from the record, image by Codex
  generate_scene.py             scene frame: prompt, image, entry in the manifest
  register_result.py            hashes, snapshot of input/, batch refs.json
  check_rights.py               rights: the book, quoting, reference licences
  build_gallery.py              build and verify index.html
  build_styles_page.py          build styles/index.html
styles/
  directions/<direction>.json   the manner in words, the palette, records about references
  refs/<direction>/             manner references
  prompts-directions.md         the prompts the references were generated with
  index.html                    direction picker
compositions/
  templates/<template>.json     where the bodies stand and where the camera is
  refs/<template>.png           grey blocking
books/<book>/
  book.json                     book manifest without the text
  bible.json                    characters and places
  characters/<key>.png          character sheets
  characters/history/           earlier sheets: what was replaced and what was rejected
  source/                       the book file — local, never committed
  <batch>/
    README.md                   what is in the batch and links to results
    scenes/<scene>.json         scene cards
    prompt/<scene>.txt          exact prompts
    input/                      batch references; input/<scene>/ is a frame's edit target
    metadata/request.json       batch manifest: scenes, hashes, roles of inputs
    metadata/refs.json          sources and licences of references
```

## Control panel

The same path without a terminal:

```bash
python3 panel/server.py --port 8770 --open
```

![The Characters screen: records, the understanding audit, buttons for every step](docs/screens/characters.png)

*Left: the steps a book goes through, the books themselves, the operator and how many jobs run
at once. Middle: one character — the accepted sheet, ten traits as a strip, what the book does
not give, and the buttons that move the work on. Right: the job queue with timings and logs.*

A local window into the repository: the whole path from a book file to a frame. Books and
their progress, character records with the understanding audit and the result of the checks,
batches, style directions with their references, the job queue with logs. The panel stores
nothing of its own — its state is those same files, and a step taken by hand in the terminal
is one it will see.

Steps that need judgement go to an **operator** — Codex or Claude, chosen in the sidebar —
and the panel checks the result itself. There is one difference between them and it is named
out loud: `codex exec` writes only inside the working directory, while
`claude -p --permission-mode bypassPermissions` is not constrained at all. Drawing is not a
choice: `image_gen` exists only in Codex.

Selection stays with the human: which characters are needed, which sheet to accept, which
scenes to draw.

What the panel does on its own:

- **reads what the book knows about itself** — title, author, translator, year and edition
  come from the fb2 or epub, the slug is built from the title; only rights stay with you;
- **collects a character record** in the book's own words, with paragraph locators and an
  understanding audit of ten traits;
- **runs a second pass on appearance** over the thin traits: a direct description scores a
  trait 1, a trait of the caste or trade the book explicitly assigns scores 0.5, and the
  book's silence is written down as a gap and never asked about again. The gap goes into the
  sheet prompt as a section of its own — "keep it ordinary" instead of something invented;
- **draws the sheet and the frame** and puts them up for your verdict: the judge of content
  is a human, not a check;
- **keeps earlier sheets**: neither accepting nor rejecting erases anything, and any variant
  can be brought back;
- **runs several jobs side by side** — as many as the setting allows, and only those that do
  not touch the same file: records of one book go one by one, sheets and different books run
  at the same time.

![The open record: ten traits by name and the exact prompt the generator receives](docs/screens/record.png)

*“What is in the record”, opened. Ten traits named with their scores; the description in the
book’s own words; and below it the exact text that goes to the generator — including the
`Unspecified` section built from the gaps, which tells the generator to keep the unsaid
ordinary instead of inventing it. The Russian paragraph is the book’s data: only the interface
is translated.*

The interface is bilingual, Russian and English, with the switch in the sidebar. Only what
the panel itself wrote is translated: character names, descriptions and the agent's own text
stay as they are, because that is the book's data.

The design and the screens are described in the
[panel specification](docs/superpowers/specs/2026-09-09-panel-design.md) (in Russian).

## What you need to run it

- **Python 3.10+.** The scripts and the panel use the standard library only; there is
  nothing to install.
- **Your own book file** — fb2, epub or txt. There are no books in this repository and there
  never will be: what lands here is the manifest, paragraph hashes and character records,
  while the text itself sits in the git-ignored `books/<book>/source/`. Anyone holding their
  own copy of the book can reproduce the layout from this repository.
- **An operator** for the steps that need judgement — at least one of the two, configured
  and signed in: [Codex CLI](https://github.com/openai/codex) (`codex exec`) or
  [Claude Code](https://github.com/anthropics/claude-code) (`claude -p`). The panel calls
  them itself; the command can be changed in `cache/panel/settings.json`.
- **Images are drawn by Codex**: only it has an image generation tool. Without Codex
  everything works except character sheets and frames.
- `pytest` is needed for the tests only. One test parses the panel script through
  `node --check` and is skipped when node is not installed.

Money and rate limits are spent by the operator, not by the panel: a character record is
7–16 minutes of Codex or Claude, a character sheet 2–4 minutes. How many jobs run side by
side is visible and changeable in the panel's sidebar.

## Running the scripts

```bash
python3 scripts/register_result.py books/<book>/<batch>   # hashes, input/, refs.json
python3 scripts/check_rights.py                           # rights
python3 scripts/build_gallery.py                          # rebuild index.html
python3 scripts/build_styles_page.py                      # rebuild styles/index.html
pytest tests/                                             # every check in the project
```

The order is not accidental: registration records what the frames were made from, the rights
check reads what was recorded, and the gallery build verifies the hashes and fails if a
picture was drawn from a card that no longer exists.

## Kinship with Okrestnosti

There the input is a photograph of a place, here it is the text of a scene; the role of the
style reference is the same. The Moscow posters stayed in the parent project; here the
collections are books.
