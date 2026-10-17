"""manifest.json снимка витрин (docs/01-architecture.md, «Снимки и воспроизводимость»).

Snapshot `YYYY-MM-<gitsha7>`: витрины + манифест с версиями источников, хешами файлов,
версией методологии и метриками бэктеста (до T3.5 — null).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import pyarrow.parquet as pq
import yaml

METHODOLOGY_VERSION = "0.1.0"  # 03-methodology.md: только измеренные факты (п. 11)
SNAPSHOT_ID = re.compile(r"^\d{4}-\d{2}-[0-9a-f]{7}$")
MANIFEST = "manifest.json"


def snapshot_id(when: dt.date, git_sha: str) -> str:
    sid = f"{when:%Y-%m}-{git_sha[:7]}"
    if not SNAPSHOT_ID.match(sid):
        raise ValueError(f"плохой snapshot id: {sid}")
    return sid


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _files(marts_dir: Path) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for p in sorted(marts_dir.rglob("*")):
        if not p.is_file() or p.name == MANIFEST:
            continue
        rec: dict[str, object] = {"bytes": p.stat().st_size, "sha256": _sha256(p)}
        if p.suffix == ".parquet":
            rec["rows"] = pq.ParquetFile(p).metadata.num_rows
        out[p.relative_to(marts_dir).as_posix()] = rec
    return out


def _rsmp_sources(slim_dir: Path | None) -> list[dict[str, object]]:
    if slim_dir is None:
        return []
    rows = []
    for p in sorted(slim_dir.glob("*.stats.json")):
        s = json.loads(p.read_text("utf-8"))
        rows.append({k: s.get(k) for k in ("snapshot_date", "url", "docs_declared", "docs_parsed")})
    return rows


def _raw_sources(raw_dir: Path | None) -> list[dict[str, object]]:
    """fetch.json, которые fetcher положил на сервере (raw/<source>/<date>/fetch.json)."""
    if raw_dir is None or not raw_dir.exists():
        return []
    return [json.loads(p.read_text("utf-8")) for p in sorted(raw_dir.glob("*/*/fetch.json"))]


def build(marts_dir: str | Path, sid: str, git_sha: str, taxonomy_path: str | Path,
          slim_dir: str | Path | None = None, raw_dir: str | Path | None = None,
          now: dt.datetime | None = None) -> dict[str, object]:
    if not SNAPSHOT_ID.match(sid):
        raise ValueError(f"плохой snapshot id: {sid}")
    marts = Path(marts_dir)
    files = _files(marts)
    if not any(name.endswith(".parquet") for name in files):
        raise FileNotFoundError(f"в {marts} нет витрин *.parquet")
    tax = yaml.safe_load(Path(taxonomy_path).read_text("utf-8"))
    rsmp = _rsmp_sources(Path(slim_dir) if slim_dir else None)
    data_date = max((str(r["snapshot_date"]) for r in rsmp), default=None)
    manifest = {
        "snapshot": sid,
        "created_at": (now or dt.datetime.now(dt.UTC)).isoformat(timespec="seconds"),
        "git_sha": git_sha,
        "methodology_version": METHODOLOGY_VERSION,
        "taxonomy_version": str(tax.get("version")),
        "data_date": data_date,
        "sources": {"fns_rsmp": rsmp, "server_raw": _raw_sources(Path(raw_dir) if raw_dir else None)},
        "backtest": None,  # после T3.5
        "files": files,
    }
    (marts / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")
    return manifest
