from pathlib import Path

import pytest

from rf_etl import taxonomy as tx

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def tax() -> tx.Taxonomy:
    return tx.load(ROOT / "config" / "taxonomy.yaml")


def test_loads_and_has_about_50_needs(tax):
    active = [n for n in tax.needs if n.status == "active"]
    assert 40 <= len(active) <= 70


def test_mapping_by_longest_prefix(tax):
    assert tx.need_for_okved(tax, "56.10.1") == "restaurants_cafes"
    assert tx.need_for_okved(tax, "96.02") == "beauty_salons"  # группа без подкласса
    assert tx.need_for_okved(tax, "96.02.1") == "beauty_salons"
    assert tx.need_for_okved(tax, "45.20.3") == "car_service"
    assert tx.need_for_okved(tax, "85.42") is None  # группа шире, чем коды потребности (85.42.1)
    assert tx.need_for_okved(tax, "56.101") is None  # префикс только по границе кода
    assert tx.need_for_okved(tax, None) is None


def test_overlap_rejected():
    bad = tx.Taxonomy(version="0", status="draft", needs=[
        tx.Need(id="aaa", name="a", okved=["56.10"]),
        tx.Need(id="bbb", name="b", okved=["56.10.1"]),
    ])
    with pytest.raises(ValueError, match="пересекаются"):
        tx.validate(bad)


def test_bad_ids_rejected():
    with pytest.raises(ValueError):
        tx.Need(id="Bad-Id", name="x", okved=["56.10"])
    with pytest.raises(ValueError):
        tx.Need(id="okid", name="x", okved=["56,10"])
