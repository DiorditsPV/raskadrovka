# Промпты эталонов направлений

Пять промптов — по одному на направление стиля. Каждый задаёт **манеру**, а не сюжет: сцена в
промпте выбрана так, чтобы манера была показана на людях, месте и действии, потому что именно
это генератор потом должен уметь повторить.

Промпты самодостаточны: **входных картинок не нужно**, манера целиком описана словами. Это и
есть смысл подхода — эталон не ищется в чужих работах, а выращивается.

Результат кладётся в `styles/<направление>/refs/ref-01.<ext>`. Запись в `style.json`:
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

## 2. `guash-plakat` — Гуашь, плакатная плоскость

Под антиутопию, социальную фантастику, ретро-НФ, производственный роман.

```text
Style: opaque matte gouache, flatness instead of volume, figures and machinery simplified to
geometric masses, palette cut to five mixed colours, poster logic with strong shape hierarchy,
visible paper tooth, no gloss, no photographic depth of field, no lens effects. Retro-futurist
restraint: everything drawn, nothing rendered.

Scene: three workers in identical overalls stand on a narrow steel gantry high above an
enormous machine hall. Turbines recede in rows below them. One worker points down; the others
watch. Overhead lamps hang in a regular grid.
Composition: gantry crossing the frame horizontally in the upper third, the hall opening
beneath it, figures small and read as silhouettes against the lit depth.
Palette: dusty teal, oxide orange, warm grey, cream, near-black.
```

## 3. `akvarel-po-peru` — Прозрачная акварель по перу

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

## 4. `maslo-epika` — Густое масло, атмосферная глубина

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

## 5. `tekhnicheskiy-razrez` — Технический разрез

Под твёрдую НФ, научную фантастику, производственный роман.

```text
Style: engineering cutaway presentation, the machine opened along one plane to show its
internal structure, precise ruled line work over restrained flat colour, even shadowless
illumination with no dramatic light, human figures included purely for scale, muted blueprint
palette. Callout marks appear as illegible tick strokes and short rules only — never as
readable words or numbers.

Scene: a cylindrical spacecraft habitat module cut open lengthwise. Decks, tanks, ducting and
stowage are visible inside. Two crew members work at a console on the middle deck, drawn small
and plainly, to give the scale of the structure.
Composition: module lying across the frame horizontally, cut face toward the viewer, thin
leader lines running out to the margins.
Palette: slate blue, cream, oxide red, warm grey; no saturated accents.
```

---

## Что делать с результатом

1. Файл — в `styles/<направление>/refs/ref-01.<ext>` (второй и третий — `ref-02`, `ref-03`).
2. Запись в `style.json`: это сделает `scripts/add_ref.py` (задача 4), пока — руками.
3. `python3 scripts/build_styles_page.py` — пересобрать `styles/index.html`.

Шестое направление, `kinematograficheskiy-realizm`, уже закрыто вашими тремя генерациями —
промпт для него не нужен.

Если какая-то манера выйдет мимо описания, правится **текст** `style_notes_en`, а не подбор
картинок: текст здесь первичен, картинка — его закрепление.
