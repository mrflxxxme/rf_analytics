import datetime as dt
import math
import zipfile
from pathlib import Path

import duckdb
import pytest

from rf_etl import cli
from rf_etl.rsmp import marts, parse, versions

ROOT = Path(__file__).resolve().parents[2]


def _doc(inn: str, region: str, okved: str, incl: str, snap: str, new: bool = False, ip: bool = False,
         ver: str = "2014") -> str:
    who = (f'<ИПВклМСП ИННФЛ="{inn}" ОГРНИП="1"><ФИОИП Фамилия="X" Имя="Y"/></ИПВклМСП>' if ip
           else f'<ОргВклМСП НаимОрг="ООО" ИННЮЛ="{inn}" ОГРН="1"/>')
    return (f'<Документ ИдДок="{inn}" ДатаСост="{snap}" ДатаВклМСП="{incl}" ВидСубМСП="{2 if ip else 1}" '
            f'КатСубМСП="1" ПризНовМСП="{1 if new else 2}">{who}'
            f'<СведМН КодРегион="{region}"><Регион Тип="Г" Наим="Москва"/></СведМН>'
            f'<СвОКВЭД><СвОКВЭДОсн КодОКВЭД="{okved}" НаимОКВЭД="name {okved}" ВерсОКВЭД="{ver}"/>'
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
        _doc("7707", "81", "56.10", "10.08.2016", "10.03.2023"),  # старый код региона, старая ДатаСост
        _doc("7708", "77", "56.10", "10.08.2016", s1, ver="2001"),  # ОКВЭД-2001: только '_all'
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
    for name, docs, date in (("a", snap1, dt.date(2024, 10, 10)), ("b", snap2, None)):
        z = _zip(tmp_path / f"{name}.zip", docs)
        st = parse.parse_zip(z, out / f"rsmp_{name}.parquet", date)
        assert st.docs_parsed == st.docs_declared == len(docs)
    return out


def test_parse_has_no_personal_names(slim: Path):
    cols = duckdb.sql(f"SELECT * FROM '{slim}/rsmp_a.parquet' LIMIT 1").columns
    assert set(cols) == {f.name for f in parse.SCHEMA}
    row = duckdb.sql(f"SELECT * FROM '{slim}/rsmp_a.parquet' WHERE inn='7702'").fetchone()
    assert row == (dt.date(2024, 10, 10), "7702", 1, 1, dt.date(2024, 9, 1), True, "77", "56.10", "2014")
    stale = duckdb.sql(f"SELECT snapshot_date FROM '{slim}/rsmp_a.parquet' WHERE inn='7707'").fetchone()
    assert stale == (dt.date(2024, 10, 10),)  # дата снимка из имени файла, а не ДатаСост


def test_marts(slim: Path, tmp_path: Path):
    out = tmp_path / "marts"
    rep = marts.build(slim, ROOT / "config" / "taxonomy.yaml", ROOT / "config" / "geo" / "regions.csv", out)
    q = lambda sql: duckdb.sql(sql.replace("$", str(out))).fetchall()  # noqa: E731

    assert q("SELECT active FROM '$/msp_active.parquet' WHERE snapshot_date='2025-10-10' "
             "AND region_id='77' AND need_id='restaurants_cafes'") == [(3,)]
    assert q("SELECT active FROM '$/msp_active.parquet' WHERE snapshot_date='2024-10-10' "
             "AND region_id='77' AND need_id='_all'") == [(5,)]
    assert q("SELECT need_id, active FROM '$/msp_active.parquet' WHERE snapshot_date='2024-10-10' "
             "AND region_id='59' ORDER BY 1") == [("_all", 1), ("restaurants_cafes", 1)]
    assert rep["legacy_regions_mapped"] == [("81", 1)]

    (g,) = q("SELECT net_growth_log FROM '$/msp_growth_12m.parquet' "
             "WHERE region_id='77' AND need_id='restaurants_cafes'")
    assert math.isclose(g[0], math.log(3 / 2))

    surv = q("SELECT need_id, cohort_n, survived_n FROM '$/msp_survival_12m.parquet' "
             "WHERE region_id='77' ORDER BY need_id")
    assert surv == [("_all", 2, 1), ("beauty_salons", 1, 0), ("restaurants_cafes", 1, 1)]
    assert rep["unknown_regions"] == []
    assert len(rep["missing_regions"]) == 86  # есть 77, 50 и 59 (из старого кода 81)


def test_parse_tolerates_bad_dates(tmp_path: Path):
    docs = [_doc(f"77{i:02d}", "77", "56.10", "10.08.2016", "10.10.2025") for i in range(4)]
    docs[1] = docs[1].replace('ДатаВклМСП="10.08.2016"', 'ДатаВклМСП="31.02.2016"')
    st = parse.parse_zip(_zip(tmp_path / "bad.zip", docs), tmp_path / "bad.parquet", dt.date(2025, 10, 10))
    assert st.docs_parsed == 4 and st.bad_dates == 1
    incl = duckdb.sql(f"SELECT date_incl FROM '{tmp_path}/bad.parquet' WHERE inn='7701'").fetchone()
    assert incl == (None,)  # строка осталась, битое поле пустое
    assert not parse.is_complete(st)  # 1 из 4 — выше допуска 0,1%
    st.docs_declared = st.docs_parsed = 10_000
    assert parse.is_complete(st)


def test_marts_duckdb_memory_limit(tmp_path: Path):
    con = marts.connect(tmp_path)
    limit = con.execute("SELECT current_setting('memory_limit')").fetchone()[0]
    assert limit.endswith("GiB") and float(limit.split()[0]) <= 3


def test_check_download_rejects_stub(tmp_path: Path):
    ok = _zip(tmp_path / "ok.zip", [_doc("7701", "77", "56.10", "10.08.2016", "10.10.2025")] * 2)
    cli._check_download(ok, ok.stat().st_size)
    stub = tmp_path / "stub.zip"
    stub.write_bytes(b"<html>busy</html>")
    with pytest.raises(OSError, match="не ZIP"):
        cli._check_download(stub, 0)
    with pytest.raises(OSError, match="получено"):
        cli._check_download(ok, ok.stat().st_size + 1)


def test_snapshot_name_dates():
    assert versions.parse_date("01102017") == dt.date(2017, 1, 10)
    assert versions.parse_date("10102026") == dt.date(2026, 10, 10)
    assert versions.parse_date("10092026") == dt.date(2026, 9, 10)
    html = ('<a href="data-10102026-structure-12052026.zip"></a>'
            '<a href="data-01102017-structure-08012016.zip"></a>'
            '<a href="data-10102025-structure-10062025.zip"></a>')
    snaps = versions.parse_listing(html + '<a href="data-10102026-structure-30012026.zip"></a>')
    assert [s.date.year for s in versions.select(snaps, "annual")] == [2025, 2026]
    assert versions.select(snaps, "latest")[0].url.endswith("data-10102026-structure-12052026.zip")
