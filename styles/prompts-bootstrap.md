# Промпты для опор библиотеки

Восемь промптов — по одному на вариацию манеры. Каждый прогоняется **с тремя эталонами**
из `kino-realizm-etalon/refs/` в качестве стилевых референсов: передавать сами файлы, а не
их описание.

```text
styles/kino-realizm-etalon/refs/ref-01.jpeg   тёмный отсек, тёплая лампа
styles/kino-realizm-etalon/refs/ref-02.png    корабль снаружи, контровой
styles/kino-realizm-etalon/refs/ref-03.jpeg   дневной отсек, серебристый свет
```

Результат кладётся в `styles/<направление>/refs/ref-01.<ext>`, лицензия `own-work` (или
`generated-here`, если генерировали уже внутри пайплайна). Одна картинка на направление —
этого хватает, чтобы закрепить манеру; вторую добирать, только если первая вышла мимо.

Общая часть у всех промптов одна и та же — она снята с ваших эталонов:

> Images 1–3 are STYLE REFERENCES: transfer their rendering manner only — painterly digital
> concept art with photographic weight, practical light sources inside the frame, full value
> range down to true black, visible brush economy on metal and fabric while the focal object
> holds crisp detail, worn lived-in objects rendered with the same care as the machinery,
> desaturated palette split warm against cool. Do not copy their subjects, characters,
> spacecraft or lettering.
> Asset: a single image, 3:2 landscape.
> Avoid: likeness of actors or film adaptations, other illustrators' compositions, signatures,
> watermarks, artist marks, any legible text or lettering.

---

## 1. `kino-tenebrizm` — тёмный отсек, один тёплый источник

```text
Scene: a near-black interior of a working spacecraft compartment. One warm practical work lamp
on a cluttered bench is the only light source, carving a seated figure and the bench out of the
darkness. A porthole behind holds a cold blue starfield. Metal surfaces are read through
highlights rather than outline; the far walls dissolve into black.
Mood: concentration in the middle of a long night watch.
Composition: figure in three-quarter view at the left, bench running into the frame from the
bottom edge, porthole as a small cold disc in the upper right.
Palette: amber and gunmetal against deep blue-black.
```

## 2. `kino-pult` — свет только от приборов

```text
Scene: a cramped technical compartment lit only by its own instruments. Blue-green screen glow
rises from below onto a face and the ceiling; everything beyond the consoles sinks into black.
Cable looms, toggle switches, worn hand-written labels taped to panels. Cyan and amber
indicator lights are the only saturated colour in the frame.
Mood: something is wrong and is being read off a gauge.
Composition: close, shallow, the operator's face lit from beneath at the right, console filling
the lower two thirds.
Palette: cyan and amber points on cold black-green.
```

## 3. `kino-massovka` — массовка в форме под холодным светом

```text
Scene: many people in identical work uniform under cold flat overhead light — a formation in a
large industrial hall. Individual faces under one unvarying light; haze thickens in the depth of
the hall, dissolving the far ranks. Scale is set by the architecture above them, not by the
composition.
Mood: routine that no one questions any more.
Composition: eye level inside the crowd, three faces sharp in the foreground, the rest receding
into haze; the ceiling structure visible above.
Palette: steel grey, uniform drab, pale skin, one distant warm lamp.
```

## 4. `kino-korabl-snaruzhi` — корабль снаружи

```text
Scene: a working spacecraft in vacuum, lit by hard rim light from a distant sun. Pure black sky
with no atmospheric haze; a planet limb glows along one edge of the frame. Hull panelling,
seams, radiators and antennae are readable down to the joint. Engine glow is the only saturated
colour.
Mood: enormous, patient, unbothered by anyone watching.
Composition: the vessel crossing the frame diagonally, planet limb lower left, sun flaring at
the upper right edge.
Palette: white-grey hull, black sky, one cold blue exhaust.
```

## 5. `kino-poverkhnost` — поверхность планеты

```text
Scene: a dust plain under a low sun. Long hard-edged shadows rake across regolith; vehicle
tracks cross the foreground. The sky is rust-orange with no haze near the horizon and darkens
overhead. A single suited figure stands at middle distance, small, giving the scale.
Mood: nothing here has ever been disturbed before.
Composition: low camera, foreground dust and a boot print cropped by the bottom edge, figure on
the horizon line at the right third.
Palette: grey-rust dust, bleached highlights, deep shadow with no fill light.
```

## 6. `kino-skafandr` — скафандр крупно

```text
Scene: a spacesuit helmet in close-up. The gold visor reflects everything outside the frame —
the sun as a hard point, the hull, a second crew member at work. Micro-detail in the suit
fabric, straps, connectors and dust worked into the seams.
Mood: a person entirely enclosed, and calm about it.
Composition: helmet filling two thirds of the frame, slightly off-centre, shallow depth of field
with the fabric at the shoulder already soft.
Palette: warm gold visor against cold white suit and black sky.
```

## 7. `kino-shakhta` — шахта, прожекторы в пыли

```text
Scene: an underground working face at industrial scale. Floodlight cones cut through hanging
dust; wet rock throws back hard specular highlights. Cables, rails and ore cars run into the
depth. Small figures stand at the foot of the face, giving the scale of the cut.
Mood: the work is heavy and has been going on a long time.
Composition: deep perspective down the tunnel, one floodlight flaring near the top edge,
figures small at the far end.
Palette: coal black, wet slate, one harsh white light source, dust catching it.
```

## 8. `kino-dnevnoy-otsek` — дневной отсек

```text
Scene: a bright habitat interior under soft silvery diffuse toplight. A working table strewn
with papers, mugs, pens, a notebook and instruments — every object fully rendered. Warm skin
tones against grey brushed metal; equipment racks and stowage bags fill the background.
Mood: an ordinary working morning a long way from home.
Composition: table running across the lower third, a person leaning in from the left, the
compartment opening into depth behind them.
Palette: aluminium grey, bone white, warm flesh, one saturated object on the table.
```

---

## Что делать с результатом

1. Файл — в `styles/<направление>/refs/ref-01.<ext>`.
2. Запись в `style.json` направления: `stored: true`, `license: own-work`,
   `license_basis` — «собственная генерация владельца репозитория; проект не считает
   сгенерированные изображения объектом исключительных прав (RIGHTS.md)», `sha256` файла.
   Это сделает `scripts/add_ref.py` (задача 4), пока — руками.
3. `python3 scripts/build_styles_page.py` — пересобрать `styles/index.html` и посмотреть
   девять направлений рядом.

Если первая же картинка выйдет мимо манеры — значит эталоны не переносятся, и это важнее
самой библиотеки: тогда лист персонажа как визуальный якорь (задача 8) тоже не сработает, и
контракт надо пересматривать до того, как писать скрипты.
