import datetime as dt
import json
from pathlib import Path

import openpyxl
import pyarrow.parquet as pq
import pytest

from rf_etl import cli
from rf_etl.rosstat import fetch, profile
from rf_etl.rosstat import parse as rp

ROOT = Path(__file__).resolve().parents[2]
REGIONS = rp.load_regions(ROOT / "config/geo/regions.csv")


@pytest.fixture(scope="module")
def names() -> rp.RegionNames:
    return rp.RegionNames(REGIONS)


@pytest.mark.parametrize("name, rid, without_ao", [
    ("Республика Адыгея", "01", False),
    ("Республика Северная Осетия – Алания", "15", False),
    ("Республика Северная Осетия-Алания", "15", False),
    ("Чувашская Республика", "21", False),
    ("Кемеровская область – Кузбасс", "42", False),
    ("Кемеровская область", "42", False),
    ("Ханты-Мансийский авт. округ – Югра", "86", False),
    ("Ханты - Мансийский автономный округ - Югра ", "86", False),
    ("Ямало-Ненецкий автономный округ", "89", False),
    ("Ненецкий автономный округ", "83", False),
    ("Архангельская область без автономии", "29", True),
    ("Архангельская область без Ненецкого автономного округа", "29", True),
    ("Тюменская область без автономных округов", "72", True),
    ("г. Москва", "77", False),
    ("г.Санкт-Петербург  ", "78", False),
    ("г. Севастополь", "92", False),
    ("Республика Саха (Якутия)", "14", False),
    ("Республика Татарстан", "16", False),
    ("Приморский край 2)", "25", False),
    ("Еврейская автономная область", "79", False),
    ("Московская область", "50", False),
    ("Российская Федеpация*", None, False),
    ("Центральный федеральный округ", None, False),
])
def test_region_names(names: rp.RegionNames, name: str, rid: str | None, without_ao: bool) -> None:
    assert names.resolve(name) == (rid, without_ao)


def test_by_region_prefers_without_ao(names: rp.RegionNames) -> None:
    res = rp.Parsed()
    rows = [("Архангельская область", 1), ("Ненецкий автономный округ", 2),
            ("Архангельская область без автономии", 3), ("Северо-Западный федеральный округ", 4)]
    assert rp.by_region(names, rows, res) == {"83": 2, "29": 3}
    assert res.unmatched == ["Северо-Западный федеральный округ"]


def test_okato_index_without_ao() -> None:
    idx = rp.okato_index(REGIONS)
    assert idx["11001000000"] == "29" and idx["71001000000"] == "72"
    assert idx["11100000000"] == "83" and idx["14000000000"] == "31"
    assert "11000000000" not in idx and "71000000000" not in idx


def _row(code: str, title: str = "") -> dict[str, object]:
    return {"extra_row_attrs": {"code": code}, "display_title": f"{code} {title}"}


def _showdata(path: Path, years: list[int], rows: list[dict[str, object]], cells: list[list[dict]]) -> Path:
    cols = [{"children": [{"period": f"{y}-01-01 00:00:00|-56"} for y in years]}]
    path.write_text(json.dumps({"headers": {"reportHeaders": {"row_header": rows, "col_header": cols}},
                                "data": {"reportData": {"data": cells}}}), "utf-8")
    return path


def test_parse_showdata_nested_conflict_empty(tmp_path: Path) -> None:
    rows = [{"display_title": "52 группа", "children": [_row("643"), _row("14000000000"), _row("11000000000"),
                                                          _row("11001000000")]}]
    cells = [[{"db_value": 74.6}, {}],
             [{"db_value": 67.2}, {"db_value": 67.4}],
             [{"db_value": 1.0}, {"db_value": 2.0}],
             [{"db_conflict": {"object_ids": "1,2"}}, {"db_value": 79.1}]]
    p = _showdata(tmp_path / "showdata_278932.json", [2019, 2020], rows, cells)
    res = rp.parse_showdata(p, "urban_share", rp.okato_index(REGIONS))
    got = {(o.region_id, o.year): o.value for o in res.obs}
    assert got == {("31", 2019): 67.2, ("31", 2020): 67.4, ("29", 2020): 79.1}
    assert res.conflicts == 1 and len(res.unmatched) == 2
    assert {o.source for o in res.obs} == {"showdata/278932"}


def test_parse_showdata_row_count_mismatch(tmp_path: Path) -> None:
    p = _showdata(tmp_path / "showdata_1.json", [2019], [_row("14000000000")], [])
    with pytest.raises(ValueError):
        rp.parse_showdata(p, "urban_share", {})


def _xlsx(path: Path, sheets: dict[str, list[list[object]]]) -> Path:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for r in rows:
            ws.append(r)
    wb.save(path)
    return path


def _polvozr(tmp: Path, year: int) -> Path:
    hdr = [["Численность населения"], [None], ["Всё население", "Всего", "моложе"]]
    total = hdr + [["Российская Федерация", 146_000_000, 1], ["Белгородская область", 1_552_417, 1],
                   ["Архангельская область", 1_127_780, 1], ["Ненецкий автономный округ", 42_503, 1],
                   ["Архангельская область без автономии", 1_085_277, 1], ["1 Мужчины в возрасте", None]]
    urban = hdr + [["Белгородская область", 1_041_000, 1], ["Ненецкий автономный округ", 31_000, 1],
                   ["Архангельская область без автономии", 850_000, 1]]
    return _xlsx(tmp / f"Chisl_polvozr_01-01-{year}_VPN-2020.xlsx",
                 {"М+Ж_Г+С": total, "М_Г+С": [], "Ж_Г+С": [], "М+Ж_Г": urban})


def test_parse_polvozr(tmp_path: Path, names: rp.RegionNames) -> None:
    res = rp.parse_polvozr(_polvozr(tmp_path, 2016), names)
    got = {(o.region_id, o.indicator): (o.year, o.value, o.computed) for o in res.obs}
    assert got[("31", "population")] == (2016, 1_552_417, False)
    assert got[("29", "population")] == (2016, 1_085_277, False)
    assert got[("31", "urban_share")] == (2016, round(100 * 1_041_000 / 1_552_417, 2), True)
    assert got[("83", "urban_share")][1] == round(100 * 31_000 / 42_503, 2)
    assert "Российская Федерация" in res.unmatched


def _okpopul(tmp: Path, year: int) -> Path:
    hdr = [[None], ["Оценка численности"], ["Городское и сельское", "Численность", "Изменения"]]
    total = hdr + [["Российская Федеpация*", 146_150_789, -30_861, -599_454, 568_593, 0, 146_119_928, 146_135_359],
                   ["Белгородская область", 1_500_659, -18_634, -11_708, -6_926, 0, 1_482_025, 1_491_342],
                   ["г. Москва", 13_149_803, 1, 1, 119_709, 0, 13_274_285, 13_200_000]]
    urban = hdr + [["Белгородская область", 980_243, 0, 0, 0, 0, 968_888, 974_566]]
    return _xlsx(tmp / f"OkPopul_Comp{year}_Site.xlsx", {"Всего": total, "Город": urban, "Село": []})


def test_parse_okpopul(tmp_path: Path, names: rp.RegionNames) -> None:
    res = rp.parse_okpopul(_okpopul(tmp_path, 2025), names)
    got = {(o.region_id, o.indicator, o.year): o.value for o in res.obs}
    assert got[("31", "population", 2024)] == 1_500_659
    assert got[("31", "population", 2025)] == 1_482_025
    assert got[("31", "urban_share", 2025)] == round(100 * 968_888 / 1_482_025, 2)
    assert got[("31", "migration_rate", 2024)] == round(1e4 * -6_926 / 1_491_342, 1)
    assert got[("77", "migration_rate", 2024)] == round(1e4 * 119_709 / 13_200_000, 1)
    assert ("77", "urban_share", 2025) not in got  # нет строки в листе «Город»


def _income(tmp: Path) -> Path:
    years = [None, "2011\nгод", "2012 год ", None, None, None, None, "2025 год 3)", None, None]
    sub = [None, None, "I кв.", "II кв.", "III кв.", "IV кв.", "год", "I кв.", "1 полугодие", "год"]
    rows = [[None], ["Содержание"], ["Среднедушевые денежные доходы, руб./месяц 1)"], [None], years, sub,
            ["Российская Федерация", 20772, 19106, 22573, 23262, 27964, 23193, 1, 1, 66203],
            ["Белгородская область", 18796, 1, 1, 1, 1, 18960, 1, 1, 55000],
            ["Республика Крым", None, None, None, None, None, None, 1, 1, 40000],
            ["1) Сноска", None]]
    return _xlsx(tmp / "urov_10subg_1pg2026.xlsx", {"Содержание": [], "СДД_субъекты": rows})


def test_parse_income_annual_only(tmp_path: Path, names: rp.RegionNames) -> None:
    res = rp.parse_income(_income(tmp_path), names)
    got = {(o.region_id, o.year): (o.value, o.provisional) for o in res.obs}
    assert got == {("31", 2011): (18796, False), ("31", 2012): (18960, False), ("31", 2025): (55000, True),
                   ("91", 2025): (40000, True)}


def test_expected_year() -> None:
    pop, mig = profile.BY_ID["population"], profile.BY_ID["migration_rate"]
    assert profile.expected_year(pop, dt.date(2026, 10, 17)) == 2026
    assert profile.expected_year(pop, dt.date(2026, 4, 30)) == 2025  # 1 января 2026 + 4 мес. ещё не прошло
    assert profile.expected_year(mig, dt.date(2026, 10, 17)) == 2025
    assert profile.expected_year(mig, dt.date(2026, 5, 31)) == 2024


def test_select_priority_and_first_year() -> None:
    o = rp.Obs
    obs = [o("31", "urban_share", 2019, 67.0, "polvozr", "a", computed=True),
           o("31", "urban_share", 2019, 67.2, "showdata", "b"),
           o("31", "urban_share", 2015, 66.0, "polvozr", "a"),
           o("31", "population", 2024, 1.0, "polvozr", "a"),
           o("31", "population", 2024, 2.0, "okpopul", "c")]
    got = {(r.indicator, r.year): r.value for r in profile.select(obs)}
    assert got == {("urban_share", 2019): 67.2, ("population", 2024): 2.0}


def _raw(tmp: Path) -> Path:
    raw = tmp / "raw"
    raw.mkdir()
    _showdata(raw / "showdata_278932.json", [2019, 2025], [_row("14000000000")],
              [[{"db_value": 67.0}, {"db_value": 66.4}]])
    _showdata(raw / "showdata_279008.json", [2017, 2023], [_row("14000000000"), _row("45000000000")],
              [[{"db_value": 12.0}, {"db_value": -5.0}], [{"db_value": 30.0}, {"db_value": 40.0}]])
    _polvozr(raw, 2016)
    _okpopul(raw, 2025)
    _income(raw)
    (raw / fetch.FETCH_JSON).write_text(json.dumps([{"name": "x", "url": "u"}]), "utf-8")
    return raw


def test_build_profile(tmp_path: Path) -> None:
    out = tmp_path / "marts"
    rep = profile.build(_raw(tmp_path), ROOT / "config/geo/regions.csv", out, dt.date(2026, 10, 17))
    prof = {(r["region_id"], r["indicator"], r["year"]): r
            for r in pq.read_table(out / "region_profile.parquet").to_pylist()}
    assert prof[("31", "urban_share", 2016)]["kind"] == "polvozr"
    assert prof[("31", "urban_share", 2025)]["value"] == 66.4  # showdata важнее посчитанной из OkPopul
    assert prof[("31", "migration_rate", 2024)]["kind"] == "okpopul"
    assert prof[("31", "income_per_capita", 2025)]["provisional"] is True
    assert prof[("31", "population", 2016)]["unit"] == "чел."
    st = {(r["region_id"], r["indicator"]): r for r in pq.read_table(out / "region_profile_status.parquet").to_pylist()}
    assert len(st) == len(REGIONS) * len(profile.INDICATORS)
    assert st[("31", "income_per_capita")]["stale"] is False  # 2025 при ожидаемом 2025
    assert st[("31", "population")]["stale"] is True  # есть 2025, ожидается 2026
    assert st[("31", "population")]["last_year"] == 2025
    assert st[("93", "population")]["last_year"] is None and st[("93", "population")]["stale"] is True
    assert prof[("31", "population", 2025)]["stale"] is True
    assert "93" in rep["regions_without_data"]
    assert rep["sources"] == [{"name": "x", "url": "u"}]
    assert (out / "region_profile.csv").exists() and (out / "region_profile_report.json").exists()


def test_cli_region_profile(tmp_path: Path) -> None:
    raw = _raw(tmp_path)
    assert cli.main(["region-profile", "--raw-dir", str(raw), "--out-dir", str(tmp_path / "m"),
                     "--regions", str(ROOT / "config/geo/regions.csv"), "--asof", "2026-10-17"]) == 0


def test_discover_links() -> None:
    html = ('<a href="/storage/mediabank/urov_10subg_1pg2026.xlsx">x</a>'
            '<a href="/storage/mediabank/OkPopul_Comp2024_Site.xlsx"></a>'
            '<a href="/storage/mediabank/OkPopul_Comp2025_Site.xlsx"></a>')
    assert fetch.discover_income(html) == "urov_10subg_1pg2026.xlsx"
    assert fetch.discover_okpopul(html) == "OkPopul_Comp2025_Site.xlsx"
    assert fetch.discover_income("") is None


def test_ssl_context_loads_russian_ca() -> None:
    ctx = fetch.ssl_context(ROOT / fetch.CA_DIR)
    names = {dict(x[0] for x in c["subject"]).get("commonName") for c in ctx.get_ca_certs()}
    assert {"Russian Trusted Root CA", "Russian Trusted Sub CA"} <= names


def test_fetch_rejects_html_instead_of_xlsx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetch, "_get", lambda url, timeout=120: b"<html>blocked</html>")
    with pytest.raises(ValueError, match="не xlsx"):
        fetch.fetch(tmp_path, [fetch.Target("a.xlsx", "https://example.invalid/a.xlsx")])
