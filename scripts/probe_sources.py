"""Пробник доступности источников (T1.1).

Только стандартная библиотека: один и тот же файл запускается локально,
в GitHub Actions и на сервере (`ssh ... python3 - < scripts/probe_sources.py`).
Файлы не скачиваются целиком: GET с Range на первые байты, тело не сохраняется.

    python scripts/probe_sources.py --vantage actions --out probe.json
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass

UA = "rf-analytics-probe/0.1 (+https://github.com/mrflxxxme/rf_analytics)"
TIMEOUT_S = 30
PAUSE_S = 1.0  # пауза между запросами, чтобы не нагружать источники

# (source_id, url, extra headers). Список держим в синхроне с config/sources.yaml.
TARGETS: list[tuple[str, str, dict[str, str]]] = [
    ("fns_rsmp", "https://www.nalog.gov.ru/opendata/7707329152-rsmp/", {}),
    ("fns_rsmp", "https://www.nalog.gov.ru/opendata/7707329152-rsmp/meta.csv", {}),
    ("fns_rsmp", "https://file.nalog.ru/opendata/7707329152-rsmp/data-10102026-structure-12052026.zip", {}),
    ("fns_rsmp", "https://file.nalog.ru/opendata/7707329152-rsmp/structure-12052026.xsd", {}),
    ("emiss", "https://www.fedstat.ru/indicator/31152", {}),
    ("emiss", "https://fedstat.ru/", {}),
    ("cbr", "https://www.cbr.ru/statistics/bank_sector/sors/", {}),
    ("cbr", "https://www.cbr.ru/vfs/statistics/BankSector/Loans_to_individuals/01_22_Loans_ind_20260901.xlsx", {}),
    ("cbr", "https://www.cbr.ru/vfs/statistics/BankSector/Borrowings/02_06_Dep_ind.xlsx", {}),
    ("cbr", "https://www.cbr.ru/vfs/statistics/BankSector/Loans_to_corporations/01_13_F_Debt_sme_subj.xlsx", {}),
    ("sberindex", "https://sberindex.ru/", {}),
    ("sberindex", "https://api.sberindex.ru/", {}),
    ("sberindex", "https://www.sberbank.com/common/img/uploaded/files/pdf/sberindex/hackathonlicence.zip", {}),
    ("osm", "https://download.geofabrik.de/russia-latest.osm.pbf", {}),
    ("osm", "https://download.geofabrik.de/russia/central-fed-district-latest.osm.pbf", {}),
    ("hh", "https://api.hh.ru/areas/113", {"HH-User-Agent": UA}),
    ("hh", "https://api.hh.ru/vacancies?area=1&per_page=1", {"HH-User-Agent": UA}),
    ("rosstat", "https://rosstat.gov.ru/compendium/document/13282", {}),
    ("rosstat", "https://rosstat.gov.ru/storage/mediabank/BUL_MO_2024.xlsx", {}),
    ("rosstat_migration", "https://rosstat.gov.ru/storage/mediabank/Bul_migr_2023.xlsx", {}),
]


@dataclass
class Result:
    source: str
    url: str
    vantage: str
    status: int | None
    ok: bool
    content_type: str | None
    size_bytes: int | None
    elapsed_s: float
    tls_verified: bool
    error: str | None


def _total_size(headers: object) -> int | None:
    cr = headers.get("Content-Range")  # type: ignore[attr-defined]
    if cr and "/" in cr and not cr.endswith("/*"):
        return int(cr.rsplit("/", 1)[1])
    cl = headers.get("Content-Length")  # type: ignore[attr-defined]
    return int(cl) if cl and cl.isdigit() else None


def probe(source: str, url: str, extra: dict[str, str], vantage: str) -> Result:
    headers = {"User-Agent": UA, "Range": "bytes=0-2047", **extra}
    t0 = time.monotonic()
    # Сначала с проверкой TLS; если цепочка не строится (сертификаты НУЦ Минцифры),
    # повторяем без проверки только ради диагностики и помечаем tls_verified=False.
    for verified in (True, False):
        ctx = ssl.create_default_context() if verified else ssl._create_unverified_context()
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S, context=ctx) as r:
                r.read(2048)
                return Result(source, url, vantage, r.status, r.status < 400,
                              r.headers.get("Content-Type"), _total_size(r.headers),
                              round(time.monotonic() - t0, 2), verified, None)
        except urllib.error.HTTPError as e:
            return Result(source, url, vantage, e.code, False, e.headers.get("Content-Type"),
                          None, round(time.monotonic() - t0, 2), verified, f"HTTP {e.code}")
        except urllib.error.URLError as e:
            if verified and isinstance(e.reason, ssl.SSLCertVerificationError):
                continue
            err = f"{type(e.reason).__name__}: {e.reason}"
        except (TimeoutError, socket.timeout, ConnectionError, ssl.SSLError) as e:
            err = f"{type(e).__name__}: {e}"
        return Result(source, url, vantage, None, False, None, None,
                      round(time.monotonic() - t0, 2), verified, err[:200])
    raise AssertionError("unreachable")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vantage", default="local", help="local | actions | server")
    ap.add_argument("--out", help="JSON-файл с результатами (по умолчанию stdout)")
    args = ap.parse_args(argv)
    results = []
    for source, url, extra in TARGETS:
        res = probe(source, url, extra, args.vantage)
        results.append(asdict(res))
        mark = "OK " if res.ok else "ERR"
        print(f"{mark} {res.status or '-':>4} {res.elapsed_s:>6}s tls={int(res.tls_verified)} "
              f"{source:<10} {url[:90]} {res.error or ''}", file=sys.stderr)
        time.sleep(PAUSE_S)
    payload = json.dumps(results, ensure_ascii=False, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
