# Полигоны субъектов РФ — происхождение

Файл: `config/geo/regions.geojson` — 89 субъектов РФ, свойства `region_id` (код субъекта ФНС, D35) и `name` (из `config/geo/regions.csv`).

- **Источник:** OpenStreetMap, выгрузки Geofabrik `russia-latest.osm.pbf` и `europe/ukraine-latest.osm.pbf` (https://download.geofabrik.de/), скачаны 16.10.2026.
- **Лицензия:** ODbL 1.0 — © участники OpenStreetMap (https://www.openstreetmap.org/copyright). При показе карты нужна атрибуция «© OpenStreetMap contributors».
- **Отбор:** отношения `boundary=administrative`, `admin_level=4`; сопоставление с `regions.csv` по тегу `ISO3166-2`, для Крыма и Севастополя — запасное по имени (`scripts/build_geo.py`). Если субъект есть в обеих выгрузках, берётся геометрия с большим числом вершин.
- **Упрощение:** mapshaper 0.6, `-simplify 6% keep-shapes -clean`, точность координат 0.0001°; общие границы соседей сохраняются. Размер — 1225985 байт (лимит 2 МБ).
- **Сборка:** workflow `.github/workflows/build-geo.yml`, прогон https://github.com/mrflxxxme/rf_analytics/actions/runs/38973554143.
- **Границы:** новые субъекты (90, 93, 94, 95) и Крым с Севастополем (91, 92) — по позиции РФ (D2, `docs/02-data-sources.md`), т. е. в границах, как их задают отношения OSM с кодами RU-*/UA-*.
- **Известное:** полигон Чукотки (87) пересекает антимеридиан 180° (долготы от −180 до 180) — обработка при отрисовке карты в W2.

## Отношения OSM

| region_id | Субъект | OSM |
|---|---|---|
| 01 | Республика Адыгея (Адыгея) | [relation/253256](https://www.openstreetmap.org/relation/253256) |
| 02 | Республика Башкортостан | [relation/77677](https://www.openstreetmap.org/relation/77677) |
| 03 | Республика Бурятия | [relation/145729](https://www.openstreetmap.org/relation/145729) |
| 04 | Республика Алтай | [relation/145194](https://www.openstreetmap.org/relation/145194) |
| 05 | Республика Дагестан | [relation/109876](https://www.openstreetmap.org/relation/109876) |
| 06 | Республика Ингушетия | [relation/253252](https://www.openstreetmap.org/relation/253252) |
| 07 | Кабардино-Балкарская Республика | [relation/109879](https://www.openstreetmap.org/relation/109879) |
| 08 | Республика Калмыкия | [relation/108083](https://www.openstreetmap.org/relation/108083) |
| 09 | Карачаево-Черкесская Республика | [relation/109878](https://www.openstreetmap.org/relation/109878) |
| 10 | Республика Карелия | [relation/393980](https://www.openstreetmap.org/relation/393980) |
| 11 | Республика Коми | [relation/115136](https://www.openstreetmap.org/relation/115136) |
| 12 | Республика Марий Эл | [relation/115114](https://www.openstreetmap.org/relation/115114) |
| 13 | Республика Мордовия | [relation/72196](https://www.openstreetmap.org/relation/72196) |
| 14 | Республика Саха (Якутия) | [relation/151234](https://www.openstreetmap.org/relation/151234) |
| 15 | Республика Северная Осетия — Алания | [relation/110032](https://www.openstreetmap.org/relation/110032) |
| 16 | Республика Татарстан (Татарстан) | [relation/79374](https://www.openstreetmap.org/relation/79374) |
| 17 | Республика Тыва | [relation/145195](https://www.openstreetmap.org/relation/145195) |
| 18 | Удмуртская Республика | [relation/115134](https://www.openstreetmap.org/relation/115134) |
| 19 | Республика Хакасия | [relation/190911](https://www.openstreetmap.org/relation/190911) |
| 20 | Чеченская Республика | [relation/109877](https://www.openstreetmap.org/relation/109877) |
| 21 | Чувашская Республика — Чувашия | [relation/80513](https://www.openstreetmap.org/relation/80513) |
| 22 | Алтайский край | [relation/144764](https://www.openstreetmap.org/relation/144764) |
| 23 | Краснодарский край | [relation/108082](https://www.openstreetmap.org/relation/108082) |
| 24 | Красноярский край | [relation/190090](https://www.openstreetmap.org/relation/190090) |
| 25 | Приморский край | [relation/151225](https://www.openstreetmap.org/relation/151225) |
| 26 | Ставропольский край | [relation/108081](https://www.openstreetmap.org/relation/108081) |
| 27 | Хабаровский край | [relation/151223](https://www.openstreetmap.org/relation/151223) |
| 28 | Амурская область | [relation/147166](https://www.openstreetmap.org/relation/147166) |
| 29 | Архангельская область | [relation/140337](https://www.openstreetmap.org/relation/140337) |
| 30 | Астраханская область | [relation/112819](https://www.openstreetmap.org/relation/112819) |
| 31 | Белгородская область | [relation/83184](https://www.openstreetmap.org/relation/83184) |
| 32 | Брянская область | [relation/81997](https://www.openstreetmap.org/relation/81997) |
| 33 | Владимирская область | [relation/72197](https://www.openstreetmap.org/relation/72197) |
| 34 | Волгоградская область | [relation/77665](https://www.openstreetmap.org/relation/77665) |
| 35 | Вологодская область | [relation/115106](https://www.openstreetmap.org/relation/115106) |
| 36 | Воронежская область | [relation/72181](https://www.openstreetmap.org/relation/72181) |
| 37 | Ивановская область | [relation/85617](https://www.openstreetmap.org/relation/85617) |
| 38 | Иркутская область | [relation/145454](https://www.openstreetmap.org/relation/145454) |
| 39 | Калининградская область | [relation/103906](https://www.openstreetmap.org/relation/103906) |
| 40 | Калужская область | [relation/81995](https://www.openstreetmap.org/relation/81995) |
| 41 | Камчатский край | [relation/151233](https://www.openstreetmap.org/relation/151233) |
| 42 | Кемеровская область — Кузбасс | [relation/144763](https://www.openstreetmap.org/relation/144763) |
| 43 | Кировская область | [relation/115100](https://www.openstreetmap.org/relation/115100) |
| 44 | Костромская область | [relation/85963](https://www.openstreetmap.org/relation/85963) |
| 45 | Курганская область | [relation/140290](https://www.openstreetmap.org/relation/140290) |
| 46 | Курская область | [relation/72223](https://www.openstreetmap.org/relation/72223) |
| 47 | Ленинградская область | [relation/176095](https://www.openstreetmap.org/relation/176095) |
| 48 | Липецкая область | [relation/72169](https://www.openstreetmap.org/relation/72169) |
| 49 | Магаданская область | [relation/151228](https://www.openstreetmap.org/relation/151228) |
| 50 | Московская область | [relation/51490](https://www.openstreetmap.org/relation/51490) |
| 51 | Мурманская область | [relation/2099216](https://www.openstreetmap.org/relation/2099216) |
| 52 | Нижегородская область | [relation/72195](https://www.openstreetmap.org/relation/72195) |
| 53 | Новгородская область | [relation/89331](https://www.openstreetmap.org/relation/89331) |
| 54 | Новосибирская область | [relation/140294](https://www.openstreetmap.org/relation/140294) |
| 55 | Омская область | [relation/140292](https://www.openstreetmap.org/relation/140292) |
| 56 | Оренбургская область | [relation/77669](https://www.openstreetmap.org/relation/77669) |
| 57 | Орловская область | [relation/72224](https://www.openstreetmap.org/relation/72224) |
| 58 | Пензенская область | [relation/72182](https://www.openstreetmap.org/relation/72182) |
| 59 | Пермский край | [relation/115135](https://www.openstreetmap.org/relation/115135) |
| 60 | Псковская область | [relation/155262](https://www.openstreetmap.org/relation/155262) |
| 61 | Ростовская область | [relation/85606](https://www.openstreetmap.org/relation/85606) |
| 62 | Рязанская область | [relation/71950](https://www.openstreetmap.org/relation/71950) |
| 63 | Самарская область | [relation/72194](https://www.openstreetmap.org/relation/72194) |
| 64 | Саратовская область | [relation/72193](https://www.openstreetmap.org/relation/72193) |
| 65 | Сахалинская область | [relation/394235](https://www.openstreetmap.org/relation/394235) |
| 66 | Свердловская область | [relation/79379](https://www.openstreetmap.org/relation/79379) |
| 67 | Смоленская область | [relation/81996](https://www.openstreetmap.org/relation/81996) |
| 68 | Тамбовская область | [relation/72180](https://www.openstreetmap.org/relation/72180) |
| 69 | Тверская область | [relation/2095259](https://www.openstreetmap.org/relation/2095259) |
| 70 | Томская область | [relation/140295](https://www.openstreetmap.org/relation/140295) |
| 71 | Тульская область | [relation/81993](https://www.openstreetmap.org/relation/81993) |
| 72 | Тюменская область | [relation/140291](https://www.openstreetmap.org/relation/140291) |
| 73 | Ульяновская область | [relation/72192](https://www.openstreetmap.org/relation/72192) |
| 74 | Челябинская область | [relation/77687](https://www.openstreetmap.org/relation/77687) |
| 75 | Забайкальский край | [relation/145730](https://www.openstreetmap.org/relation/145730) |
| 76 | Ярославская область | [relation/81994](https://www.openstreetmap.org/relation/81994) |
| 77 | Москва | [relation/102269](https://www.openstreetmap.org/relation/102269) |
| 78 | Санкт-Петербург | [relation/337422](https://www.openstreetmap.org/relation/337422) |
| 79 | Еврейская автономная область | [relation/147167](https://www.openstreetmap.org/relation/147167) |
| 83 | Ненецкий автономный округ | [relation/274048](https://www.openstreetmap.org/relation/274048) |
| 86 | Ханты-Мансийский автономный округ — Югра | [relation/140296](https://www.openstreetmap.org/relation/140296) |
| 87 | Чукотский автономный округ | [relation/151231](https://www.openstreetmap.org/relation/151231) |
| 89 | Ямало-Ненецкий автономный округ | [relation/191706](https://www.openstreetmap.org/relation/191706) |
| 90 | Запорожская область | [relation/71980](https://www.openstreetmap.org/relation/71980) |
| 91 | Республика Крым | [relation/72639](https://www.openstreetmap.org/relation/72639) |
| 92 | Севастополь | [relation/1574364](https://www.openstreetmap.org/relation/1574364) |
| 93 | Донецкая Народная Республика | [relation/71973](https://www.openstreetmap.org/relation/71973) |
| 94 | Луганская Народная Республика | [relation/71971](https://www.openstreetmap.org/relation/71971) |
| 95 | Херсонская область | [relation/71022](https://www.openstreetmap.org/relation/71022) |
