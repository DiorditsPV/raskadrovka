# Red Rising — проба направлений

Восемь кадров: по два на каждое из четырёх направлений стиля плюс пара «с шаблоном
композиции и без». Цель партии — не иллюстрации к книге, а выбор: какая манера этой книге
идёт и нужен ли вообще шаблон блокинга.

Сцены взяты из первых трёх глав, герои — из библии книги, у каждого кадра свой промпт в
`prompt/` и запись с хешами в `metadata/request.json`.

Партия пересобиралась трижды по разбору кадров человеком. Что чинилось:

1. **Анатомия** — в запреты промпта внесены невозможные позы, поворот головы за предел
   позвоночника, непропорциональные конечности, лишние пальцы, суставы наоборот.
2. **Шум** — добавлена секция ясности: деталь концентрируется у света и гаснет в крупные
   спокойные плоскости; блок объяснений про входные картинки сжат с трети промпта до
   восьмой части.
3. **Палитра** — убрана из карточек сцен и заведена в направлениях полем `palette_en`
   (тональный ключ и названные цвета). До этого цвет задавало освещение сцены, и все
   направления сходились в янтарь на чёрном: сцены книги подземные.
4. **Разрез** — убран из направлений на ось композиции шаблоном `05-razrez-obekta`:
   вскрытый объект это способ показать предмет, а не манера рисунка.
5. **Локаторы** — шесть из восьми указывали не на те абзацы; пересчитаны по хешам.

Книга охраняется (Pierce Brown, «Red Rising», Del Rey, 2014). Текст в репозиторий не
попадает: в `book.json` только выходные данные, оглавление и хеши абзацев. Отрывки в
карточках — целые абзацы локатора, суммарно 0.66% объёма при пределе 3%.

<!--raskadrovka:scenes-->
| Кадр                                                                                                                                                                        | Направление                    | Шаблон               |
|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------|----------------------|
| [Хеллдайвер в глубоком забое — kinematograficheskiy-realizm](../../../output/pierce-brown-red-rising--proba--kinematograficheskiy-realizm--01-helldiver-v-zaboe.png)        | `kinematograficheskiy-realizm` | `03-spinoy-vdal`     |
| [Спуск к газовому карману — kinematograficheskiy-realizm](../../../output/pierce-brown-red-rising--proba--kinematograficheskiy-realizm--02-spusk-k-karmanu.png)             | `kinematograficheskiy-realizm` | `02-krupno-i-daleko` |
| [Урод Дэн бросает камешек — tush-i-plashki](../../../output/pierce-brown-red-rising--proba--tush-i-plashki--03-ugly-dan-kidaet-kamen.png)                                   | `tush-i-plashki`               | `01-dvoe-litsom`     |
| [Урод Дэн бросает камешек — tush-i-plashki (без композиции)](../../../output/pierce-brown-red-rising--proba--tush-i-plashki--03-ugly-dan-kidaet-kamen--bez-kompozitsii.png) | `tush-i-plashki`               | `—`                  |
| [Лицо под забралом — tush-i-plashki](../../../output/pierce-brown-red-rising--proba--tush-i-plashki--07-litso-v-shleme.png)                                                 | `tush-i-plashki`               | `04-krupny-plan`     |
| [Ио в дверях, волосы в паутине — akvarel-po-peru](../../../output/pierce-brown-red-rising--proba--akvarel-po-peru--04-eo-v-pautine.png)                                     | `akvarel-po-peru`              | `01-dvoe-litsom`     |
| [Нарол с цитрой — akvarel-po-peru](../../../output/pierce-brown-red-rising--proba--akvarel-po-peru--08-narol-s-tsitroy.png)                                                 | `akvarel-po-peru`              | `04-krupny-plan`     |
| [Туннельная дорога на Лаврелтайд — maslo-epika](../../../output/pierce-brown-red-rising--proba--maslo-epika--06-tunnelroad-lavreltayd.png)                                  | `maslo-epika`                  | `02-krupno-i-daleko` |
<!--/raskadrovka:scenes-->
