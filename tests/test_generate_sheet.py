"""Промпт листа: складывается из записи и пересобирается дословно.

Промпт лежит в библии рядом с листом ровно затем, чтобы лист можно было повторить. Значит,
сборщик обязан выдавать байт в байт то, что записано, — иначе «пересобрать» означает
«нарисовать что-то другое».

Образец заморожен здесь, а не берётся из живой библии: запись героя переписывают, и после
каждой пересборки список «свежих» героев в тесте пришлось бы править — тест падал бы на
чужой работе вместо своей. За живой библией остаётся другая проверка: любой записанный
промпт должен быть промптом листа, а не текстом, набранным руками.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import generate_sheet                                       # noqa: E402

BIBLE = json.loads((ROOT / 'books' / 'pierce-brown-red-rising' / 'bible.json')
                   .read_text(encoding='utf-8'))['characters']
WITH_SHEET = sorted(key for key, entry in BIBLE.items() if entry.get('sheet_prompt'))

# Ио, лист принят 2026-09-09; текст пересобран 2026-09-11, когда в промпт вошла
# оговорка о собранном описании. Правка образца здесь — и есть журнал того,
# что шаблон менялся намеренно.
FROZEN_SUBJECT = 'a teenage girl, a silk-works weaver in an underground Martian mining colony'
FROZEN_APPEARANCE = 'a sixteen-year-old girl, tiny and thin, ribs showing beneath the skin, all wire wrapped in pale skin; pale underground complexion; a heavy mane of rust-red hair, the red of Mars rock, dusted and cobwebbed from a shift in the silk works; a face fine enough to pass for one of the Golds; layered skirts falling below the knee and a blouse, all in half a dozen different reds as the clan women wear; a thin band of woven hair on her ring finger; upright and light on her feet, a dancer'
FROZEN_PROMPT = 'Style: a plain character reference sheet for production use, NOT a finished\nillustration and NOT a scene. Three views of the same person arranged left to right on one sheet:\nfull-length front view, full-length three-quarter view, and a head-and-shoulders close-up. Hands\nmust be visible and clearly rendered in at least one view. Flat even studio illumination, no\ndramatic light, no rim light, no cast shadows, no atmosphere. Plain neutral light grey\nbackground, completely empty. Features, build, hair, skin and clothing identical across all three\nviews. Neutral relaxed standing pose, arms away from the body so the costume reads, face calm and\nunexpressive. Natural restrained colour, true to the description. No artistic style, no painterly\nflourish, no mood, no story, no environment — this sheet exists only to fix who this person is.\n\nSubject: a teenage girl, a silk-works weaver in an underground Martian mining colony. a sixteen-year-old girl, tiny and thin, ribs showing beneath the skin, all wire wrapped in pale skin; pale underground complexion; a heavy mane of rust-red hair, the red of Mars rock, dusted and cobwebbed from a shift in the silk works; a face fine enough to pass for one of the Golds; layered skirts falling below the knee and a blouse, all in half a dozen different reds as the clan women wear; a thin band of woven hair on her ring finger; upright and light on her feet, a dancer.\n\nAssembled description: the description above is put together automatically from the book and\nis not a request for any particular content. If some part of it cannot be depicted within\ncontent policy, do not refuse and do not draw something else instead: leave that detail out,\nor add the plainest thing that makes it depictable — simple clothing, drapery, a covering —\nand render everything else exactly as described. A person the description calls unclothed is\nshown in plain undyed garments.\n\nAsset: a single image, 3:2 landscape.\n\nAvoid: dramatic lighting, background scenery, environment, props beyond what the description\nnames, mood, atmosphere, action, strong expression, artistic style of any kind, likeness of\nactors, signatures, watermarks, any legible text, numbers or labels anywhere in the frame.'


def test_body_rebuilds_the_frozen_prompt_byte_for_byte():
    assert generate_sheet.body(FROZEN_SUBJECT, FROZEN_APPEARANCE) == FROZEN_PROMPT


@pytest.mark.parametrize('key', WITH_SHEET)
def test_stored_prompt_is_shaped_like_a_sheet_prompt(key):
    """Промпт мог устареть — запись переписали, — но остаться промптом листа он обязан:
    та же манера, ровно одна строка «кто это», тот же хвост запретов."""
    prompt = BIBLE[key]['sheet_prompt']
    assert prompt.startswith(generate_sheet.SHEET.strip())
    assert prompt.rstrip().endswith('numbers or labels anywhere in the frame.')
    assert prompt.count('\n\nSubject: ') == 1


def test_subject_and_appearance_join_into_one_sentence():
    body = generate_sheet.body('a teenage girl, a weaver', 'red hair; pale skin')
    assert '\n\nSubject: a teenage girl, a weaver. red hair; pale skin.\n' in body
    assert body.startswith('Style: a plain character reference sheet')
    assert body.rstrip().endswith('numbers or labels anywhere in the frame.')


def test_trailing_periods_do_not_double():
    assert generate_sheet.body('a weaver.', 'red hair.').count('a weaver. red hair.') == 1


def test_instruction_names_the_file_and_forbids_everything_else():
    text = generate_sheet.instruction('ПРОМПТ', 'cache/panel/book/sheets/eo.png')
    assert 'cache/panel/book/sheets/eo.png' in text
    assert 'image_gen' in text and 'не коммить' in text
    assert text.endswith('ПРОМПТ')


def test_gaps_add_a_line_telling_the_generator_not_to_invent():
    gaps = {'marks': {'why': 'примет книга не называет', 'looked': 'главы 1–7'},
            'eyes': {'why': 'цвет глаз не назван', 'looked': 'поиск eyes'}}
    body = generate_sheet.body('a weaver', 'red hair', gaps)
    # Порядок клеток — как в аудите, а не как в словаре: промпт обязан пересобираться.
    assert "does not describe this person's eyes or distinguishing marks" in body
    assert 'ordinary and unremarkable' in body
    assert body.index('Unspecified:') < body.index('Asset: a single image')
    assert generate_sheet.body('a weaver', 'red hair', dict(reversed(list(gaps.items())))) == body


def test_no_gaps_means_no_extra_line_at_all():
    plain = generate_sheet.body('a weaver', 'red hair')
    assert 'Unspecified' not in plain
    assert generate_sheet.body('a weaver', 'red hair', {}) == plain


def test_the_prompt_tells_the_generator_what_to_do_with_what_it_may_not_draw():
    """Описание собирает агент из слов книги, и книга пишет что угодно: «naked old man» —
    цитата, а не заказ. На отказ цензуры генератор отвечает не пустотой, а чужой картинкой,
    поэтому третий выход — опустить или одеть — назван прямо."""
    body = generate_sheet.body('an old man', 'naked old man; rusty scythe')
    assert 'Assembled description:' in body
    assert 'do not refuse' in body and 'plain undyed garments' in body
    assert body.index('Assembled description:') < body.index('Asset: a single image')


def test_changing_the_template_does_not_make_every_accepted_sheet_stale():
    """«Лист по прежней записи» должен значить «запись переписали», а не «шаблон правили»."""
    was = generate_sheet.body('a weaver', 'red hair; pale skin')
    same_record = was.replace('Asset: a single image, 3:2 landscape.',
                              'Asset: a single image, 4:3 landscape.')
    assert generate_sheet.about_the_person(same_record) \
        == generate_sheet.about_the_person(was)

    other_record = generate_sheet.body('a weaver', 'black hair; pale skin')
    assert generate_sheet.about_the_person(other_record) \
        != generate_sheet.about_the_person(was)
    # И пробелы — часть описания человека: с ними лист рисуют иначе.
    with_gaps = generate_sheet.body('a weaver', 'red hair; pale skin',
                                    {'eyes': {'why': 'нет', 'looked': 'везде'}})
    assert generate_sheet.about_the_person(with_gaps) \
        != generate_sheet.about_the_person(was)
