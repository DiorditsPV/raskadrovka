"""Строит индекс книги целиком: кто в ней есть, где описан и какие абзацы просятся в кадр.

Зачем. Читать роман целиком дорогой моделью нельзя, а читать первые главы — неверно:
ключевые лица появляются по всей книге, и описание внешности часто даётся не при первом
упоминании, а при первом настоящем выходе героя. Поэтому проход по всему тексту делает
скрипт, без модели, а агент потом читает только окрестности найденного.

Что считает:
  characters  — имена собственные, ведущие себя как люди: частота, главы, первое упоминание
                и абзацы, где рядом с именем есть слова про внешность;
  places      — имена собственные после локативных предлогов;
  scenes      — окна абзацев, набравшие балл по визуальному лексикону.

Только стандартная библиотека.
"""
import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEXICON = ROOT / 'scripts' / 'lexicon'

WORD = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё'’-]+")
SENTENCE_START = re.compile(r'(?:^|[.!?…]["»)\]]?\s+)([A-ZА-ЯЁ][A-Za-zА-Яа-яЁё\'’-]+)')
CAPITALIZED = re.compile(r"\b([A-ZА-ЯЁ][A-Za-zА-Яа-яЁё'’-]{2,})")
SPEECH = re.compile(r'^\s*[—–-]|["“«]')
ARTICLE = re.compile(r'\b(?:the|a|an|this|that|these|those|his|her|their|my|our|your)\s+$', re.I)
CONTRACTION = re.compile(r"[’'](?:m|s|re|ve|ll|d|t)\b", re.I)
LOCATIVE = re.compile(r'\b(?:in|at|on|to|from|through|toward|towards|into|'
                      r'в|во|на|из|к|ко|у|под|над|за|через|до)\s+$', re.I)

# Слова, которые пишутся с прописной, но людьми не являются.
STOP = {
    'I', 'The', 'A', 'An', 'And', 'But', 'So', 'If', 'When', 'Then', 'That', 'This', 'There',
    'What', 'Who', 'Why', 'How', 'It', 'He', 'She', 'They', 'We', 'You', 'His', 'Her', 'My',
    'Mr', 'Mrs', 'Ms', 'Dr', 'Sir', 'Lord', 'Lady', 'God', 'Yes', 'No', 'Not', 'Now', 'Here',
    'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday',
    'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
    'September', 'October', 'November', 'December',
    'Я', 'Он', 'Она', 'Они', 'Мы', 'Вы', 'Ты', 'Это', 'Так', 'Но', 'И', 'А', 'Что', 'Как',
    'Когда', 'Если', 'Тогда', 'Там', 'Здесь', 'Да', 'Нет',
}

# Доля строчных, после которой слово перестаёт быть именем. У имени строчной формы
# в книге нет вовсе: «Дэрроу» — 111 раз с прописной и ни разу со строчной, «Томас» — 806
# и ни разу. У обычного слова наоборот: «Did» — 27 раз с прописной (начало реплики)
# и 163 раза со строчной. Настоящие имена лежат ниже 0.1, мусор — выше 0.3.
COMMON_SHARE = 0.30

# Исключение: родство и звание. Ими в книгах зовут людей — «Мать сказала», «Cardinal nodded», —
# и статистикой они неотличимы от обычных слов, потому что обычными словами и являются.
# Без этого списка из индекса пропадают «мать Дэрроу» и «дядя Нарол», а вместе с ними
# единственный способ их завести: имён, кроме индексных, панель не предлагает.
KINSHIP = {
    'mother', 'father', 'papa', 'mama', 'mom', 'dad', 'uncle', 'aunt', 'brother', 'sister',
    'son', 'daughter', 'grandmother', 'grandfather', 'granny', 'nurse', 'widow',
    'doctor', 'captain', 'priest', 'cardinal', 'pope', 'abbot', 'bishop', 'knight',
    'king', 'queen', 'prince', 'princess', 'master', 'mistress', 'sire', 'comte', 'baron',
    'madame', 'mademoiselle', 'monsieur', 'signor', 'senor',
    'мать', 'отец', 'папа', 'мама', 'дядя', 'тётя', 'тетя', 'брат', 'сестра', 'сын', 'дочь',
    'бабушка', 'дедушка', 'нянька', 'вдова', 'доктор', 'капитан', 'священник', 'батюшка',
    'матушка', 'князь', 'граф', 'барон', 'король', 'королева', 'барин', 'госпожа', 'сударь',
}

# Слова, по которым узнаётся описание внешности. Дополняется без опаски: лишнее слово
# добавит кандидата, которого агент отбросит, а недостающее — спрячет описание.
APPEARANCE = {
    'hair', 'eyes', 'eye', 'face', 'skin', 'beard', 'scar', 'scars', 'hands', 'jaw', 'brow',
    'lips', 'mouth', 'nose', 'cheek', 'cheekbones', 'shoulders', 'tall', 'short', 'thin',
    'lean', 'slim', 'stout', 'fat', 'heavy', 'slender', 'wiry', 'freckles', 'freckled',
    'pale', 'dark', 'wore', 'wears', 'wearing', 'dressed', 'coat', 'cloak', 'boots', 'gloves',
    'uniform', 'armour', 'armor', 'suit', 'dress', 'skirt', 'blouse', 'shirt', 'ring',
    'tattoo', 'sigil', 'sigils', 'braid', 'bald', 'grey', 'gray', 'blond', 'red-haired',
    'волосы', 'глаза', 'лицо', 'кожа', 'борода', 'шрам', 'руки', 'плечи', 'высокий',
    'низкий', 'худой', 'полный', 'бледный', 'тёмный', 'одет', 'одета', 'носил', 'носила',
    'шинель', 'плащ', 'сапоги', 'перчатки', 'мундир', 'платье', 'кольцо', 'седой', 'рыжий',
}


def load_lexicon(name):
    path = LEXICON / name
    if not path.is_file():
        return set()
    return {w.strip().lower() for w in path.read_text(encoding='utf-8').splitlines()
            if w.strip() and not w.startswith('#')}


def load_paragraphs(slug, root=ROOT):
    cache = root / 'cache' / slug / 'paragraphs.jsonl'
    if not cache.is_file():
        raise SystemExit(f'нет кеша: {cache} — сначала ingest_book.py')
    # Пустые строки пропускаются: у книги без единого абзаца кеш состоит из одного
    # перевода строки, и разбор такого файла падал бы разбором JSON, а не понятным словом.
    return [json.loads(line) for line in cache.read_text(encoding='utf-8').splitlines()
            if line.strip()]


def proper_nouns(text):
    """Прописные слова, стоящие не в начале предложения: так отсеиваются обычные слова."""
    starts = set(SENTENCE_START.findall(' ' + text))
    found = []
    for m in CAPITALIZED.finditer(text):
        word = m.group(1)
        if CONTRACTION.search(word):
            continue                       # I'm, don't — это не имена
        word = re.sub(r"[’']s$", '', word)  # притяжательное к тому же лицу
        if word in STOP or len(word) < 3:
            continue
        prefix = text[:m.start()]
        found.append((word, bool(LOCATIVE.search(prefix)), bool(ARTICLE.search(prefix)),
                      word in starts and prefix.rstrip().endswith(('.', '!', '?', '"', '”'))
                      or not prefix.strip()))
    return found


LOWERCASE = re.compile(r"(?<![\w’'-])([a-zа-яё][A-Za-zА-Яа-яЁё'’-]{2,})")


def index_names(paragraphs, min_mentions=4):
    counts, chapters, first = Counter(), defaultdict(set), {}
    locative, articled, sentence_start, lower = Counter(), Counter(), Counter(), Counter()
    for p in paragraphs:
        lower.update(LOWERCASE.findall(p['text']))
        for word, after_locative, after_article, at_start in proper_nouns(p['text']):
            counts[word] += 1
            if at_start:
                sentence_start[word] += 1
            chapters[word].add(p['chapter'])
            first.setdefault(word, p['i'])
            if after_locative:
                locative[word] += 1
            if after_article:
                articled[word] += 1
    names = {}
    for word, n in counts.items():
        if n < min_mentions:
            continue
        # Слово, которое почти всегда стоит первым в предложении, — не имя, а «Well»,
        # «Because», «Something». Имя встречается и в середине фразы.
        if n - sentence_start[word] < max(2, n * 0.25):
            continue
        # Главная проверка: пишет ли книга это слово со строчной. Прописную даёт и начало
        # предложения, и начало реплики — «„Did you…“», — а строчную даёт только то, что
        # словом и является. Родство и звание из проверки выведены: ими зовут людей.
        low = lower[word.lower()]
        if low and low / (low + n) >= COMMON_SHARE and word.lower() not in KINSHIP:
            continue
        # Имя человека почти не идёт после артикля: «the House» — вещь, «Cassius» — человек.
        if articled[word] >= n * 0.25:
            kind = 'thing'
        elif locative[word] >= max(2, n * 0.4):
            kind = 'place'
        else:
            kind = 'person'
        names[word] = {'mentions': n, 'kind': kind, 'chapters': sorted(chapters[word]),
                       'first_paragraph': first[word]}
    return names


def appearance_hits(paragraphs, name, limit=12):
    """Абзацы, где имя стоит рядом со словами про внешность, — там ищут описание."""
    hits = []
    for p in paragraphs:
        text = p['text']
        if name not in text:
            continue
        words = {w.lower() for w in WORD.findall(text)}
        score = len(words & APPEARANCE)
        if score:
            hits.append({'i': p['i'], 'chapter': p['chapter'], 'score': score,
                         'preview': text[:160]})
    hits.sort(key=lambda h: (-h['score'], h['i']))
    return hits[:limit]


def score_paragraph(text, lexicon):
    words = WORD.findall(text)
    if not words:
        return 0.0
    lowered = [w.lower() for w in words]
    score = sum(1 for w in lowered if w in lexicon)
    score -= 1.5 * len(SPEECH.findall(text))
    if len(text) < 200:
        score -= 1
    return score / math.sqrt(len(words))


def scene_candidates(paragraphs, lexicon, per_chapter=3, window=2, total=None):
    by_chapter = defaultdict(list)
    for p in paragraphs:
        by_chapter[p['chapter']].append(p)
    out = []
    for chapter, items in sorted(by_chapter.items()):
        scores = [score_paragraph(p['text'], lexicon) for p in items]
        windows = []
        for i in range(len(items) - window + 1):
            windows.append((sum(scores[i:i + window]), i))
        windows.sort(reverse=True)
        taken = []
        for value, i in windows:
            if len(taken) >= per_chapter:
                break
            if any(abs(i - j) < window for j in taken):
                continue                    # окна не должны пересекаться
            taken.append(i)
            out.append({'chapter': chapter,
                        'paragraphs': [items[i]['i'], items[i + window - 1]['i']],
                        'score': round(value, 3),
                        'preview': items[i]['text'][:140]})
    out.sort(key=lambda c: (-c['score']))
    if total:
        out = out[:total]
    out.sort(key=lambda c: (c['chapter'], -c['score']))
    return out


TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 'ж': 'zh',
    'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o',
    'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'ts',
    'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu',
    'я': 'ya',
}


def key_for(name):
    """Ключ записи по имени из книги: латиница, нижний регистр, слова через подчёркивание.

    Ключ — имя файла и путь к листу, поэтому кириллицы в нём быть не должно. Имя, каким
    его зовёт книга, живёт в самой записи и в отметках панели, а не в ключе.
    """
    out = []
    for letter in (name or '').strip().lower():
        if letter in TRANSLIT:
            out.append(TRANSLIT[letter])
        elif letter.isalnum() and letter.isascii():
            out.append(letter)
        elif out and out[-1] != '_':
            out.append('_')
    return ''.join(out).strip('_') or 'geroy'


def build(slug, root=ROOT, per_chapter=3, window=2, total=None, min_mentions=4):
    paragraphs = load_paragraphs(slug, root)
    lexicon = load_lexicon('visual_en.txt') | load_lexicon('visual_ru.txt')
    names = index_names(paragraphs, min_mentions)
    people = {n: v for n, v in names.items() if v['kind'] == 'person'}
    for name, entry in people.items():
        entry['appearance'] = appearance_hits(paragraphs, name)
    index = {
        'slug': slug,
        'paragraphs': len(paragraphs),
        'characters': dict(sorted(people.items(), key=lambda kv: -kv[1]['mentions'])),
        'places': dict(sorted(((n, v) for n, v in names.items() if v['kind'] == 'place'),
                              key=lambda kv: -kv[1]['mentions'])),
        'scenes': scene_candidates(paragraphs, lexicon, per_chapter, window, total),
    }
    out = root / 'cache' / slug / 'index.json'
    out.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return index


def main(argv=None):
    ap = argparse.ArgumentParser(description='Индекс книги: лица, места, кандидаты в сцены')
    ap.add_argument('slug')
    ap.add_argument('--per-chapter', type=int, default=3)
    ap.add_argument('--window', type=int, default=2)
    ap.add_argument('--total', type=int, help='оставить только N лучших окон по всей книге')
    ap.add_argument('--min-mentions', type=int, default=4)
    ap.add_argument('--top', type=int, default=15, help='сколько строк печатать')
    args = ap.parse_args(argv)

    index = build(args.slug, per_chapter=args.per_chapter, window=args.window,
                  total=args.total, min_mentions=args.min_mentions)
    print(f"{args.slug}: абзацев {index['paragraphs']}, "
          f"лиц {len(index['characters'])}, мест {len(index['places'])}, "
          f"кандидатов в сцены {len(index['scenes'])}\n")
    print('ЛИЦА (упоминаний · глав · первое · абзацев с внешностью)')
    for name, e in list(index['characters'].items())[:args.top]:
        print(f"  {name:<20} {e['mentions']:>4}  {len(e['chapters']):>3}  "
              f"{e['first_paragraph']:>5}  {len(e['appearance']):>3}")
    print('\nМЕСТА')
    for name, e in list(index['places'].items())[:args.top]:
        print(f"  {name:<20} {e['mentions']:>4}  глав {len(e['chapters'])}")
    print(f"\nиндекс: cache/{args.slug}/index.json")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
