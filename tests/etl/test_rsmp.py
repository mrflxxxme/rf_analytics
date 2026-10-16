import datetime as dt
import math
import zipfile
from pathlib import Path

import duckdb
import pytest

from rf_etl.rsmp import marts, parse, versions

ROOT = Path(__file__).resolve().parents[2]


def _doc(inn: str, region: str, okved: str, incl: str, snap: str, new: bool = False, ip: bool = False) -> str:
    who = (f'<ИПВклМСП ИННФЛ="{inn}" ОГРНИП="1"><ФИОИП Фамилия="X" Имя="Y"/></ИПВклМСП>' if ip
           else f'<ОргВклМСП НаимОрг="ООО" ИННЮЛ="{inn}" ОГРН="1"/>')
    return (f'<Документ ИдДок="{inn}" ДатаСост="{snap}" ДатаВклМСП="{incl}" ВидСубМСП="{2 if ip else 1}" '
            f'КатСубМСП="1" ПризНовМСП="{1 if new else 2}">{who}'
            f'<СведМН КодРегион="{region}"><Регион Тип="Г" Наим="Москва"/></СведМН>'
            f'<СвОКВЭД><СвОКВЭДОсн КодОКВЭД="{okved}" НаимОКВЭД="name {okved}" ВерсОКВЭД="2014"/>'
            f'<СвОКВЭДДоп КодОКВЭД="47.11" НаимОКВЭД="доп" ВерсОКВЭД="2014"/></СвОКВЭД></Документ>')


def _zip(path: Path, docs: list[str]) -> Path:
    half = len(docs) // 2
    with zipfile.ZipFile(path, "w") as z:
        for i, part in enumerate((docs[:half], docs[half:])):
            body = "".join(part)
            z.writestr(f"VO_RRMSPSV_{i}.xml", f'<?xml version="1.0" encoding="utf-8"?>'
                       f'<Файл ИдФайл="{i}" ВерсФорм="4.06" ТипИнф="РЕЕСТРМСП" КолДок="{len(part)}">'
                       f'<ИдОтпр><ФИООтв Фамилия="A" Имя="B"/></ИдОтпр>{body}</Файл>')
    return path


@pytest.fixture
def slim(tmp_path: Path) -> Path:
    s1, s2 = "10.10.2024", "10.10.2025"
    snap1 = [
        _doc("7701", "77", "56.10.1", "10.08.2016", s1),
        _doc("7702", "77", "56.10", "01.09.2024", s1, new=True),   # когорта, выживет
        _doc("7703", "77", "96.02.1", "15.08.2024", s1, new=True),  # когорта, закроется
        _doc("7704", "77", "96.02.1", "10.08.2024", s1),            # не новый: вне когорты
        _doc("500000000001", "50", "01.11", "10.08.2016", s1, ip=True),  # вне таксономии
    ]
    snap2 = [
        _doc("7701", "77", "56.10.1", "10.08.2016", s2),
        _doc("7702", "50", "56.10", "01.09.2024", s2, new=True),  # переехал — всё равно выжил
        _doc("7705", "77", "56.10", "01.10.2025", s2, new=True),
        _doc("7706", "77", "56.10", "01.10.2025", s2, new=True),
        _doc("7704", "77", "96.02.1", "10.08.2024", s2),
    ]
    out = tmp_path / "slim"
    out.mkdir()
    for name, docs in (("a", snap1), ("b", snap2)):
        z = _zip(tmp_path / f"{name}.zip", docs)
        st = parse.parse_zip(z, out / f"rsmp_{name}.parquet")
        assert st.docs_parsed == st.docs_declared == 5
    return out


def test_parse_has_no_personal_names(slim: Path):
    cols = duckdb.sql(f"SELECT * FROM '{slim}/rsmp_a.parquet' LIMIT 1").columns
    assert set(cols) == {f.name for f in parse.SCHEMA}
    row = duckdb.sql(f"SELECT * FROM '{slim}/rsmp_a.parquet' WHERE inn='7702'").fetchone()
    assert row == (dt.date(2024, 10, 10), "7702", 1, 1, dt.date(2024, 9, 1), True, "77", "56.10")


def test_marts(slim: Path, tmp_path: Path):
    out = tmp_path / "marts"
    rep = marts.build(slim, ROOT / "config" / "taxonomy.yaml", ROOT / "config" / "geo" / "regions.csv", out)
    q = lambda sql: duckdb.sql(sql.replace("$", str(out))).fetchall()  # noqa: E731

    assert q("SELECT active FROM '$/msp_active.parquet' WHERE snapshot_date='2025-10-10' "
             "AND region_id='77' AND need_id='restaurants_cafes'") == [(3,)]
    assert q("SELECT active FROM '$/msp_active.parquet' WHERE snapshot_date='2024-10-10' "
             "AND region_id='77' AND need_id='_all'") == [(4,)]

    (g,) = q("SELECT net_growth_log FROM '$/msp_growth_12m.parquet' "
             "WHERE region_id='77' AND need_id='restaurants_cafes'")
    assert math.isclose(g[0], math.log(3 / 2))

    surv = q("SELECT need_id, cohort_n, survived_n FROM '$/msp_survival_12m.parquet' "
             "WHERE region_id='77' ORDER BY need_id")
    assert surv == [("_all", 2, 1), ("hair_barbershops", 1, 0), ("restaurants_cafes", 1, 1)]
    assert rep["unknown_regions"] == []
    assert len(rep["missing_regions"]) == 87


def test_snapshot_name_dates():
    assert versions.parse_date("01102017") == dt.date(2017, 1, 10)
    assert versions.parse_date("10102026") == dt.date(2026, 10, 10)
    assert versions.parse_date("10092026") == dt.date(2026, 9, 10)
    html = ('<a href="data-10102026-structure-12052026.zip"></a>'
            '<a href="data-01102017-structure-08012016.zip"></a>'
            '<a href="data-10102025-structure-10062025.zip"></a>')
    snaps = versions.parse_listing(html)
    assert [s.date.year for s in versions.select(snaps, "annual")] == [2025, 2026]
    assert versions.select(snaps, "latest")[0].url.endswith("data-10102026-structure-12052026.zip")
