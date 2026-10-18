"""T2.1: справочники, /api/meta, noindex и смена snapshot."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from conftest import CONFIG, write_snapshot
from rf_api.app import create_app


def test_meta(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    m = r.json()
    assert m["snapshot"] == "2026-10-abcdef1"
    assert m["beta"] is True and m["calibrated"] is False
    assert m["marts"] == ["msp_active", "msp_growth_12m", "msp_survival_12m", "region_profile"]
    assert m["sources"]["fns_rsmp"] == [{"snapshot_date": "2026-10-10", "docs_parsed": 6}]


def test_noindex_everywhere(client):
    for path in ("/api/meta", "/api/regions", "/api/health"):
        assert client.get(path).headers["X-Robots-Tag"] == "noindex, nofollow"
    assert client.post("/api/query", json={"metrics": ["x"]}).headers["X-Robots-Tag"] == "noindex, nofollow"


def test_refs(client):
    regions = client.get("/api/regions").json()["regions"]
    assert len(regions) == 89 and {"region_id", "name", "iso3166_2"} <= set(regions[0])
    needs = client.get("/api/needs").json()
    assert needs["taxonomy_version"] == "1.0.0" and len(needs["needs"]) == 51
    geo = client.get("/api/geo")
    assert geo.status_code == 200 and geo.headers["content-type"].startswith("application/geo+json")
    assert geo.json()["type"] == "FeatureCollection"
    sem = client.get("/api/metrics").json()
    assert "msp_active" in sem["metrics"] and "expr" not in sem["metrics"]["msp_active"]


def test_no_snapshot_503(tmp_path):
    c = TestClient(create_app(tmp_path, CONFIG))
    assert c.get("/api/health").status_code == 200
    r = c.get("/api/meta")
    assert r.status_code == 503 and r.json()["error"] == "no_snapshot"
    assert c.post("/api/query", json={"metrics": ["msp_active"]}).status_code == 503
    # Справочники не зависят от snapshot.
    assert c.get("/api/regions").status_code == 200


def test_snapshot_switch(tmp_path):
    a = write_snapshot(tmp_path / "2026-09-aaaaaaa", "2026-09-aaaaaaa")
    b = write_snapshot(tmp_path / "2026-10-bbbbbbb", "2026-10-bbbbbbb", scale=2)
    cur = tmp_path / "current"
    try:
        os.symlink(a.name, cur, target_is_directory=True)
    except OSError:
        pytest.skip("симлинки недоступны (Windows без прав)")
    c = TestClient(create_app(tmp_path, CONFIG))
    q = {"metrics": ["msp_active"]}
    assert c.post("/api/query", json=q).json()["rows"][0]["value"] == 1700
    tmp = tmp_path / "current.new"
    os.symlink(b.name, tmp, target_is_directory=True)
    os.replace(tmp, cur)  # как mv -T в deploy/publish-snapshot.sh
    body = c.post("/api/query", json=q).json()
    assert body["snapshot"] == "2026-10-bbbbbbb" and body["rows"][0]["value"] == 3400
    assert c.get("/api/meta").json()["snapshot"] == "2026-10-bbbbbbb"
