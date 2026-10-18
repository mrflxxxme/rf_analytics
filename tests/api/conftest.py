from __future__ import annotations

import json
import math
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from rf_api.app import create_app

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"
D1, D2 = "2025-10-10", "2026-10-10"


def write_snapshot(path: Path, sid: str, marts: tuple[str, ...] = ("msp", "profile"), scale: int = 1) -> Path:
    path.mkdir(parents=True)
    con = duckdb.connect()
    if "msp" in marts:
        active = [  # (date, region, need, active)
            (D1, "77", "_all", 1000), (D1, "77", "restaurants_cafes", 100), (D1, "77", "bars_pubs", 10),
            (D1, "78", "_all", 500), (D1, "78", "restaurants_cafes", 50), (D1, "78", "bars_pubs", 5),
            (D2, "77", "_all", 1100), (D2, "77", "restaurants_cafes", 120), (D2, "77", "bars_pubs", 12),
            (D2, "78", "_all", 600), (D2, "78", "restaurants_cafes", 40), (D2, "78", "bars_pubs", 6),
        ]
        active = [(d, r, n, a * scale) for d, r, n, a in active]
        con.execute("CREATE TABLE msp_active (snapshot_date DATE, region_id VARCHAR, need_id VARCHAR, active BIGINT)")
        con.executemany("INSERT INTO msp_active VALUES (?, ?, ?, ?)", active)
        con.execute("""CREATE TABLE msp_growth_12m AS
            SELECT a.snapshot_date, a.region_id, a.need_id, a.active, p.active AS active_prev_12m,
                   ln(a.active::DOUBLE / p.active) AS net_growth_log
            FROM msp_active a JOIN msp_active p USING (region_id, need_id)
            WHERE p.snapshot_date = a.snapshot_date - INTERVAL 12 MONTH""")
        con.execute("""CREATE TABLE msp_survival_12m (cohort_date DATE, region_id VARCHAR, need_id VARCHAR,
                       cohort_n BIGINT, survived_n BIGINT, survival_share DOUBLE)""")
        con.executemany("INSERT INTO msp_survival_12m VALUES (?, ?, ?, ?, ?, ?)", [
            (D1, "77", "_all", 100, 80, 0.8), (D1, "78", "_all", 50, 30, 0.6),
            (D1, "77", "restaurants_cafes", 10, 7, 0.7), (D1, "78", "restaurants_cafes", 10, 5, 0.5),
        ])
    if "profile" in marts:
        con.execute("CREATE TABLE region_profile (region_id VARCHAR, indicator VARCHAR, year INTEGER, value DOUBLE)")
        con.executemany("INSERT INTO region_profile VALUES (?, ?, ?, ?)", [
            ("77", "population", 2024, 13_000_000), ("78", "population", 2024, 5_600_000),
            ("77", "population", 2025, 13_100_000), ("78", "population", 2025, 5_650_000),
            ("77", "urban_share", 2025, 98.6), ("78", "urban_share", 2025, 100.0),
            ("77", "income_per_capita", 2024, 120_000), ("78", "income_per_capita", 2024, 80_000),
        ])
    for (t,) in con.execute("SHOW TABLES").fetchall():
        con.execute(f"COPY {t} TO '{(path / (t + '.parquet')).as_posix()}' (FORMAT parquet)")
    con.close()
    (path / "manifest.json").write_text(json.dumps({
        "snapshot": sid, "created_at": "2026-10-14T03:00:00+00:00", "git_sha": sid[-7:] + "0" * 33,
        "methodology_version": "0.2.0", "taxonomy_version": "1.0.0", "data_date": D2,
        "sources": {"fns_rsmp": [{"snapshot_date": D2, "url": "x", "docs_parsed": 6}], "rosstat": [{}]},
        "backtest": None, "files": {},
    }), "utf-8")
    return path


@pytest.fixture
def marts(tmp_path: Path) -> Path:
    write_snapshot(tmp_path / "marts" / "current", "2026-10-abcdef1")
    return tmp_path / "marts"


@pytest.fixture
def client(marts: Path) -> TestClient:
    return TestClient(create_app(marts, CONFIG))


def close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9)
