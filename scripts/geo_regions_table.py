"""Справочник 89 субъектов РФ (T1.6) из таблицы ru.wikipedia «Коды субъектов РФ».

    python scripts/geo_regions_table.py codes.wiki config/geo/regions.csv

codes.wiki — `action=raw` статьи. Порядок строк — статья 65 Конституции РФ.
region_id — двузначный код субъекта ФНС (D35): для «старых» субъектов он
совпадает с первым кодом ГИБДД, для шести новых задан явно. Сверка с полем
`КодРегион` реестра МСП — тест ETL (tests/test_regions.py).
"""

from __future__ import annotations

import csv
import re
import sys

N_SUBJECTS = 89
# Коды ФНС, которые не совпадают с первым кодом ГИБДД.
FNS_OVERRIDE = {"UA-43": "91", "UA-40": "92", "UA-14": "93", "UA-09": "94",
                "UA-23": "90", "UA-65": "95"}


def parse(src: str) -> list[list[str]]:
    src = re.sub(r"<ref[^>/]*/>", "", src)
    src = re.sub(r"<ref[^>]*>.*?</ref>", "", src, flags=re.S)
    rows = []
    for line in (raw.strip() for raw in src.splitlines()):
        if not line.startswith("|") or "||" not in line or line[:2] in ("|-", "|}"):
            continue
        cells = [c.strip() for c in line[1:].split("||")]
        cells[0] = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", cells[0]).strip()
        rows.append(cells)
    return rows[:N_SUBJECTS]


def main() -> int:
    rows = parse(open(sys.argv[1], encoding="utf-8").read())
    dst = open(sys.argv[2], "w", encoding="utf-8", newline="") if len(sys.argv) > 2 else sys.stdout
    out = csv.writer(dst, lineterminator="\n")
    out.writerow(["region_id", "name", "constitution_order", "okato", "oktmo",
                  "iso3166_2", "gost_7_67", "gibdd"])
    seen: set[str] = set()
    for i, (name, gibdd, codes, iso, gost) in enumerate((r[:5] for r in rows), start=1):
        gibdd_codes = [c.strip() for c in gibdd.split(",") if c.strip()]
        region_id = FNS_OVERRIDE.get(iso, gibdd_codes[0].zfill(2))
        okato, _, oktmo = codes.partition("/")
        okato = okato.strip()
        oktmo = oktmo.strip() or okato
        if okato == "111":  # НАО: в таблице префикс «111», ОКАТО субъекта — 11100
            okato = "11100"
        assert region_id not in seen, region_id
        seen.add(region_id)
        name = " ".join(name.replace("\xa0", " ").split())  # в вики-разметке nbsp и двойные пробелы
        out.writerow([region_id, name, i, okato, oktmo, iso,
                      gost.split(",")[-1].strip(), " ".join(gibdd_codes)])
    assert len(seen) == N_SUBJECTS, len(seen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
