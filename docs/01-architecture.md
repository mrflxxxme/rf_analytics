# 01. Архитектура

## Схема

```
                ┌──────────────── сервер 194.87.187.207 (РФ IP) ────────────────┐
 госисточники ──▶ fetcher (cron, nice/ionice, только сеть+диск)                 │
 (ФНС, ЕМИСС,   │   └─▶ /opt/rf-analytics/raw/<source>/<date>/…                 │
  закупки…)     │                                                               │
                │ /opt/rf-analytics/marts/<snapshot>/*.parquet ◀── rsync ──┐    │
                │      │                                                   │    │
                │  api (FastAPI + DuckDB read-only, ≤512 МБ)               │    │
                │  web (статика) ── rf-analytics-caddy ── сеть edge ──▶ edge-caddy ──▶ radar.uklonskiyk.ru
                └──────────────────────────────────────────────────────────┼────┘
                                                                           │
 открытые источники без геоблока ──▶ GitHub Actions (monthly-etl.yml) ─────┘
 (СберИндекс, OSM/Geofabrik,          1. rsync raw с сервера (ключ деплоя)
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

## Деплой на сервер

Шаблон тот же, что у остальных сайтов сервера:

- каталог `/opt/rf-analytics`, свой compose-проект `rf-analytics`;
- контейнеры `rf-analytics-caddy` (статика + `reverse_proxy /api/* api:8000`) и
  `rf-analytics-api`, **порты не публикуются**, оба в сети `edge`;
- `fetcher` — отдельный сервис с `cpus: 0.5`, `mem_limit: 256m`, запуск ночью;
- лимиты: api `mem_limit: 512m`, `cpus: 1.0` (на сервере 2 ядра и ~3 ГБ свободно,
  он общий ещё с 9 сайтами);
- в `/opt/edge-caddy/Caddyfile` дописывается один блок
  `radar.uklonskiyk.ru { reverse_proxy rf-analytics-caddy:8080 }`. Перед правкой —
  бэкап рядом, затем **только** `caddy validate` + `caddy reload`, никогда restart;
- статика публикуется через `rsync -a --delete` **внутрь** существующего каталога
  (подмена каталога через `mv` ломает bind-монт).

DNS: A и AAAA для поддомена в reg.ru → `194.87.187.207` / `2a03:6f00:a::2:da7f`.

## Секреты

| Секрет | Где | Назначение |
|---|---|---|
| `RF_DEPLOY_SSH_KEY` | GitHub Secrets | Отдельный ключ деплоя (`id_ed25519_rf_analytics`), rsync raw/marts/static |
| `RF_DEPLOY_KNOWN_HOSTS` | GitHub Secrets | Отпечаток сервера, без `StrictHostKeyChecking=no` |
| `CLOUDRU_API_KEY`, `DEEPSEEK_API_KEY` | GitHub Secrets + `/opt/rf-analytics/.env` | LLM (ключи переносит автор, агенты их не читают) |
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
