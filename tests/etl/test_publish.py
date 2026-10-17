"""T1.4: manifest.json снимка, fetcher, переключение current на сервере."""

import datetime as dt
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import duckdb
import pytest

from rf_etl import cli, manifest

ROOT = Path(__file__).resolve().parents[2]
SHA = "0123456789abcdef0123456789abcdef01234567"


def _marts(tmp: Path) -> Path:
    d = tmp / "marts"
    d.mkdir()
    duckdb.sql(f"COPY (SELECT range AS x FROM range(5)) TO '{d / 'msp_active.parquet'}' (FORMAT parquet)")
    (d / "report.json").write_text("{}", "utf-8")
    return d


def _slim(tmp: Path) -> Path:
    d = tmp / "slim"
    d.mkdir()
    for day in ("2025-10-10", "2026-10-10"):
        (d / f"rsmp_{day}.stats.json").write_text(json.dumps(
            {"snapshot_date": day, "url": f"u{day}", "docs_declared": 3, "docs_parsed": 3, "no_inn": 0}), "utf-8")
    return d


def test_snapshot_id():
    assert manifest.snapshot_id(dt.date(2026, 10, 17), SHA) == "2026-10-0123456"
    with pytest.raises(ValueError):
        manifest.snapshot_id(dt.date(2026, 10, 17), "XYZ")


def test_manifest_contents(tmp_path):
    marts, slim = _marts(tmp_path), _slim(tmp_path)
    raw = tmp_path / "raw" / "emiss_probe" / "2026-10-16"
    raw.mkdir(parents=True)
    (raw / "fetch.json").write_text(json.dumps({"id": "emiss_probe", "ok": True}), "utf-8")
    m = manifest.build(marts, "2026-10-0123456", SHA, ROOT / "config/taxonomy.yaml", slim, tmp_path / "raw")
    on_disk = json.loads((marts / "manifest.json").read_text("utf-8"))
    assert on_disk == m
    assert m["snapshot"] == "2026-10-0123456" and m["git_sha"] == SHA
    assert m["taxonomy_version"] == "1.0.0" and m["methodology_version"] == manifest.METHODOLOGY_VERSION
    assert m["data_date"] == "2026-10-10"
    assert [r["snapshot_date"] for r in m["sources"]["fns_rsmp"]] == ["2025-10-10", "2026-10-10"]
    assert m["sources"]["server_raw"] == [{"id": "emiss_probe", "ok": True}]
    assert m["files"]["msp_active.parquet"]["rows"] == 5
    assert len(m["files"]["report.json"]["sha256"]) == 64
    assert "manifest.json" not in m["files"]


def test_manifest_requires_parquet(tmp_path):
    (tmp_path / "marts").mkdir()
    with pytest.raises(FileNotFoundError):
        manifest.build(tmp_path / "marts", "2026-10-0123456", SHA, ROOT / "config/taxonomy.yaml")


def test_cli_manifest_prints_id(tmp_path, capsys, monkeypatch):
    marts = _marts(tmp_path)
    monkeypatch.chdir(ROOT)
    assert cli.main(["manifest", "--marts-dir", str(marts), "--git-sha", SHA, "--snapshot", "2026-09-abcdef0"]) == 0
    assert capsys.readouterr().out.strip() == "2026-09-abcdef0"
    assert (marts / "manifest.json").exists()


def _fetcher(monkeypatch, raw: Path):
    spec = importlib.util.spec_from_file_location("fetch", ROOT / "deploy/fetcher/fetch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "RAW", raw)
    return mod


def test_fetcher_due_and_schedule(tmp_path, monkeypatch):
    f = _fetcher(monkeypatch, tmp_path)
    src = {"id": "s", "every_days": 7}
    today = dt.date(2026, 10, 17)
    assert f.is_due(src, today)
    d = tmp_path / "s" / "2026-10-14"
    d.mkdir(parents=True)
    (d / "fetch.json").write_text(json.dumps({"ok": False}), "utf-8")
    assert f.is_due(src, today)  # неудачная попытка не считается
    (d / "fetch.json").write_text(json.dumps({"ok": True}), "utf-8")
    assert not f.is_due(src, today)
    assert f.is_due(src, dt.date(2026, 10, 21))
    now = dt.datetime(2026, 10, 17, 1, 0, tzinfo=dt.UTC)
    assert f.seconds_until("00:30", now) == 23.5 * 3600
    assert f.seconds_until("02:00", now) == 3600


def test_fetcher_writes_file_and_meta(tmp_path, monkeypatch):
    f = _fetcher(monkeypatch, tmp_path)
    page = tmp_path / "page.html"
    page.write_bytes(b"hello")
    meta = f.fetch({"id": "s", "url": page.as_uri(), "filename": "x.html"}, dt.date(2026, 10, 17))
    assert meta["ok"] and meta["bytes"] == 5
    assert (tmp_path / "s/2026-10-17/x.html").read_bytes() == b"hello"
    bad = f.fetch({"id": "s", "url": (tmp_path / "nope").as_uri(), "filename": "y"}, dt.date(2026, 10, 18))
    assert not bad["ok"] and "error" in bad
    assert not (tmp_path / "s/2026-10-18/y.part").exists()


def test_fetcher_sources_valid():
    sources = json.loads((ROOT / "deploy/fetcher/sources.json").read_text("utf-8"))["sources"]
    ids = [s["id"] for s in sources]
    assert len(ids) == len(set(ids))
    for s in sources:
        assert s["url"].startswith("https://") and s["filename"] and "/" not in s["filename"]


needs_bash = pytest.mark.skipif(os.name == "nt" or not shutil.which("bash"), reason="серверный bash-скрипт")


def _publish(marts: Path, snap: str, keep: int = 6) -> subprocess.CompletedProcess:
    inc = marts / ".incoming" / snap
    inc.mkdir(parents=True)
    (inc / "manifest.json").write_text(json.dumps({
        "snapshot": snap, "created_at": "t", "git_sha": "g", "methodology_version": "m",
        "taxonomy_version": "1", "data_date": "d", "files": {}}), "utf-8")
    env = {**os.environ, "SNAP": snap, "MARTS": str(marts), "KEEP": str(keep)}
    return subprocess.run(["bash", str(ROOT / "deploy/publish-snapshot.sh")], env=env,
                          capture_output=True, text=True)


@needs_bash
def test_publish_switch_and_prune(tmp_path):
    marts = tmp_path / "marts"
    marts.mkdir()
    snaps = [f"2026-{m:02d}-abcdef0" for m in range(1, 5)]
    for s in snaps:
        r = _publish(marts, s, keep=2)
        assert r.returncode == 0, r.stderr
        assert os.readlink(marts / "current") == s
    left = sorted(p.name for p in marts.iterdir() if p.name[0].isdigit())
    assert len(left) == 2 and snaps[-1] in left
    r = _publish(marts, snaps[-1], keep=2)  # повтор того же снимка
    assert r.returncode == 0, r.stderr
    assert os.readlink(marts / "current") == snaps[-1]
    assert not list(marts.glob(".swap-*"))


@needs_bash
def test_publish_rejects_bad_input(tmp_path):
    marts = tmp_path / "marts"
    marts.mkdir()
    env = {**os.environ, "SNAP": "../etc", "MARTS": str(marts)}
    r = subprocess.run(["bash", str(ROOT / "deploy/publish-snapshot.sh")], env=env, capture_output=True, text=True)
    assert r.returncode == 2
    (marts / ".incoming" / "2026-10-abcdef0").mkdir(parents=True)
    r = subprocess.run(["bash", str(ROOT / "deploy/publish-snapshot.sh")],
                       env={**env, "SNAP": "2026-10-abcdef0"}, capture_output=True, text=True)
    assert r.returncode == 3 and not (marts / "current").exists()
