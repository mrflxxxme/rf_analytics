"""Витрины измеренных фактов по реестру МСП (D25, D27). Определения — 03-methodology.md, п. 11.

Вход: каталог `rsmp_YYYY-MM-DD.parquet` (выход parse). Выход: Parquet + CSV.
  msp_active        — активные субъекты на дату снимка по (регион, потребность)
  msp_growth_12m    — чистый прирост за 12 мес.: ln(active_t / active_{t-12})
  msp_survival_12m  — доля вновь созданных субъектов, вошедших в реестр за 3 мес.
                      до снимка, которые есть в реестре через 12 мес.
  okved_counts      — активные субъекты по основному ОКВЭД (для проверки таксономии)
need_id = '_all' — все субъекты региона, в т.ч. вне таксономии.
"""

from __future__ import annotations

import csv
from pathlib import Path

import duckdb

from rf_etl import taxonomy as tx

ALL = "_all"


def _okved_map(con: duckdb.DuckDBPyConnection, tax: tx.Taxonomy) -> None:
    codes = [r[0] for r in con.execute("SELECT DISTINCT okved FROM msp WHERE okved IS NOT NULL").fetchall()]
    rows = [(c, tx.need_for_okved(tax, c)) for c in codes]
    con.execute("CREATE TABLE okved_need (okved VARCHAR, need_id VARCHAR)")
    if rows:
        con.executemany("INSERT INTO okved_need VALUES (?, ?)", rows)


def build(slim_dir: str | Path, taxonomy_path: str | Path, regions_csv: str | Path,
          out_dir: str | Path) -> dict[str, object]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tax = tx.load(taxonomy_path)
    with open(regions_csv, encoding="utf-8") as f:
        known_regions = {r["region_id"] for r in csv.DictReader(f)}

    con = duckdb.connect()
    files = sorted(str(p) for p in Path(slim_dir).glob("rsmp_*.parquet"))
    if not files:
        raise FileNotFoundError(f"нет rsmp_*.parquet в {slim_dir}")
    con.execute(f"CREATE VIEW msp AS SELECT * FROM read_parquet({files!r})")
    _okved_map(con, tax)
    con.execute("""
        CREATE TABLE m AS
        SELECT msp.*, coalesce(n.need_id, NULL) AS need_id
        FROM msp LEFT JOIN okved_need n USING (okved)""")

    con.execute(f"""
        CREATE TABLE msp_active AS
        WITH x AS (
            SELECT snapshot_date, region_id, need_id FROM m WHERE need_id IS NOT NULL
            UNION ALL SELECT snapshot_date, region_id, '{ALL}' FROM m)
        SELECT snapshot_date, region_id, need_id, count(*)::BIGINT AS active
        FROM x GROUP BY ALL""")

    con.execute("""
        CREATE TABLE msp_growth_12m AS
        SELECT a.snapshot_date, a.region_id, a.need_id, a.active, p.active AS active_prev_12m,
               ln(a.active::DOUBLE / p.active) AS net_growth_log
        FROM msp_active a JOIN msp_active p
          ON p.region_id = a.region_id AND p.need_id = a.need_id
         AND p.snapshot_date = a.snapshot_date - INTERVAL 12 MONTH""")

    con.execute(f"""
        CREATE TABLE msp_survival_12m AS
        WITH cohort AS (
            SELECT snapshot_date AS cohort_date, inn, region_id, need_id FROM m
            WHERE is_new AND inn IS NOT NULL
              AND date_incl > snapshot_date - INTERVAL 3 MONTH AND date_incl <= snapshot_date),
        later AS (SELECT DISTINCT snapshot_date, inn FROM m),
        flagged AS (
            SELECT c.*, (l.inn IS NOT NULL) AS survived
            FROM cohort c
            JOIN (SELECT DISTINCT snapshot_date FROM m) s
              ON s.snapshot_date = c.cohort_date + INTERVAL 12 MONTH
            LEFT JOIN later l ON l.snapshot_date = s.snapshot_date AND l.inn = c.inn),
        x AS (
            SELECT cohort_date, region_id, need_id, survived FROM flagged WHERE need_id IS NOT NULL
            UNION ALL SELECT cohort_date, region_id, '{ALL}', survived FROM flagged)
        SELECT cohort_date, region_id, need_id, count(*)::BIGINT AS cohort_n,
               count_if(survived)::BIGINT AS survived_n,
               count_if(survived)::DOUBLE / count(*) AS survival_share
        FROM x GROUP BY ALL""")

    latest = con.execute("SELECT max(snapshot_date) FROM m").fetchone()[0]
    con.execute("""
        CREATE TABLE okved_counts AS
        SELECT okved, need_id, count(*)::BIGINT AS active FROM m
        WHERE snapshot_date = ? GROUP BY ALL ORDER BY active DESC""", [latest])

    for name in ("msp_active", "msp_growth_12m", "msp_survival_12m", "okved_counts"):
        con.execute(f"COPY {name} TO '{out / (name + '.parquet')}' (FORMAT parquet, COMPRESSION zstd)")
        con.execute(f"COPY {name} TO '{out / (name + '.csv')}' (HEADER)")

    totals = con.execute("SELECT snapshot_date, count(*) FROM m GROUP BY 1 ORDER BY 1").fetchall()
    unknown = con.execute("SELECT region_id, count(*) FROM m GROUP BY 1").fetchall()
    needs_below = con.execute(f"""
        SELECT need_id, sum(active) FROM msp_active
        WHERE snapshot_date = ? AND need_id <> '{ALL}' GROUP BY 1""", [latest]).fetchall()
    per_need = dict(needs_below)
    return {
        "snapshots": [(str(d), n) for d, n in totals],
        "unknown_regions": sorted((r, n) for r, n in unknown if r not in known_regions),
        "missing_regions": sorted(known_regions - {r for r, _ in unknown}),
        "taxonomy_coverage_latest": round(sum(per_need.values()) / totals[-1][1], 4),
        "needs_below_threshold": sorted(
            (n.id, int(per_need.get(n.id, 0)), tax.threshold(n)) for n in tax.needs
            if per_need.get(n.id, 0) < tax.threshold(n)),
    }
