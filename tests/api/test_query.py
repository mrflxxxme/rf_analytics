"""T2.1: валидация query-spec по семантическому слою и исполнение над витринами snapshot."""

from __future__ import annotations

import math

import pytest

from conftest import CONFIG, D1, D2, close
from rf_api import semantic


def post(client, spec):
    return client.post("/api/query", json=spec)


def rows(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()["rows"]


# --- семантический слой ---------------------------------------------------------------

def test_metrics_yaml_valid():
    sem = semantic.load(CONFIG / "metrics.yaml")
    assert {"msp_active", "msp_growth_12m", "msp_survival_12m", "population", "urban_share",
            "migration_rate", "income_per_capita"} <= set(sem.metrics)
    assert all(m.kind == "measured" for m in sem.metrics.values())  # D27: на M1 только факты


def test_semantic_rejects_bad_identifier(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text((CONFIG / "metrics.yaml").read_text("utf-8").replace("mart: msp_active", "mart: msp_active; DROP"),
                 "utf-8")
    with pytest.raises(ValueError):
        semantic.load(p)


# --- отказ: метрика / измерение / значение вне белого списка ---------------------------

def test_unknown_metric_rejected(client):
    r = post(client, {"metrics": ["msp_active", "revenue_forecast"]})
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "unknown_metric"
    assert "revenue_forecast" in body["message"]
    assert "msp_active" in body["allowed"]


def test_sql_in_metric_rejected(client):
    r = post(client, {"metrics": ["msp_active; DROP TABLE msp_active"]})
    assert r.status_code == 422 and r.json()["error"] == "unknown_metric"


@pytest.mark.parametrize("spec, code", [
    ({"metrics": ["msp_active"], "group_by": ["okved"]}, "unknown_dimension"),
    ({"metrics": ["msp_active"], "group_by": ["region_id", "region_id"]}, "duplicate_dimension"),
    ({"metrics": ["msp_active", "msp_active"]}, "duplicate_metric"),
    ({"metrics": ["msp_active"], "filters": [{"dim": "inn", "values": ["1"]}]}, "unknown_dimension"),
    ({"metrics": ["msp_active"], "filters": [{"dim": "period", "values": ["2026"]}]}, "unknown_dimension"),
    ({"metrics": ["msp_active"], "filters": [{"dim": "region_id", "values": ["77' OR 1=1 --"]}]}, "unknown_value"),
    ({"metrics": ["msp_active"], "filters": [{"dim": "need_id", "values": ["casino"]}]}, "unknown_value"),
    ({"metrics": ["msp_active"], "filters": [{"dim": "region_id", "values": ["77"]},
                                             {"dim": "region_id", "values": ["78"]}]}, "duplicate_filter"),
    ({"metrics": ["population"], "group_by": ["need_id"]}, "dimension_not_in_metric"),
    ({"metrics": ["urban_share"]}, "no_rollup"),
    ({"metrics": ["msp_active"], "filters": [{"dim": "need_id", "values": ["_all", "bars_pubs"]}]}, "double_count"),
    ({"metrics": ["msp_active"], "period": {"from": "2026-01-01", "to": "2025-01-01"}}, "bad_period"),
    ({"metrics": ["msp_active"], "map_binding": {"metric": "population"}}, "bad_map_binding"),
    ({"metrics": ["msp_active"], "map_binding": {"metric": "msp_active"}}, "bad_map_binding"),
])
def test_semantic_validation(client, spec, code):
    r = post(client, spec)
    assert r.status_code == 422, r.text
    assert r.json()["error"] == code


@pytest.mark.parametrize("spec", [
    {},
    {"metrics": []},
    {"metrics": ["msp_active"] * 5},
    {"metrics": ["msp_active"], "sql": "SELECT 1"},
    {"metrics": ["msp_active"], "compare_to": "rf"},
    {"metrics": ["msp_active"], "limit": 0},
    {"metrics": ["msp_active"], "limit": 10**6},
    {"metrics": ["msp_active"], "period": {"from": "вчера"}},
    {"metrics": ["msp_active"], "filters": [{"dim": "region_id", "values": []}]},
    {"metrics": ["msp_active"], "filters": [{"dim": "region_id", "values": ["77"], "op": "like"}]},
])
def test_schema_validation(client, spec):
    assert post(client, spec).status_code == 422


# --- исполнение -------------------------------------------------------------------------

def test_latest_total_uses_all_default(client):
    r = post(client, {"metrics": ["msp_active"]})
    body = r.json()
    assert body["rows"] == [{"metric": "msp_active", "period": D2, "value": 1700}]  # _all, не сумма с нишами
    assert body["defaults"] == {"msp_active": {"need_id": "_all"}}
    assert body["snapshot"] == "2026-10-abcdef1"


def test_by_region_for_need(client):
    out = rows(post(client, {"metrics": ["msp_active"], "group_by": ["region_id"],
                             "filters": [{"dim": "need_id", "values": ["restaurants_cafes"]}],
                             "map_binding": {"metric": "msp_active", "dim": "region_id"}}))
    assert [(r["region_id"], r["value"]) for r in out] == [("77", 120), ("78", 40)]


def test_series_and_period_to(client):
    out = rows(post(client, {"metrics": ["msp_active"], "group_by": ["period"],
                             "filters": [{"dim": "region_id", "values": ["77"]}]}))
    assert [(r["period"], r["value"]) for r in out] == [(D1, 1000), (D2, 1100)]
    out = rows(post(client, {"metrics": ["msp_active"], "period": {"to": "2026-01-01"}}))
    assert out == [{"metric": "msp_active", "period": D1, "value": 1500}]
    out = rows(post(client, {"metrics": ["msp_active"], "group_by": ["period"], "period": {"from": "2026-01-01"}}))
    assert [r["period"] for r in out] == [D2]


def test_growth_recomputed_from_sums(client):
    out = rows(post(client, {"metrics": ["msp_growth_12m"],
                             "filters": [{"dim": "need_id", "values": ["restaurants_cafes", "bars_pubs"]}]}))
    assert close(out[0]["value"], math.log((120 + 12 + 40 + 6) / (100 + 10 + 50 + 5)))


def test_survival_weighted(client):
    out = rows(post(client, {"metrics": ["msp_survival_12m"]}))
    assert out == [{"metric": "msp_survival_12m", "period": D1, "value": pytest.approx(110 / 150)}]


def test_profile_metrics(client):
    out = rows(post(client, {"metrics": ["population", "urban_share"], "group_by": ["region_id"]}))
    pop = {r["region_id"]: r["value"] for r in out if r["metric"] == "population"}
    assert pop == {"77": 13_100_000, "78": 5_650_000}
    assert all(r["period"] == 2025 for r in out)
    out = rows(post(client, {"metrics": ["income_per_capita"],
                             "filters": [{"dim": "region_id", "values": ["78"]}]}))
    assert out == [{"metric": "income_per_capita", "period": 2024, "value": 80_000}]
    out = rows(post(client, {"metrics": ["population"], "group_by": ["period"], "period": {"to": "2024-12-31"}}))
    assert out == [{"metric": "population", "period": 2024, "value": 18_600_000}]


def test_limit_truncates(client):
    body = post(client, {"metrics": ["msp_active"], "group_by": ["region_id", "need_id"], "limit": 2}).json()
    assert len(body["rows"]) == 2 and body["truncated"] is True


def test_missing_mart_409(tmp_path):
    from fastapi.testclient import TestClient

    from conftest import write_snapshot
    from rf_api.app import create_app
    write_snapshot(tmp_path / "current", "2026-10-abcdef2", marts=("msp",))
    c = TestClient(create_app(tmp_path, CONFIG))
    assert post(c, {"metrics": ["msp_active"]}).status_code == 200
    r = post(c, {"metrics": ["population"]})
    assert r.status_code == 409 and r.json()["error"] == "mart_missing"
