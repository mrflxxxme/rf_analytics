"""Индексируемый слой фактов (T2.5): страницы из витрин snapshot, sitemap, без noindex."""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import duckdb
import pytest

from rf_etl.cli import main
from rf_etl.facts import data, render

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"
D0, D1, D2 = "2024-10-10", "2025-10-10", "2026-10-10"


@pytest.fixture(scope="module")
def marts(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("snap")
    con = duckdb.connect()
    con.execute("CREATE TABLE msp_active (snapshot_date DATE, region_id VARCHAR, need_id VARCHAR, active BIGINT)")
    rows = []
    for d, k in ((D0, 1.0), (D1, 1.1), (D2, 1.21)):
        for reg, size in (("77", 1000), ("78", 400), ("01", 60)):
            rows += [(d, reg, "restaurants_cafes", int(size * k)), (d, reg, "bars_pubs", int(size / 10)),
                     (d, reg, "_all", int(size * k) + int(size / 10) + 500)]
    rows.append((D2, "77", "<script>", 5))  # не из таксономии — на страницы не попадает
    con.executemany("INSERT INTO msp_active VALUES (?, ?, ?, ?)", rows)
    con.execute("""CREATE TABLE msp_growth_12m AS
        SELECT a.snapshot_date, a.region_id, a.need_id, a.active, p.active AS active_prev_12m,
               ln(a.active::DOUBLE / p.active) AS net_growth_log
        FROM msp_active a JOIN msp_active p USING (region_id, need_id)
        WHERE p.snapshot_date = a.snapshot_date - INTERVAL 12 MONTH""")
    con.execute("""CREATE TABLE msp_survival_12m AS
        SELECT DATE '2025-10-10' AS cohort_date, region_id, need_id, 100::BIGINT AS cohort_n, 70::BIGINT AS survived_n,
               0.7 AS survival_share FROM msp_active WHERE snapshot_date = DATE '2026-10-10'""")
    for (t,) in con.execute("SHOW TABLES").fetchall():
        con.execute(f"COPY {t} TO '{(path / (t + '.parquet')).as_posix()}' (FORMAT parquet)")
    (path / "manifest.json").write_text(json.dumps({
        "snapshot": "2026-10-abcdef0", "methodology_version": "0.2.0", "taxonomy_version": "1.0.0", "data_date": D2}))
    return path


@pytest.fixture(scope="module")
def site(marts: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("site")
    assert main(["facts", "--marts-dir", str(marts), "--out-dir", str(out), "--site-url", "https://nishemer.ru/",
                 "--config-dir", str(CONFIG), "--methodology", str(ROOT / "docs" / "03-methodology.md"),
                 "--today", "2026-10-19"]) == 0
    return out


def test_measured_numbers_from_marts(marts: Path) -> None:
    f = data.load(marts, CONFIG)
    n = f.needs["restaurants_cafes"]
    assert n.active == 1210 + 484 + 72
    assert n.series[0] == (dt.date(2024, 10, 10), 1000 + 400 + 60)
    # Рост по РФ — из сумм компонентов: ln(Σt / Σt−12).
    assert n.growth == pytest.approx(math.log((1210 + 484 + 72) / (1100 + 440 + 66)))
    assert [r.key for r in n.top_regions] == ["77", "78", "01"]
    assert "01" in {r.key for r in n.fastest_regions}  # база 66 ≥ MIN_BASE
    assert "01" not in {r.key for r in f.needs["bars_pubs"].fastest_regions}  # база 6 < MIN_BASE
    assert n.survival == pytest.approx(0.7)
    assert set(f.needs) == {"restaurants_cafes", "bars_pubs"}
    assert f.region_order == ["01", "77", "78"]  # порядок Конституции, только регионы с данными


def test_rubrics_are_deterministic(marts: Path) -> None:
    f = data.load(marts, CONFIG)
    assert data.niche_of_month(f) == "restaurants_cafes"  # +10 % против 0 %
    weeks = {data.region_of_week(f, dt.date(2026, 10, 19) + dt.timedelta(weeks=i)) for i in range(3)}
    assert weeks == {"01", "77", "78"}  # ротация обходит все регионы


def test_pages_sitemap_robots(site: Path) -> None:
    for p in ("index.html", "fakty/nisha/restaurants_cafes/index.html", "fakty/region/77/index.html",
              "fakty/nisha-mesyaca/index.html", "fakty/region-nedeli/index.html", "metodologiya/index.html",
              "facts.css", "robots.txt"):
        assert (site / p).is_file(), p
    html = (site / "fakty/nisha/restaurants_cafes/index.html").read_text("utf-8")
    assert "noindex" not in html  # D27: страницы фактов индексируются
    assert '<link rel="canonical" href="https://nishemer.ru/fakty/nisha/restaurants_cafes/">' in html
    assert "1 766" in html and "+10,0 %" in html
    assert "от Кирилла Уклонского" in html  # подвал D28
    assert "<script" not in html.lower()
    locs = [e.text for e in ET.parse(site / "sitemap.xml").getroot().iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    assert "https://nishemer.ru/" in locs and "https://nishemer.ru/metodologiya/" in locs
    assert not any("/karta" in u or "/api" in u for u in locs)
    robots = (site / "robots.txt").read_text("utf-8")
    assert "Disallow: /karta/" in robots and "Sitemap: https://nishemer.ru/sitemap.xml" in robots


def test_every_internal_link_resolves(site: Path) -> None:
    pages = {"/" + str(p.relative_to(site).parent.as_posix()).strip(".") for p in site.rglob("index.html")}
    pages = {p if p.endswith("/") else p + "/" for p in pages}
    for p in site.rglob("index.html"):
        for href in re.findall(r'href="(/[^"]*)"', p.read_text("utf-8")):
            if href.startswith(("/karta/", "/facts.css")):
                continue
            assert href in pages, (p, href)


def test_pct_format() -> None:
    assert render.pct(math.log(0.9)) == "−10,0 %"
    assert render.pct(None) == "нет данных"
