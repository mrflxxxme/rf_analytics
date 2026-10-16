"""Список снимков реестра МСП с паспорта набора открытых данных ФНС."""

from __future__ import annotations

import datetime as dt
import re
import urllib.request
from dataclasses import dataclass

PASSPORT = "https://www.nalog.gov.ru/opendata/7707329152-rsmp/"
BASE = "https://file.nalog.ru/opendata/7707329152-rsmp/"
UA = "rf-analytics-etl/0.1 (+https://github.com/mrflxxxme/rf_analytics)"
NAME = re.compile(r"data-(\d{8})-structure-(\d{8})\.zip")


@dataclass(frozen=True, order=True)
class Snapshot:
    date: dt.date
    structure: str
    filename: str

    @property
    def url(self) -> str:
        return BASE + self.filename


def parse_date(token: str) -> dt.date:
    """Дата снимка из имени файла. Снимки выходят 10-го числа; в старых именах
    формат MMDDYYYY (01102017 — 10.01.2017), в новых DDMMYYYY (10102026)."""
    a, b, year = int(token[:2]), int(token[2:4]), int(token[4:])
    if a == 10 and b != 10:
        return dt.date(year, b, 10)
    if b == 10:
        return dt.date(year, a, 10)
    return dt.date(year, b, a)  # прочие даты — DDMMYYYY


def parse_listing(html: str) -> list[Snapshot]:
    seen: dict[dt.date, Snapshot] = {}
    for m in NAME.finditer(html):
        snap = Snapshot(parse_date(m.group(1)), m.group(2), m.group(0))
        prev = seen.get(snap.date)
        if prev is None or snap.structure > prev.structure:
            seen[snap.date] = snap
    return sorted(seen.values())


def fetch_listing(timeout: int = 60) -> list[Snapshot]:
    req = urllib.request.Request(PASSPORT, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return parse_listing(r.read().decode("utf-8", "replace"))


def select(snaps: list[Snapshot], spec: str) -> list[Snapshot]:
    """spec: 'latest' | 'annual' (октябрьские снимки, плюс последний) | 'YYYY-MM,YYYY-MM'."""
    if spec == "latest":
        return snaps[-1:]
    if spec == "annual":
        picked = [s for s in snaps if s.date.month == 10]
        if snaps and snaps[-1] not in picked:
            picked.append(snaps[-1])
        return picked
    wanted = {tuple(map(int, p.split("-"))) for p in spec.split(",") if p}
    return [s for s in snaps if (s.date.year, s.date.month) in wanted]
