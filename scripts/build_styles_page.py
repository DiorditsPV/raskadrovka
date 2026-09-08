"""Собирает styles/index.html — страницу выбора направления стиля. Только стандартная библиотека.

Читает описания манер из styles/directions/<направление>.json и показывает эталоны сеткой.
Картинки лежат под styles/refs/<направление>/, отдельно от описаний манер.
Страница открывается локально, ничего не встраивает и никуда не ходит.
"""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLES = ROOT / 'styles'
ESC = html.escape

STYLE = (
    ':root{color-scheme:dark;background:#181a19;color:#eeeae1;'
    'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}'
    '*{box-sizing:border-box}body{margin:0}'
    'header,main,footer{max-width:1500px;margin:auto;padding:32px}header{padding-top:56px}'
    'h1{font-size:clamp(30px,4vw,52px);font-weight:550;letter-spacing:-.035em;margin:0 0 14px}'
    'p{line-height:1.6;color:#b8bbb4}header p{max-width:70ch}'
    '.eyebrow{letter-spacing:.13em;font-size:12px;text-transform:uppercase;color:#cabea3;margin-bottom:14px}'
    'section{margin-bottom:56px;scroll-margin-top:24px;border-top:1px solid #353b35;padding-top:28px}'
    '.head{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:6px}'
    'h2{font-size:27px;font-weight:550;margin:0;letter-spacing:-.01em}'
    '.slug{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;color:#8a7c5e}'
    '.about{max-width:72ch;margin:0 0 10px}'
    '.fits{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 8px;padding:0;list-style:none}'
    '.fits li{font-size:12px;color:#cabea3;border:1px solid #3f463e;padding:2px 9px}'
    '.notes{font-size:13.5px;color:#8f958c;max-width:80ch;margin:0 0 8px;'
    'font-family:ui-monospace,SFMono-Regular,Menlo,monospace;line-height:1.55}'
    '.palette{color:#a8a08c;border-left:2px solid #3f463e;padding-left:12px;margin-bottom:20px}'
    '.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:20px}'
    'figure{margin:0;min-width:0}'
    'figure a{display:block;background:#252826;line-height:0}'
    'img{display:block;width:100%;height:auto}'
    'figcaption{font-size:12px;color:#8f958c;line-height:1.5;padding:8px 2px 0}'
    'figcaption b{color:#b8bbb4;font-weight:500}'
    'a{color:#e1c99a;text-underline-offset:3px}a:hover{color:#fff}'
    'a:focus-visible{outline:2px solid #e1c99a;outline-offset:4px}'
    'nav{display:flex;gap:12px 20px;flex-wrap:wrap;margin:16px 0 0}'
    'footer{border-top:1px solid #353b35;color:#969d94;font-size:13.5px;line-height:1.7}'
    '@media(max-width:700px){header,main,footer{padding-left:18px;padding-right:18px}}'
)


def load():
    out = []
    for file in sorted((STYLES / 'directions').glob('*.json')):
        out.append(json.loads(file.read_text()))
    return out


def figure(style, ref_id, ref):
    path = ref['file']          # уже относительно styles/
    author = ref.get('author') or '—'
    return (
        f'<figure><a href="{ESC(path)}"><img src="{ESC(path)}" loading="lazy" '
        f'alt="{ESC(style["name"])} — {ESC(ref_id)}"></a>'
        f'<figcaption><b>{ESC(author)}</b><br>{ESC(ref.get("license", "?"))} · '
        f'<a href="{ESC(ref.get("source", ""))}">источник</a></figcaption></figure>'
    )


def section(style):
    refs = ''.join(figure(style, rid, ref) for rid, ref in sorted(style.get('refs', {}).items()))
    fits = ''.join(f'<li>{ESC(f)}</li>' for f in style.get('fits', []))
    return (
        f'<section id="{ESC(style["slug"])}">'
        f'<div class="head"><h2>{ESC(style["name"])}</h2>'
        f'<span class="slug">{ESC(style["slug"])} · {len(style.get("refs", {}))} референса</span></div>'
        f'<p class="about">{ESC(style.get("about", ""))}</p>'
        f'<ul class="fits">{fits}</ul>'
        f'<p class="notes">{ESC(style.get("style_notes_en", ""))}</p>'
        f'<p class="notes palette">{ESC(style.get("palette_en", ""))}</p>'
        f'<div class="grid">{refs}</div></section>'
    )


def main(argv=None):
    styles = load()
    if not styles:
        print('Направлений нет: styles/directions/<направление>.json не найдено.')
        return 1
    total = sum(len(s.get('refs', {})) for s in styles)
    menu = ''.join(f'<a href="#{ESC(s["slug"])}">{ESC(s["name"])}</a>' for s in styles)
    page = (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>Раскадровка — направления стиля</title><style>{STYLE}</style></head><body>'
        '<header><div class="eyebrow">Раскадровка</div><h1>Направления стиля</h1>'
        f'<p>{len(styles)} направлений, {total} референса. Манера серии берётся отсюда: партия '
        'выбирает направление, снимает с него копию референсов и подмешивает '
        '<code>style_notes_en</code> и <code>palette_en</code> в каждый промпт. Моноширинным набран '
        'текст, который уходит в промпт дословно: сначала манера, следом тональный ключ и '
        'палитра.</p>'
        f'<nav>{menu}</nav></header><main>' + ''.join(section(s) for s in styles) +
        '</main><footer>Эталоны сгенерированы в этом проекте; описания манер — в '
        '<code>styles/directions/</code>, картинки — в <code>styles/refs/</code>. '
        'Правила по референсам — в <a href="../RIGHTS.md">RIGHTS.md</a>, контракт направления — в '
        '<a href="README.md">styles/README.md</a>.</footer></body></html>'
    )
    (STYLES / 'index.html').write_text(page)
    print(f'Страница направлений собрана: {len(styles)} направлений, {total} референса.')
    for s in styles:
        licenses = sorted({r.get('license', '?') for r in s.get('refs', {}).values()})
        print(f'  {s["slug"]:<28} {len(s.get("refs", {}))} × {", ".join(licenses)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
