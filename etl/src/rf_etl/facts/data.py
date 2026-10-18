"""Факты для индексируемого слоя (T2.5, D27): только измеренные величины из витрин snapshot.

Вход — каталог snapshot (msp_active, msp_growth_12m, msp_survival_12m, manifest.json).
Числа не выдумываются и не прогнозируются: счёт субъектов, его изменение за 12 месяцев,
доля новых субъектов, работающих через 12 месяцев (03-methodology.md).
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import yaml

ALL = "_all"
MIN_BASE = 50  # рейтинг роста — только где 12 месяцев назад было не меньше MIN_BASE субъектов
MIN_COHORT = 30  # выживаемость — только когорты от MIN_COHORT субъектов


@dataclass
class Ranked:
    key: str
    value: float
    base: int | None = None


@dataclass
class NeedFacts:
    need_id: str
    name: str
    active: int  # по РФ на дату снимка
    growth: float | None  # ln(t / t−12) по РФ
    series: list[tuple[dt.date, int]]  # по РФ, все снимки
    top_regions: list[Ranked]
    fastest_regions: list[Ranked]
    survival: float | None
    survival_cohort: dt.date | None
    region_values: dict[str, int] = field(default_factory=dict)


@dataclass
class RegionFacts:
    region_id: str
    name: str
    active: int  # все субъекты МСП региона (_all)
    growth: float | None
    series: list[tuple[dt.date, int]]
    top_needs: list[Ranked]
    fastest_needs: list[Ranked]
    survival: float | None
    survival_cohort: dt.date | None


@dataclass
class Facts:
    snapshot: str
    data_date: dt.date
    methodology_version: str
    taxonomy_version: str
    needs: dict[str, NeedFacts]
    regions: dict[str, RegionFacts]
    region_order: list[str]  # порядок Конституции — для ротации «Региона недели»


def _ref_regions(config_dir: Path) -> tuple[dict[str, str], list[str]]:
    with open(config_dir / "geo" / "regions.csv", encoding="utf-8") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: int(r["constitution_order"]))
    return {r["region_id"]: r["name"] for r in rows}, [r["region_id"] for r in rows]


def _ref_needs(config_dir: Path) -> dict[str, str]:
    tax = yaml.safe_load((config_dir / "taxonomy.yaml").read_text("utf-8"))
    return {n["id"]: n["name"] for n in tax["needs"] if n.get("status", "active") == "active"}


def load(marts_dir: str | Path, config_dir: str | Path, top: int = 10) -> Facts:
    marts, cfg = Path(marts_dir), Path(config_dir)
    man = json.loads((marts / "manifest.json").read_text("utf-8"))
    region_names, order = _ref_regions(cfg)
    need_names = _ref_needs(cfg)
    con = duckdb.connect(":memory:")
    for t in ("msp_active", "msp_growth_12m", "msp_survival_12m"):
        p = marts / f"{t}.parquet"
        if not p.is_file():
            raise FileNotFoundError(f"нет витрины {p}")
        con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{p.as_posix()}')")
    latest: dt.date = con.execute("SELECT max(snapshot_date) FROM msp_active").fetchone()[0]  # type: ignore[index]

    def q(sql: str, *params: object) -> list[tuple]:  # type: ignore[type-arg]
        return con.execute(sql, list(params)).fetchall()

    # Ряды по РФ и по региону (_all) — все снимки.
    series_need: dict[str, list[tuple[dt.date, int]]] = {}
    for need, d, v in q("SELECT need_id, snapshot_date, sum(active) FROM msp_active WHERE need_id <> ? "
                        "GROUP BY ALL ORDER BY 1, 2", ALL):
        series_need.setdefault(need, []).append((d, int(v)))
    series_region: dict[str, list[tuple[dt.date, int]]] = {}
    for reg, d, v in q("SELECT region_id, snapshot_date, active FROM msp_active WHERE need_id = ? ORDER BY 1, 2", ALL):
        series_region.setdefault(reg, []).append((d, int(v)))

    # Рост по РФ: из сумм компонентов, а не усреднением (как в config/metrics.yaml).
    g_need = {n: g for n, g in q("SELECT need_id, ln(sum(active)::DOUBLE / sum(active_prev_12m)) FROM msp_growth_12m "
                                  "WHERE snapshot_date = ? AND need_id <> ? GROUP BY 1", latest, ALL)}
    g_region = {r: g for r, g in q("SELECT region_id, ln(active::DOUBLE / active_prev_12m) FROM msp_growth_12m "
                                    "WHERE snapshot_date = ? AND need_id = ?", latest, ALL)}

    cohort = q("SELECT max(cohort_date) FROM msp_survival_12m")[0][0]
    s_need = {n: (s, c) for n, s, c in q("SELECT need_id, sum(survived_n)::DOUBLE / sum(cohort_n), sum(cohort_n) "
                                          "FROM msp_survival_12m WHERE cohort_date = ? GROUP BY 1", cohort)}
    s_region = {r: (s, c) for r, s, c in q("SELECT region_id, survived_n::DOUBLE / cohort_n, cohort_n "
                                            "FROM msp_survival_12m WHERE cohort_date = ? AND need_id = ?", cohort, ALL)}

    def surv(x: tuple[float, int] | None) -> float | None:
        return x[0] if x and x[1] >= MIN_COHORT else None

    cur = q("SELECT region_id, need_id, active FROM msp_active WHERE snapshot_date = ?", latest)
    by_need: dict[str, dict[str, int]] = {}
    by_region: dict[str, dict[str, int]] = {}
    for reg, need, v in cur:
        if reg not in region_names:
            continue
        if need != ALL:
            by_need.setdefault(need, {})[reg] = int(v)
            by_region.setdefault(reg, {})[need] = int(v)
    grow = q("SELECT region_id, need_id, ln(active::DOUBLE / active_prev_12m), active_prev_12m FROM msp_growth_12m "
             "WHERE snapshot_date = ? AND need_id <> ? AND active_prev_12m >= ?", latest, ALL, MIN_BASE)
    g_by_need: dict[str, list[Ranked]] = {}
    g_by_region: dict[str, list[Ranked]] = {}
    for reg, need, g, base in grow:
        if reg in region_names and g is not None:
            g_by_need.setdefault(need, []).append(Ranked(reg, g, int(base)))
            g_by_region.setdefault(reg, []).append(Ranked(need, g, int(base)))

    def rank(d: dict[str, int]) -> list[Ranked]:
        return [Ranked(k, v) for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[:top]]

    def fastest(lst: list[Ranked]) -> list[Ranked]:
        return sorted(lst, key=lambda r: (-r.value, r.key))[:top]

    needs = {}
    for nid, name in need_names.items():
        ser = series_need.get(nid, [])
        if not ser:
            continue
        needs[nid] = NeedFacts(nid, name, ser[-1][1] if ser[-1][0] == latest else 0, g_need.get(nid), ser,
                               rank(by_need.get(nid, {})), fastest(g_by_need.get(nid, [])),
                               surv(s_need.get(nid)), cohort, by_need.get(nid, {}))
    regions = {}
    for rid, name in region_names.items():
        ser = series_region.get(rid, [])
        if not ser or ser[-1][0] != latest:
            continue  # новые субъекты без данных реестра — страницы нет
        regions[rid] = RegionFacts(rid, name, ser[-1][1], g_region.get(rid), ser,
                                   rank({k: v for k, v in by_region.get(rid, {}).items() if k in need_names}),
                                   fastest([r for r in g_by_region.get(rid, []) if r.key in need_names]),
                                   surv(s_region.get(rid)), cohort)
    con.close()
    return Facts(str(man["snapshot"]), latest, str(man.get("methodology_version", "")),
                 str(man.get("taxonomy_version", "")), needs, regions, [r for r in order if r in regions])


def niche_of_month(f: Facts) -> str | None:
    """«Ниша месяца»: самый быстрый измеренный рост числа субъектов по РФ за 12 месяцев."""
    cand = [n for n in f.needs.values() if n.growth is not None]
    return max(cand, key=lambda n: (n.growth, n.need_id)).need_id if cand else None


def region_of_week(f: Facts, today: dt.date) -> str | None:
    """«Регион недели»: ротация по порядку Конституции, по номеру ISO-недели — без выбора «вручную»."""
    if not f.region_order:
        return None
    y, w, _ = today.isocalendar()
    return f.region_order[(y * 53 + w) % len(f.region_order)]
