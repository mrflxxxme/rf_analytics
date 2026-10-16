"""Снимок реестра МСП (ZIP с XML) → компактный Parquet: одна строка на субъект.

Персональные данные (ФИО ИП, наименования) не извлекаются. ИНН нужен только
для сопоставления субъекта между снимками (выживаемость) и в витрины не попадает.
"""

from __future__ import annotations

import collections
import datetime as dt
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Iterator

import pyarrow as pa
import pyarrow.parquet as pq
from lxml import etree

SCHEMA = pa.schema([
    ("snapshot_date", pa.date32()),
    ("inn", pa.string()),
    ("kind", pa.int8()),        # ВидСубМСП: 1 — ЮЛ, 2 — ИП
    ("category", pa.int8()),    # КатСубМСП: 1 — микро, 2 — малое, 3 — среднее
    ("date_incl", pa.date32()),  # ДатаВклМСП
    ("is_new", pa.bool_()),      # ПризНовМСП = 1
    ("region_id", pa.string()),  # КодРегион (код субъекта ФНС, D35)
    ("okved", pa.string()),      # основной ОКВЭД (заявительный)
])
BATCH = 200_000


@dataclass
class Stats:
    docs_declared: int = 0
    docs_parsed: int = 0
    no_inn: int = 0
    no_okved: int = 0
    snapshot_dates: collections.Counter = field(default_factory=collections.Counter)
    okved_names: dict[str, str] = field(default_factory=dict)
    okved_versions: collections.Counter = field(default_factory=collections.Counter)


def _date(s: str | None) -> dt.date | None:
    if not s:
        return None
    d, m, y = s.split(".")
    return dt.date(int(y), int(m), int(d))


def _int(s: str | None) -> int | None:
    return int(s) if s and s.isdigit() else None


def iter_documents(xml: IO[bytes], stats: Stats) -> Iterator[dict]:
    for event, el in etree.iterparse(xml, events=("start", "end"), tag=("Файл", "Документ")):
        if el.tag == "Файл":
            if event == "start":
                stats.docs_declared += _int(el.get("КолДок")) or 0
            continue
        if event != "end":
            continue
        yield _row(el, stats)
        el.clear(keep_tail=False)
        parent = el.getparent()
        while el.getprevious() is not None:
            del parent[0]


def _row(el: etree._Element, stats: Stats) -> dict:
    org = el.find("ОргВклМСП")
    ip = el.find("ИПВклМСП")
    inn = org.get("ИННЮЛ") if org is not None else (ip.get("ИННФЛ") if ip is not None else None)
    mn = el.find("СведМН")
    osn = el.find("СвОКВЭД/СвОКВЭДОсн")
    if osn is None:
        osn = el.find(".//СвОКВЭДОсн")
    okved = osn.get("КодОКВЭД") if osn is not None else None
    if okved and okved not in stats.okved_names:
        stats.okved_names[okved] = osn.get("НаимОКВЭД", "")
    if osn is not None:
        stats.okved_versions[osn.get("ВерсОКВЭД", "")] += 1
    stats.docs_parsed += 1
    stats.no_inn += inn is None
    stats.no_okved += okved is None
    snap = _date(el.get("ДатаСост"))
    stats.snapshot_dates[snap] += 1
    return {
        "snapshot_date": snap,
        "inn": inn,
        "kind": _int(el.get("ВидСубМСП")),
        "category": _int(el.get("КатСубМСП")),
        "date_incl": _date(el.get("ДатаВклМСП")),
        "is_new": el.get("ПризНовМСП") == "1",
        "region_id": (mn.get("КодРегион") if mn is not None else None),
        "okved": okved,
    }


def parse_zip(zip_path: str | Path, out_path: str | Path) -> Stats:
    """Пишет Parquet батчами, держит в памяти не больше BATCH строк."""
    stats = Stats()
    with zipfile.ZipFile(zip_path) as z, pq.ParquetWriter(out_path, SCHEMA, compression="zstd") as w:
        buf: list[dict] = []
        for info in z.infolist():
            if not info.filename.lower().endswith(".xml"):
                continue
            with z.open(info) as xml:
                for row in iter_documents(xml, stats):
                    buf.append(row)
                    if len(buf) >= BATCH:
                        w.write_table(pa.Table.from_pylist(buf, SCHEMA))
                        buf.clear()
        if buf:
            w.write_table(pa.Table.from_pylist(buf, SCHEMA))
    return stats
