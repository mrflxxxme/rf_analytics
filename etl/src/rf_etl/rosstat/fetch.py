"""Загрузка файлов Росстата для `region_profile` (config/sources.yaml: rosstat_*).

rosstat.gov.ru и showdata.rosstat.gov.ru открыты с зарубежных IP — качаем в GitHub Actions.
Их сертификаты выданы НУЦ Минцифры: цепочка (config/certs/*.pem) добавляется к системным корням
только в контексте этих запросов.
Имена xlsx меняются с выпуском, поэтому ссылку на свежий файл ищем на странице раздела;
если страница не ответила — берём последнее известное имя.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import http.client
import json
import re
import ssl
import sys
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

UA = "Mozilla/5.0 (compatible; rf-analytics/0.1; +https://github.com/mrflxxxme/rf_analytics)"
MEDIABANK = "https://rosstat.gov.ru/storage/mediabank/"
SHOWDATA = "https://showdata.rosstat.gov.ru/x/report/{id}/view/compound/"
# Отчёты витрины showdata (период отчёта зашит в нём, фильтры GET игнорируются).
SHOWDATA_REPORTS = {"278932": "urban_share", "279008": "migration_rate"}
POLVOZR_YEARS = range(2016, 2023)  # Chisl_polvozr_01-01-YYYY_VPN-2020.xlsx, пересчёт после ВПН-2020
INCOME_PAGE = "https://rosstat.gov.ru/folder/13397"
INCOME_RE = re.compile(r"/storage/mediabank/(urov_10subg_[\w-]+\.xlsx)", re.I)
INCOME_FALLBACK = "urov_10subg_1pg2026.xlsx"
POPUL_PAGE = "https://rosstat.gov.ru/folder/12781"
OKPOPUL_RE = re.compile(r"/storage/mediabank/(OkPopul_Comp(\d{4})_Site\.xlsx)")
OKPOPUL_FALLBACK = "OkPopul_Comp2025_Site.xlsx"
FETCH_JSON = "fetch.json"
CA_DIR = "config/certs"  # Russian Trusted Root CA + Sub CA (публичные сертификаты, gu-st.ru)


@dataclass(frozen=True)
class Target:
    name: str  # имя файла в raw-каталоге
    url: str


_CTX: ssl.SSLContext | None = None


def ssl_context(ca_dir: str | Path = CA_DIR) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    for pem in sorted(Path(ca_dir).glob("*.pem")):
        ctx.load_verify_locations(cafile=str(pem))
    return ctx


def _get(url: str, timeout: int = 120) -> bytes:
    global _CTX
    _CTX = _CTX or ssl_context()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
        return r.read()


def _get_retry(url: str, retries: int = 3) -> bytes:
    for attempt in range(1, retries + 1):
        try:
            return _get(url)
        except (OSError, http.client.HTTPException) as e:
            print(f"{url}: попытка {attempt}: {e}", file=sys.stderr)
            if attempt == retries:
                raise
            time.sleep(10 * attempt)
    raise AssertionError("unreachable")


def discover_income(html: str) -> str | None:
    names = sorted(set(INCOME_RE.findall(html)))
    return names[-1] if names else None


def discover_okpopul(html: str) -> str | None:
    found = sorted({(int(y), n) for n, y in OKPOPUL_RE.findall(html)})
    return found[-1][1] if found else None


def _page(url: str) -> str:
    try:
        return _get_retry(url).decode("utf-8", "replace")
    except (OSError, http.client.HTTPException) as e:
        print(f"страница {url} недоступна ({e}) — берём известное имя файла", file=sys.stderr)
        return ""


def plan() -> list[Target]:
    income = discover_income(_page(INCOME_PAGE)) or INCOME_FALLBACK
    okpopul = discover_okpopul(_page(POPUL_PAGE)) or OKPOPUL_FALLBACK
    xlsx = [f"Chisl_polvozr_01-01-{y}_VPN-2020.xlsx" for y in POLVOZR_YEARS] + [okpopul, income]
    return ([Target(f"showdata_{rid}.json", SHOWDATA.format(id=rid)) for rid in SHOWDATA_REPORTS]
            + [Target(n, MEDIABANK + n) for n in xlsx])


def _check(name: str, body: bytes, dst: Path) -> None:
    if name.endswith(".json"):
        rows = json.loads(body)["headers"]["reportHeaders"]["row_header"]
        if not rows:
            raise ValueError(f"{name}: отчёт без строк")
    elif not zipfile.is_zipfile(dst):
        raise ValueError(f"{name}: не xlsx ({len(body)} Б): {body[:120]!r}")


def fetch(out_dir: str | Path, targets: list[Target] | None = None) -> list[dict[str, object]]:
    """Скачивает все файлы; ошибка любого — исключение (витрина без части рядов вводила бы в заблуждение)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    log: list[dict[str, object]] = []
    for t in targets or plan():
        body = _get_retry(t.url)
        dst = out / t.name
        dst.write_bytes(body)
        _check(t.name, body, dst)
        log.append({"name": t.name, "url": t.url, "bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "fetched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")})
        print(f"{t.name}: {len(body)} Б", file=sys.stderr)
    (out / FETCH_JSON).write_text(json.dumps(log, ensure_ascii=False, indent=1), "utf-8")
    return log
