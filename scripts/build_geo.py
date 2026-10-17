"""Сборка полигонов 89 субъектов (T1.6) из GeoJSONSeq, выгруженного osmium.

    python scripts/build_geo.py config/geo/regions.csv boundaries-*.geojsonseq -o regions_full.geojson

Берёт отношения boundary=administrative + admin_level=4, сопоставляет с
`config/geo/regions.csv` по тегу ISO3166-2 (для Крыма и Севастополя — также
по русскому имени), оставляет в свойствах только `region_id` и `name`.
Упрощение — отдельным шагом mapshaper (общие границы соседей сохраняются).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys

# Запасное сопоставление, если в OSM у отношения нет ожидаемого ISO-кода.
NAME_FALLBACK = {"Республика Крым": "91", "Севастополь": "92"}


def load_regions(path: str) -> dict[str, dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        return {r["region_id"]: r for r in csv.DictReader(f)}


def pick(features: list[dict], regions: dict[str, dict[str, str]]) -> tuple[dict[str, dict], list[str]]:
    by_iso = {r["iso3166_2"]: rid for rid, r in regions.items()}
    chosen: dict[str, dict] = {}
    for feat in features:
        p = feat.get("properties") or {}
        if p.get("@type") != "relation" or p.get("admin_level") != "4":
            continue
        if p.get("boundary") != "administrative":
            continue
        rid = by_iso.get(p.get("ISO3166-2", "")) or NAME_FALLBACK.get(p.get("name:ru") or p.get("name", ""))
        if rid is None:
            continue
        # Если отношение пришло из двух выгрузок (Россия и Украина) — берём одно, с большим числом вершин.
        size = len(json.dumps(feat["geometry"]))
        if rid not in chosen or size > chosen[rid]["_size"]:
            chosen[rid] = {"_size": size, "_osm_id": p.get("@id"), "geometry": feat["geometry"]}
    missing = sorted(set(regions) - set(chosen))
    return chosen, missing


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("regions_csv")
    ap.add_argument("seq", nargs="+", help="GeoJSONSeq из osmium export")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--provenance", default="geo-provenance.json")
    args = ap.parse_args(argv)

    regions = load_regions(args.regions_csv)
    features = []
    for path in args.seq:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip().lstrip("\x1e")
                if line:
                    features.append(json.loads(line))
    chosen, missing = pick(features, regions)
    out = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"region_id": rid, "name": regions[rid]["name"]},
         "geometry": c["geometry"]} for rid, c in sorted(chosen.items())]}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    with open(args.provenance, "w", encoding="utf-8") as f:
        json.dump({rid: f"relation/{c['_osm_id']}" for rid, c in sorted(chosen.items())}, f, indent=1)
    print(f"matched {len(chosen)}/{len(regions)}; missing: {missing}", file=sys.stderr)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
