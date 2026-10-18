"""Справочники: субъекты (config/geo/regions.csv, D35) и потребности (config/taxonomy.yaml, D36)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import yaml

ALL_NEEDS = "_all"  # все субъекты региона, в т.ч. вне таксономии (витрины МСП)


@dataclass(frozen=True)
class Refs:
    regions: list[dict[str, str]]
    needs: list[dict[str, object]]
    taxonomy_version: str
    geojson: Path

    @property
    def region_ids(self) -> set[str]:
        return {r["region_id"] for r in self.regions}

    @property
    def need_ids(self) -> set[str]:
        return {str(n["id"]) for n in self.needs} | {ALL_NEEDS}

    def allowed(self, ref: str | None) -> set[str] | None:
        return {"regions": self.region_ids, "needs": self.need_ids}.get(ref or "")


def load(config_dir: str | Path) -> Refs:
    cfg = Path(config_dir)
    with open(cfg / "geo" / "regions.csv", encoding="utf-8") as f:
        regions = list(csv.DictReader(f))
    tax = yaml.safe_load((cfg / "taxonomy.yaml").read_text("utf-8"))
    needs = [
        {"id": n["id"], "name": n["name"], "okved": n["okved"], "status": n.get("status", "active")}
        for n in tax["needs"]
    ]
    return Refs(regions=regions, needs=needs, taxonomy_version=str(tax["version"]),
                geojson=cfg / "geo" / "regions.geojson")
