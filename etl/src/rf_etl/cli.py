"""CLI ETL: `rf-etl rsmp-versions | rsmp-parse | rsmp-marts`."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

from rf_etl.rsmp import marts, parse, versions


def _download(url: str, dst: Path, retries: int = 3) -> None:
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": versions.UA})
            with urllib.request.urlopen(req, timeout=120) as r, open(dst, "wb") as f:
                shutil.copyfileobj(r, f, length=8 << 20)
            return
        except OSError as e:
            print(f"download attempt {attempt} failed: {e}", file=sys.stderr)
            time.sleep(30 * attempt)
    raise RuntimeError(f"не скачали {url}")


def cmd_versions(a: argparse.Namespace) -> int:
    snaps = versions.select(versions.fetch_listing(), a.spec)
    print(json.dumps([{"date": str(s.date), "url": s.url} for s in snaps]))
    return 0


def cmd_parse(a: argparse.Namespace) -> int:
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    zpath = out / "snapshot.zip"
    t0 = time.monotonic()
    _download(a.url, zpath)
    t1 = time.monotonic()
    tmp = out / "rsmp_tmp.parquet"
    stats = parse.parse_zip(zpath, tmp)
    zpath.unlink()
    snap_date = stats.snapshot_dates.most_common(1)[0][0]
    final = out / f"rsmp_{snap_date}.parquet"
    tmp.replace(final)
    report = {
        "url": a.url, "snapshot_date": str(snap_date), "docs_declared": stats.docs_declared,
        "docs_parsed": stats.docs_parsed, "no_inn": stats.no_inn, "no_okved": stats.no_okved,
        "snapshot_dates": {str(k): v for k, v in stats.snapshot_dates.items()},
        "okved_versions": dict(stats.okved_versions),
        "download_s": round(t1 - t0), "parse_s": round(time.monotonic() - t1),
    }
    (out / f"rsmp_{snap_date}.stats.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    (out / f"rsmp_{snap_date}.okved_names.json").write_text(
        json.dumps(stats.okved_names, ensure_ascii=False, indent=0), "utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if stats.docs_parsed == stats.docs_declared else 2


def cmd_marts(a: argparse.Namespace) -> int:
    rep = marts.build(a.slim_dir, a.taxonomy, a.regions, a.out_dir)
    names: dict[str, str] = {}
    for p in sorted(Path(a.slim_dir).glob("*.okved_names.json")):
        names.update(json.loads(p.read_text("utf-8")))
    (Path(a.out_dir) / "okved_names.json").write_text(json.dumps(names, ensure_ascii=False, indent=0), "utf-8")
    (Path(a.out_dir) / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), "utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rf-etl")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("rsmp-versions")
    v.add_argument("--spec", default="annual")
    v.set_defaults(fn=cmd_versions)
    p = sub.add_parser("rsmp-parse")
    p.add_argument("--url", required=True)
    p.add_argument("--out-dir", required=True)
    p.set_defaults(fn=cmd_parse)
    m = sub.add_parser("rsmp-marts")
    m.add_argument("--slim-dir", required=True)
    m.add_argument("--out-dir", required=True)
    m.add_argument("--taxonomy", default="config/taxonomy.yaml")
    m.add_argument("--regions", default="config/geo/regions.csv")
    m.set_defaults(fn=cmd_marts)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
