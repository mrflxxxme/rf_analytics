"""Витрина `region_profile` — измеренные показатели субъектов 2016→сейчас (03-methodology.md, п. 12).

  region_profile         — (регион, показатель, год): значение, источник, флаги
  region_profile_status  — (регион, показатель): первый и последний год, ожидаемый год, `stale`
Показатель за год берётся из первого по приоритету источника, где он есть (`Indicator.sources`).
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from rf_etl.rosstat import fetch
from rf_etl.rosstat import parse as rp

FIRST_YEAR = 2016


@dataclass(frozen=True)
class Indicator:
    id: str
    label: str
    unit: str
    stock: bool  # на 1 января года (True) или за год (False)
    lag_months: int  # от даты значения (1 января / 31 декабря) до публикации — порог устаревания
    sources: tuple[str, ...]  # семейства источников по убыванию приоритета


INDICATORS = (
    Indicator("population", "Численность постоянного населения на 1 января", "чел.", True, 4,
              ("okpopul", "polvozr")),
    Indicator("urban_share", "Доля городского населения на 1 января", "%", True, 4,
              ("showdata", "okpopul", "polvozr")),
    Indicator("migration_rate", "Коэффициент миграционного прироста за год", "на 10 000 чел.", False, 5,
              ("showdata", "okpopul")),
    Indicator("income_per_capita", "Среднедушевые денежные доходы населения за год", "руб./мес.", False, 4,
              ("urov",)),
)
BY_ID = {i.id: i for i in INDICATORS}


def expected_year(ind: Indicator, asof: dt.date) -> int:
    """Последний год, значение за который к дате `asof` уже должно быть опубликовано."""
    m = asof.year * 12 + asof.month - 1 - ind.lag_months
    y = m // 12
    return y if ind.stock else y - 1


def select(obs: list[rp.Obs]) -> list[rp.Obs]:
    """Одно значение на (регион, показатель, год): первый источник из `Indicator.sources`."""
    best: dict[tuple[str, str, int], rp.Obs] = {}
    for o in obs:
        ind = BY_ID[o.indicator]
        if o.year < FIRST_YEAR or o.kind not in ind.sources:
            continue
        key = (o.region_id, o.indicator, o.year)
        cur = best.get(key)
        if cur is None or ind.sources.index(o.kind) < ind.sources.index(cur.kind):
            best[key] = o
    return sorted(best.values(), key=lambda o: (o.region_id, o.indicator, o.year))


def status(rows: list[rp.Obs], region_ids: list[str], asof: dt.date) -> list[dict[str, object]]:
    years: dict[tuple[str, str], list[int]] = {}
    for o in rows:
        years.setdefault((o.region_id, o.indicator), []).append(o.year)
    out = []
    for rid in region_ids:
        for ind in INDICATORS:
            ys = sorted(years.get((rid, ind.id), []))
            exp = expected_year(ind, asof)
            out.append({
                "region_id": rid, "indicator": ind.id,
                "first_year": ys[0] if ys else None, "last_year": ys[-1] if ys else None,
                "n_years": len(ys), "expected_year": exp,
                "missing_years": len(set(range(FIRST_YEAR, exp + 1)) - set(ys)),
                "stale": not ys or ys[-1] < exp,
            })
    return out


def collect(raw_dir: str | Path, regions: list[dict[str, str]]) -> tuple[list[rp.Obs], dict[str, object]]:
    raw = Path(raw_dir)
    names, okato = rp.RegionNames(regions), rp.okato_index(regions)
    obs: list[rp.Obs] = []
    files: dict[str, dict[str, object]] = {}

    def add(path: Path, res: rp.Parsed) -> None:
        obs.extend(res.obs)
        files[path.name] = {"obs": len(res.obs), "conflicts": res.conflicts,
                            "unmatched": sorted(set(res.unmatched))}

    for rid, ind in fetch.SHOWDATA_REPORTS.items():
        p = raw / f"showdata_{rid}.json"
        add(p, rp.parse_showdata(p, ind, okato))
    for p in sorted(raw.glob("*.xlsx")):
        if rp.POLVOZR.search(p.name):
            add(p, rp.parse_polvozr(p, names))
        elif rp.OKPOPUL.search(p.name):
            add(p, rp.parse_okpopul(p, names))
        elif rp.INCOME.search(p.name):
            add(p, rp.parse_income(p, names))
    return obs, files


def _write(rows: list[dict[str, object]], out: Path, name: str) -> None:
    t = pa.Table.from_pylist(rows)
    pq.write_table(t, out / f"{name}.parquet", compression="zstd")
    pacsv.write_csv(t, out / f"{name}.csv")


def build(raw_dir: str | Path, regions_csv: str | Path, out_dir: str | Path,
          asof: dt.date | None = None) -> dict[str, object]:
    asof = asof or dt.datetime.now(dt.UTC).date()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    regions = rp.load_regions(regions_csv)
    obs, files = collect(raw_dir, regions)
    rows = select(obs)
    st = status(rows, [r["region_id"] for r in regions], asof)
    flags = {(s["region_id"], s["indicator"]): s for s in st}
    _write([{**asdict(o) | {"unit": BY_ID[o.indicator].unit},
             "last_year": flags[(o.region_id, o.indicator)]["last_year"],
             "stale": flags[(o.region_id, o.indicator)]["stale"]} for o in rows], out, "region_profile")
    _write(st, out, "region_profile_status")

    fetch_log = Path(raw_dir) / fetch.FETCH_JSON
    by_ind = Counter(o.indicator for o in rows)
    report: dict[str, object] = {
        "asof": str(asof),
        "indicators": [asdict(i) for i in INDICATORS],
        "rows": len(rows),
        "rows_by_indicator": dict(sorted(by_ind.items())),
        "years_by_indicator": {i.id: sorted({o.year for o in rows if o.indicator == i.id}) for i in INDICATORS},
        "stale_by_indicator": {i.id: sum(1 for s in st if s["indicator"] == i.id and s["stale"])
                               for i in INDICATORS},
        "regions_without_data": sorted({s["region_id"] for s in st if s["last_year"] is None}),
        "files": files,
        "sources": json.loads(fetch_log.read_text("utf-8")) if fetch_log.exists() else [],
    }
    (out / "region_profile_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    return report
