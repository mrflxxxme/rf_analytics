"""Fetcher RADAR (docs/01-architecture.md): качает источники, которые закрыты для зарубежных IP.

Ничего не разбирает. Кладёт файл в /raw/<source>/<YYYY-MM-DD>/ и рядом fetch.json
(url, sha256, байты, время). Разбор — в ETL на GitHub Actions (rsync raw с сервера).

Только stdlib. Запуск:
  python fetch.py          — демон: раз в сутки в RF_FETCH_AT (UTC), качает источники, у которых
                             последний удачный файл старше every_days;
  python fetch.py --once   — один проход сейчас (ручной запуск: docker compose run --rm fetcher …).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parent
RAW = Path(os.environ.get("RF_RAW_DIR", "/raw"))
SOURCES = Path(os.environ.get("RF_FETCH_SOURCES", APP / "sources.json"))
AT = os.environ.get("RF_FETCH_AT", "00:30")  # UTC; 03:30 МСК — ночь у соседей по серверу
UA = "rf-analytics-fetcher/0.1 (+https://github.com/mrflxxxme/rf_analytics)"
# Росстат и др. подписаны НУЦ Минцифры; корень добавляем к системным, verify не отключаем.
EXTRA_CA = APP / "russian_trusted_root_ca.pem"


def _ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if EXTRA_CA.exists():
        ctx.load_verify_locations(cafile=str(EXTRA_CA))
    return ctx


def last_ok(source_id: str) -> dt.date | None:
    dates = []
    for meta in (RAW / source_id).glob("*/fetch.json"):
        try:
            if json.loads(meta.read_text("utf-8")).get("ok"):
                dates.append(dt.date.fromisoformat(meta.parent.name))
        except (ValueError, OSError):
            continue
    return max(dates, default=None)


def is_due(src: dict, today: dt.date) -> bool:
    prev = last_ok(src["id"])
    return prev is None or (today - prev).days >= int(src.get("every_days", 30))


def fetch(src: dict, today: dt.date) -> dict:
    out = RAW / src["id"] / today.isoformat()
    out.mkdir(parents=True, exist_ok=True)
    dst = out / src["filename"]
    part = dst.with_name(dst.name + ".part")
    meta: dict = {"id": src["id"], "url": src["url"], "file": dst.name,
                  "fetched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "ok": False}
    try:
        req = urllib.request.Request(src["url"], headers={"User-Agent": UA, **src.get("headers", {})})
        h = hashlib.sha256()
        with urllib.request.urlopen(req, timeout=120, context=_ctx()) as r, open(part, "wb") as f:
            meta["status"] = r.status
            while chunk := r.read(1 << 20):
                h.update(chunk)
                f.write(chunk)
        part.replace(dst)
        meta.update(ok=True, bytes=dst.stat().st_size, sha256=h.hexdigest())
    except Exception as e:  # noqa: BLE001 — один источник не роняет проход
        meta["error"] = f"{type(e).__name__}: {e}"
        part.unlink(missing_ok=True)
    (out / "fetch.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    return meta


def run_once(force: bool = False) -> int:
    today = dt.datetime.now(dt.UTC).date()
    sources = json.loads(SOURCES.read_text("utf-8"))["sources"]
    failed = 0
    for src in sources:
        if not force and not is_due(src, today):
            continue
        meta = fetch(src, today)
        failed += not meta["ok"]
        print(json.dumps(meta, ensure_ascii=False), flush=True)
        time.sleep(2)  # вежливая пауза между запросами к госсайтам
    print(f"pass done: {len(sources)} sources, {failed} failed", flush=True)
    return 1 if failed else 0


def seconds_until(at: str, now: dt.datetime) -> float:
    hh, mm = map(int, at.split(":"))
    nxt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if nxt <= now:
        nxt += dt.timedelta(days=1)
    return (nxt - now).total_seconds()


def main(argv: list[str]) -> int:
    if "--once" in argv:
        return run_once(force="--force" in argv)
    while True:
        wait = seconds_until(AT, dt.datetime.now(dt.UTC))
        print(f"next pass in {wait / 3600:.1f} h", flush=True)
        time.sleep(wait)
        run_once()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
