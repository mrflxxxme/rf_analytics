import csv
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_geo", ROOT / "scripts" / "build_geo.py")
build_geo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_geo)


def regions() -> list[dict[str, str]]:
    with open(ROOT / "config" / "geo" / "regions.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_89_unique_two_digit_ids():
    rows = regions()
    ids = [r["region_id"] for r in rows]
    assert len(rows) == 89
    assert len(set(ids)) == 89
    assert all(len(i) == 2 and i.isdigit() for i in ids)
    assert len({r["iso3166_2"] for r in rows}) == 89


def test_known_codes():
    by_id = {r["region_id"]: r for r in regions()}
    assert by_id["77"]["okato"] == "45"
    assert by_id["83"]["oktmo"] == "118"
    assert by_id["86"]["oktmo"] == "718"
    assert by_id["89"]["oktmo"] == "719"
    assert by_id["91"]["iso3166_2"] == "UA-43"


def test_names_clean():
    for r in regions():
        assert "\xa0" not in r["name"] and "  " not in r["name"], r["name"]


def test_geojson_matches_regions():
    path = ROOT / "config" / "geo" / "regions.geojson"
    assert path.stat().st_size <= 2_000_000
    with open(path, encoding="utf-8") as f:
        feats = json.load(f)["features"]
    by_id = {r["region_id"]: r["name"] for r in regions()}
    assert len(feats) == 89
    assert {f["properties"]["region_id"]: f["properties"]["name"] for f in feats} == by_id
    assert all(set(f["properties"]) == {"region_id", "name"} for f in feats)


def _feat(iso, osm_id, coords, **tags):
    props = {"@type": "relation", "@id": osm_id, "boundary": "administrative",
             "admin_level": "4", "ISO3166-2": iso, **tags}
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Polygon", "coordinates": coords}}


def test_pick_matches_iso_and_name_and_dedupes():
    regs = {r["region_id"]: r for r in regions()}
    small = [[[0, 0], [1, 0], [1, 1], [0, 0]]]
    big = [[[0, 0], [1, 0], [1, 1], [0.5, 1.5], [0, 1], [0, 0]]]
    feats = [
        _feat("RU-MOW", 1, small),
        _feat("", 2, small, name="Республика Крым"),
        _feat("UA-43", 3, big),  # дубль Крыма из украинской выгрузки — побеждает больший
        _feat("RU-SPE", 4, small, admin_level="6"),  # не тот уровень
    ]
    chosen, missing = build_geo.pick(feats, regs)
    assert set(chosen) == {"77", "91"}
    assert chosen["91"]["_osm_id"] == 3
    assert "78" in missing and len(missing) == 87
