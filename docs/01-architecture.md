# 01. Архитектура

## Схема

```
                ┌──────────────── сервер 194.87.187.207 (РФ IP) ────────────────┐
 госисточники ──▶ fetcher (cron, nice/ionice, только сеть+диск)                 │
 (ЕМИСС,        │   └─▶ /opt/rf-analytics/raw/<source>/<date>/…                 │
  закупки…)     │                                                               │
                │ /opt/rf-analytics/marts/<snapshot>/*.parquet ◀── rsync ──┐    │
                │      │                                                   │    │
                │  api (FastAPI + DuckDB read-only, ≤512 МБ)               │    │
                │  web (статика) ── rf-analytics-caddy ── сеть edge ──▶ edge-caddy ──▶ <домен RADAR, D28>
                └──────────────────────────────────────────────────────────┼────┘
                                                                           │
 открытые источники без геоблока ──▶ GitHub Actions (monthly-etl.yml) ─────┘
 (реестр МСП ФНС, OSM,                1. rsync raw с сервера (ключ деплоя)
  Open-Meteo, hh API…)                2. Python + DuckDB: нормализация → признаки → модель → бэктест
                                      3. витрины Parquet (десятки МБ) + отчёт бэктеста
                                      4. rsync витрин на сервер, атомарное переключение snapshot
```

## Компоненты

| Компонент | Где | Технологии | Ответственность |
|---|---|---|---|
| `fetcher` | сервер, cron в контейнере | Python, `httpx` | Скачивает источники, которые блокируют зарубежные IP; ничего не разбирает |
| `etl` | GitHub Actions | Python 3.12, `uv`, DuckDB, Polars, statsmodels/scikit-learn | Сбор, нормализация, признаки, модель, бэктест, витрины |
| `api` | сервер | FastAPI, DuckDB (read-only), Pydantic | Отдаёт витрины, исполняет query-spec, `/ask`, `/enrich` |
| `web` | сервер (статика) | Vite, React, TypeScript, MapLibre GL, deck.gl | Карта, конструктор, досье |
| `enrich` | GitHub Actions (`workflow_dispatch`) | тот же `etl` | Дообогащение по запросу пользователя |
| `drivers` | GitHub Actions (еженедельно) | `etl` + LLM-клиент | Извлечение кандидатов в драйверы из новостей и актов |

## Снимки и воспроизводимость

- Каждый ежемесячный прогон создаёт **snapshot** `YYYY-MM-<gitsha>`: витрины,
  `manifest.json` (версии источников, хеши, версия методологии, метрики бэктеста).
- На сервере `marts/current` — симлинк на активный snapshot. Переключение
  атомарное, откат — смена симлинка. Хранятся последние 6 снимков.
- Реализация (T1.4): `.github/workflows/monthly-etl.yml` (14-го числа и вручную,
  `workflow_dispatch`) → `rf-etl manifest` → rsync в `marts/.incoming/<snapshot>` →
  `deploy/publish-snapshot.sh` на сервере. Стек выкладывает `deploy-stack.yml`
  при изменении `deploy/**` в `main`.
- В интерфейсе всегда виден snapshot и дата данных. Ссылка на состояние экрана
  содержит snapshot, поэтому отчёт воспроизводим.

## API (черновик контракта)

| Метод | Назначение |
|---|---|
| `GET /api/meta` | Активный snapshot, свежесть источников, метрики бэктеста (для плашки беты) |
| `GET /api/geo` | Полигоны субъектов и точки городов (кешируется навсегда в пределах snapshot) |
| `GET /api/needs`, `GET /api/regions` | Справочники |
| `POST /api/query` | Исполнение **query-spec** (JSON-DSL поверх семантического слоя `config/metrics.yaml`) |
| `GET /api/dossier/{region}/{need}` | Досье пары: факторы, ряды, драйверы, связи, источники |
| `GET /api/links?type=waves\|migration\|drivers&need=…` | Связи для слоёв карты |
| `POST /api/ask` | Вопрос → LLM → query-spec (валидируется), выполнение, ответ + показанный spec |
| `POST /api/enrich` | Постановка задачи дообогащения → `workflow_dispatch` → статус в `/api/enrich/{id}` |

Query-spec — единственный способ получить данные. И конструктор, и LLM
порождают одно и то же: `{metrics[], filters[], group_by, period, compare_to, map_binding}`.
Метрики и измерения берутся только из белого списка семантического слоя,
поэтому SQL-инъекции и «галлюцинированные» метрики невозможны.

Реализация (T2.1): `api/` (`rf_api`), семантический слой `config/metrics.yaml`, тесты
`tests/api/`. Ответ `/api/query` — длинная таблица `{metric, <измерения>, period, value}`;
доли и логарифмы пересчитываются из сумм компонентов. Без `period` в `group_by` —
последняя точка не позже `period.to`; с ним — ряд `[from, to]`. Нарушение белого
списка → 422 с кодом (`unknown_metric`, `no_rollup`, …); `compare_to` до M1 не
принимается. Ещё `GET /api/metrics` (публичная часть слоя, без `expr`) и `/api/health`.
Образ собирается в Actions и загружается на сервер `docker load`; api сидит только
во внутренней сети проекта (`internal`, без выхода наружу), в `edge` — один caddy.

## Деплой на сервер

Шаблон тот же, что у остальных сайтов сервера:

- каталог `/opt/rf-analytics`, свой compose-проект `rf-analytics`;
- контейнеры `rf-analytics-caddy` (статика + `reverse_proxy /api/* api:8000`) и
  `rf-analytics-api`, **порты не публикуются**, оба в сети `edge`;
- `fetcher` — отдельный сервис с `cpus: 0.5`, `mem_limit: 256m`, запуск ночью
  (00:30 UTC); список источников — `deploy/fetcher/sources.json`, результат —
  `raw/<source>/<дата>/` + `fetch.json`;
- лимиты: api `mem_limit: 512m`, `cpus: 1.0` (на сервере 2 ядра и ~3 ГБ свободно,
  он общий ещё с 9 сайтами);
- в `/opt/edge-caddy/Caddyfile` дописывается один блок
  `<домен> { reverse_proxy rf-analytics-caddy:8080 }` (домен - из T1.0, D28). Перед правкой —
  бэкап рядом, затем **только** `caddy validate` + `caddy reload`, никогда restart;
- статика публикуется через `rsync -a --delete` **внутрь** существующего каталога
  (подмена каталога через `mv` ломает bind-монт).

Раскладка статики (T2.2, T2.5; workflow `web.yml`): `/` (оглавление), `/fakty/nisha/<need_id>/`,
`/fakty/region/<region_id>/`, `/fakty/nisha-mesyaca/`, `/fakty/region-nedeli/`, `/metodologiya/`,
`sitemap.xml`, `robots.txt` — индексируемый слой фактов (D27), собирается `rf-etl facts` из
`marts/current` сервера; `/karta/` — приложение `web/` (Vite, React, MapLibre + deck.gl).
Пересборка: push в `main`, успешный `monthly-etl` (новый snapshot) и по понедельникам
(«Регион недели» — ротация по номеру ISO-недели). Внутренний Caddy ставит
`X-Robots-Tag: noindex` на всё, кроме путей фактов на своём домене; временный адрес
`*.sslip.io` закрыт целиком, чтобы поиск не запомнил его до переезда (R14). Канонический
адрес в страницах и sitemap — переменная репозитория `RF_SITE_URL` (по умолчанию `https://nishemer.ru`).

DNS: A и AAAA для домена продукта → `194.87.187.207` / `2a03:6f00:a::2:da7f`.

## Секреты

| Секрет | Где | Назначение |
|---|---|---|
| `RF_DEPLOY_SSH_KEY` | GitHub Secrets | Отдельный ключ деплоя (`id_ed25519_rf_analytics`), rsync raw/marts/static |
| `RF_DEPLOY_KNOWN_HOSTS` | GitHub Secrets | Отпечаток сервера, без `StrictHostKeyChecking=no` |
| `CLOUDRU_API_KEY`, `DEEPSEEK_API_KEY` | GitHub Secrets + `/opt/rf-analytics/.env` | LLM (ключи переносит автор, агенты их не читают). На время разработки - виртуальный ключ RADAR в LLM-шлюзе экосистемы (D33) |
| `WORDSTAT_*` | там же | После получения доступа к API |
| `GH_DISPATCH_TOKEN` | `/opt/rf-analytics/.env` | Fine-grained токен только на `actions:write` этого репо — для `/enrich` |

`.env` на сервере — `chmod 600`, вне каталога статики. В репозитории только `.env.example`.

## Почему так, а не иначе

- **ETL не на сервере:** выгрузки реестра МСП и OSM весят гигабайты и съели бы
  память соседних сайтов. Actions бесплатны и без лимита минут для публичного репо.
- **Не self-hosted runner:** в публичном репозитории чужой pull request может
  выполнить код на сервере.
- **DuckDB + Parquet, без Postgres:** данные только на чтение и обновляются раз
  в месяц; отдельная СУБД — лишние память и администрирование.
