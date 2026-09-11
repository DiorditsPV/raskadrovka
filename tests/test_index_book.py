"""Индекс имён: кто в книге есть. Проверяется не полнота, а отсутствие мусора.

Индекс — единственный источник имён для панели: героя, которого в нём нет, завести нельзя.
Поэтому у него две ошибки разной цены. Лишнее слово («Did», «Your», «Are») человек отбросит
глазами, но когда таких слов половина списка, список перестают читать целиком. Потерянное
имя дороже: героя просто не будет.

Главный признак имени — книга не пишет его со строчной. «Дэрроу» встречается 111 раз
с прописной и ни разу со строчной; «Did» — 27 раз с прописной (начало реплики) и 163 раза
со строчной. В книге ниже те же слова расставлены так, чтобы прежние проверки их пропускали:
`Did`, `Your` и `Are` встречаются по четыре раза и ни разу в начале предложения, — отсеять
их может только доля строчных.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import index_book                                            # noqa: E402


def book(text):
    """Книга из абзаца на строку: индексу нужны только `text` и `chapter`."""
    return [{'i': i, 'chapter': 1, 'text': line}
            for i, line in enumerate(text.strip().splitlines()) if line.strip()]


NOVEL = book('''
Darrow swings the drill and Barlow laughs at him over the comm.
The vein holds, Darrow says, and Barlow counts the load again.
He said, Did you see that. He said, Did the vein hold. She asked, Did anyone count the load.
He said again, Did the drill bite, and nobody answered him at all.
He said, Your father was a Helldiver. She said, Your hands are his hands, and Barlow agreed.
He said, Your load is light. She said, Your Laurel is lost, and Darrow said nothing.
He asked, Are you certain of the count. She asked, Are the numbers right, and Darrow shrugged.
He asked, Are we winning. She asked, Are we even trying, and Barlow laughed at that.
Uncle Narol did not answer, and Darrow watched Narol drink alone that night.
Then Uncle Narol slept, and Barlow left Uncle Narol where he lay, and Narol did not stir.
Mother came in with the broth, and Barlow greeted Mother by name that evening.
Then Mother said nothing, but Mother looked at Barlow and then at Narol.
The boy did as his mother asked, because his mother is his mother, and my mother is kin.
His mother had said it, your mother says it, and every mother in Lykos says it.
He did what your father did, and you are what your father was, and did it matter.
''')


def test_real_names_survive():
    """Имя книга пишет только с прописной — по этому его и узнают."""
    names = index_book.index_names(NOVEL)
    for word in ('Darrow', 'Barlow', 'Narol'):
        assert word in names, f'{word} потерян, а это имя'


def test_words_the_book_also_writes_in_lower_case_are_dropped():
    """«Did», «Your», «Are» стоят с прописной в начале реплики, а в середине фразы — со
    строчной. Прежние проверки их пропускали: в начале предложения они не стоят ни разу."""
    names = index_book.index_names(NOVEL)
    for word in ('Did', 'Your', 'Are'):
        assert word not in names, f'{word} остался в индексе, а это не имя'


def test_kinship_survives_although_it_is_a_common_word():
    """«Мать» статистикой неотличима от обычного слова — обычным словом она и является:
    семь строчных на четыре прописных. Но в книгах так зовут людей, и без этого имени
    героиню не завести: других имён у матери Дэрроу в книге нет."""
    assert 'Mother' in index_book.index_names(NOVEL)


def test_a_rare_name_is_kept_the_same_as_a_frequent_one():
    """Порог по доле строчных не зависит от того, часто ли имя встречается: у имени
    строчных нет вовсе, сколько бы раз оно ни попалось."""
    rare = book('''
The door opened and Kavax walked in. Nobody spoke to Kavax that evening.
The fire was low when Kavax sat down. They left Kavax there until morning.
''')
    assert 'Kavax' in index_book.index_names(rare)


def test_one_stray_lower_case_does_not_kill_a_name():
    """Смотрим долю, а не сам факт: у «Dancer» в книге есть и танцор со строчной."""
    text = book('''
The door swung and Dancer met us there. The boy watched Dancer smile at him.
The dancer in the corner kept playing for them all that evening.
They spoke of Ares, and then Dancer spoke of the Sons of Ares.
The room went quiet when Dancer stood up and looked at us.
''')
    assert 'Dancer' in index_book.index_names(text)
