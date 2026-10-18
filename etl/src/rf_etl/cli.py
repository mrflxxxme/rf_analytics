"""CLI ETL: `rf-etl rsmp-versions | rsmp-parse | rsmp-marts | rosstat-fetch | region-profile | manifest`."""

from __future__ import annotations

import argparse
import datetime as dt
import http.client
import json
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

from rf_etl import manifest
from rf_etl.rosstat import fetch as rosstat_fetch
from rf_etl.rosstat import profile
from rf_etl.rsmp import marts, parse, versions


def _check_download(dst: Path, expected: int) -> None:
    """file.nalog.ru под нагрузкой иногда отдаёт 200 с обрывком или заглушкой вместо ZIP."""
    size = dst.stat().st_size
    if expected and size != expected:
        raise OSError(f"получено {size} из {expected} байт")
    if not zipfile.is_zipfile(dst):
        with open(dst, "rb") as f:
            head = f.read(200)
        raise OSError(f"не ZIP ({size} байт): {head!r}")


def _download(url: str, dst: Path, retries: int = 8) -> None:
    """Обрыв под конец 2-ГБ архива — обычное дело для file.nalog.ru: докачиваем Range-запросом,
    а не начинаем заново. Если сервер Range не поддержал (200 вместо 206) — пишем с нуля."""
    expected = 0
    dst.unlink(missing_ok=True)
    for attempt in range(1, retries + 1):
        try:
            have = dst.stat().st_size if dst.exists() else 0
            headers = {"User-Agent": versions.UA}
            if have and expected:
                headers["Range"] = f"bytes={have}-"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as r:
                resumed = r.status == 206
                if not resumed:
                    expected = int(r.headers.get("Content-Length") or 0)
                with open(dst, "ab" if resumed else "wb") as f:
                    shutil.copyfileobj(r, f, length=8 << 20)
            _check_download(dst, expected)
            print(f"downloaded {dst.stat().st_size} bytes", file=sys.stderr)
            return
        except (OSError, http.client.HTTPException) as e:
            print(f"download attempt {attempt} failed: {e}", file=sys.stderr)
            # Докачивать есть смысл только недокачанный файл; заглушку или переросток — заново.
            if not expected or (dst.exists() and dst.stat().st_size >= expected):
                dst.unlink(missing_ok=True)
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
    m = versions.NAME.search(a.url)
    file_date = versions.parse_date(m.group(1)) if m else None
    stats = parse.parse_zip(zpath, tmp, file_date)
    zpath.unlink()
    snap_date = file_date or stats.snapshot_dates.most_common(1)[0][0]
    final = out / f"rsmp_{snap_date}.parquet"
    tmp.replace(final)
    report = {
        "url": a.url, "snapshot_date": str(snap_date), "docs_declared": stats.docs_declared,
        "docs_parsed": stats.docs_parsed, "no_inn": stats.no_inn, "no_okved": stats.no_okved,
        "bad_dates": stats.bad_dates,
        "snapshot_dates": {str(k): v for k, v in stats.snapshot_dates.items()},
        "okved_versions": dict(stats.okved_versions),
        "download_s": round(t1 - t0), "parse_s": round(time.monotonic() - t1),
    }
    (out / f"rsmp_{snap_date}.stats.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    (out / f"rsmp_{snap_date}.okved_names.json").write_text(
        json.dumps(stats.okved_names, ensure_ascii=False, indent=0), "utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if parse.is_complete(stats) else 2


def cmd_marts(a: argparse.Namespace) -> int:
    rep = marts.build(a.slim_dir, a.taxonomy, a.regions, a.out_dir)
    names: dict[str, str] = {}
    for p in sorted(Path(a.slim_dir).glob("*.okved_names.json")):
        names.update(json.loads(p.read_text("utf-8")))
    (Path(a.out_dir) / "okved_names.json").write_text(json.dumps(names, ensure_ascii=False, indent=0), "utf-8")
    (Path(a.out_dir) / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), "utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    return 0


def cmd_rosstat_fetch(a: argparse.Namespace) -> int:
    log = rosstat_fetch.fetch(a.out_dir)
    print(json.dumps(log, ensure_ascii=False, indent=1))
    return 0


def cmd_region_profile(a: argparse.Namespace) -> int:
    asof = dt.date.fromisoformat(a.asof) if a.asof else None
    rep = profile.build(a.raw_dir, a.regions, a.out_dir, asof)
    print(json.dumps({k: v for k, v in rep.items() if k != "sources"}, ensure_ascii=False, indent=1))
    return 0


def cmd_manifest(a: argparse.Namespace) -> int:
    sid = a.snapshot or manifest.snapshot_id(dt.datetime.now(dt.UTC).date(), a.git_sha)
    m = manifest.build(a.marts_dir, sid, a.git_sha, a.taxonomy, a.slim_dir, a.raw_dir)
    print(sid)
    print(f"{len(m['files'])} files, data_date={m['data_date']}", file=sys.stderr)
    return 0


def cmd_facts(a: argparse.Namespace) -> int:
    from rf_etl.facts import render

    today = dt.date.fromisoformat(a.today) if a.today else None
    rep = render.build(a.marts_dir, a.config_dir, a.out_dir, a.site_url, a.methodology, today)
    print(json.dumps(rep, ensure_ascii=False))
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
    rf = sub.add_parser("rosstat-fetch", help="файлы Росстата для region_profile")
    rf.add_argument("--out-dir", required=True)
    rf.set_defaults(fn=cmd_rosstat_fetch)
    rp = sub.add_parser("region-profile", help="витрина region_profile из файлов rosstat-fetch")
    rp.add_argument("--raw-dir", required=True)
    rp.add_argument("--out-dir", required=True)
    rp.add_argument("--regions", default="config/geo/regions.csv")
    rp.add_argument("--asof", help="дата для флагов устаревания, YYYY-MM-DD (по умолчанию сегодня UTC)")
    rp.set_defaults(fn=cmd_region_profile)
    mf = sub.add_parser("manifest", help="manifest.json снимка; печатает snapshot id")
    mf.add_argument("--marts-dir", required=True)
    mf.add_argument("--git-sha", required=True)
    mf.add_argument("--snapshot", help="по умолчанию YYYY-MM-<sha7> от текущей даты UTC")
    mf.add_argument("--slim-dir")
    mf.add_argument("--raw-dir")
    mf.add_argument("--taxonomy", default="config/taxonomy.yaml")
    mf.set_defaults(fn=cmd_manifest)
    fc = sub.add_parser("facts", help="статические страницы фактов, sitemap.xml, robots.txt (T2.5)")
    fc.add_argument("--marts-dir", required=True, help="каталог snapshot (marts/current)")
    fc.add_argument("--out-dir", required=True)
    fc.add_argument("--site-url", required=True, help="канонический адрес сайта, https://…")
    fc.add_argument("--config-dir", default="config")
    fc.add_argument("--methodology", default="docs/03-methodology.md")
    fc.add_argument("--today", help="дата для «Региона недели», YYYY-MM-DD (по умолчанию сегодня UTC)")
    fc.set_defaults(fn=cmd_facts)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
