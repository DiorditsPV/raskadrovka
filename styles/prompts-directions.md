# Промпты эталонов направлений

Промпты эталонов: каждый задаёт **манеру**, а не сюжет. Сцена в промпте выбрана так, чтобы
манера была показана на людях, месте и действии, потому что именно это генератор потом должен
уметь повторить.

Здесь три направления из четырёх. Эталоны `kinematograficheskiy-realizm` пришли извне —
владелец репозитория сгенерировал их в ChatGPT, — и промпта к ним нет. Направление
`tekhnicheskiy-razrez` было отсюда убрано: разрез оказался не манерой, а способом показать
предмет, и переехал в `compositions/` шаблоном `05-razrez-obekta`.

Промпты самодостаточны: **входных картинок не нужно**, манера целиком описана словами. Это и
есть смысл подхода — эталон не ищется в чужих работах, а выращивается.

Результат кладётся в `styles/refs/<направление>/ref-01.png`. Запись в
`styles/directions/<направление>.json`:
`stored: true`, `license: own-work`, `license_basis` — «собственная генерация владельца
репозитория; проект не считает сгенерированные изображения объектом исключительных прав
(RIGHTS.md)».

Если из одного промпта выйдет два-три удачных кадра — берите все: два-три эталона держат
манеру устойчивее одного. Больше пяти на направление не надо, иначе направление перестаёт быть
одним.

Общий хвост, дописывать к каждому:

```text
Asset: a single image, 3:2 landscape.
Avoid: photographic realism unless the style asks for it, likeness of actors or film
adaptations, other illustrators' recognisable compositions, signatures, watermarks, artist
marks, any legible text or lettering anywhere in the frame.
```

---

## 1. `tush-i-plashki` — Тушь с плашками цвета

Под фэнтези, приключения, нуар, тёмное фэнтези.

```text
Style: heavy black brush ink defining every form, colour applied as large flat unmodulated
areas with no blending or gradient, shadow rendered as a solid silhouette shape rather than
shading, high contrast, economical detail that reads at a distance, dry-brush breakup at the
edges of strokes, visible bristle texture. Limited palette: black plus three colours only.

Scene: a hooded figure stands at a heavy iron gate at night, holding a lantern up toward it.
Rain streaks across the frame. Behind the gate the courtyard is pure black. The lantern is the
only warm thing in the picture.
Composition: figure at the left third seen from slightly below, gate filling the right two
thirds, rain as diagonal white scratches over everything.
Palette: black, cold blue-grey, one warm ochre for the lantern light, muted brick red.
```

## 2. `akvarel-po-peru` — Прозрачная акварель по перу

Под классику, психологическую прозу, мемуары, камерную сцену.

```text
Style: light pen contour with transparent watercolour washes laid over it, generous areas of
untouched white paper, light rendered as reserved paper rather than added pigment, muted
desaturated palette, soft blooms where wet met wet, visible cockling of the sheet. No heavy
black, no hard edges, no opaque colour.

Scene: a woman stands at a window in a modest room in early morning, one hand on the frame,
looking out. A table behind her holds a cup and an open book. The room is almost empty; most of
the paper is left white.
Composition: figure at the right third in near-silhouette against the window, table in the
lower left, wide empty space between them.
Palette: pale grey-blue, warm sand, a single muted rose, and the white of the paper.
```

## 3. `maslo-epika` — Густое масло, атмосферная глубина

Под эпическое фэнтези, исторический роман, классику, приключения.

```text
Style: thick impasto oil with glazed transparent darks, vast sky occupying two thirds of the
frame, layered atmospheric perspective with visible air between planes, figures small against
landscape scale, romantic painting logic rather than concept art, visible canvas weave and
brush ridges catching the light.

Scene: four riders halt on a bare ridge as a storm builds ahead of them. The land falls away
into haze; a break in the cloud throws one shaft of light onto the distant valley floor. Wind
takes the horses' manes.
Composition: riders small on the ridge line in the lower third at the left, sky and storm
filling everything above, the lit valley far off at the right.
Palette: warm ochre and umber in the foreground, cold blue-violet in the distance, one shaft of
pale gold.
```

## Палитра

В каждом промпте выше палитра названа отдельной строкой — и именно её потом надо перенести в
`palette_en` направления. Без этого палитра остаётся только в эталонах: сцена её не просит,
и кадр уезжает в тот цвет, которым освещено место действия. Так четыре направления и сошлись
в один янтарь на чёрном — все сцены книги подземные и освещены рабочими лампами.

`palette_en` пишется по факту: тональный ключ (какая доля кадра в свету, какая в тени) и
названные цвета — измеренные по готовым эталонам направления, а не выдуманные.

## Что делать с результатом

1. Файл — в `styles/refs/<направление>/ref-01.png` (дальше `ref-02`, `ref-03`).
2. Запись в `styles/directions/<направление>.json`: это сделает `scripts/add_ref.py`
   (задача 4), пока — руками.
3. `python3 scripts/build_styles_page.py` — пересобрать `styles/index.html`.

Направление `kinematograficheskiy-realizm` закрыто отдельно — промпт для него не нужен.

Если какая-то манера выйдет мимо описания, правится **текст** `style_notes_en`, а не подбор
картинок: текст здесь первичен, картинка — его закрепление.
