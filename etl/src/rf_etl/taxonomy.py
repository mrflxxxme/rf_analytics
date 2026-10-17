"""Таксономия потребностей (config/taxonomy.yaml): схема, проверки, маппинг ОКВЭД → need_id."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

NEED_ID = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
OKVED = re.compile(r"^\d{2}(\.\d{1,2}(\.\d{1,2})?)?$")


class Need(BaseModel):
    id: str
    name: str
    okved: list[str] = Field(min_length=1)
    osm_tags: list[str] = []
    search_keys: list[str] = []
    franchise_examples: list[str] = []
    min_entities_rf: int | None = None
    status: str = "active"

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not NEED_ID.match(v):
            raise ValueError(f"need_id {v!r}: только a-z, 0-9, _")
        return v

    @field_validator("okved")
    @classmethod
    def _okved(cls, v: list[str]) -> list[str]:
        bad = [c for c in v if not OKVED.match(c)]
        if bad:
            raise ValueError(f"неверные коды ОКВЭД: {bad}")
        return v


class Taxonomy(BaseModel):
    version: str
    status: str
    defaults: dict[str, int] = {}
    needs: list[Need]

    def threshold(self, need: Need) -> int:
        return need.min_entities_rf or self.defaults.get("min_entities_rf", 0)


def load(path: str | Path) -> Taxonomy:
    tax = Taxonomy.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    validate(tax)
    return tax


def _covers(prefix: str, code: str) -> bool:
    return code == prefix or code.startswith(prefix + ".")


def validate(tax: Taxonomy) -> None:
    ids = [n.id for n in tax.needs]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"повтор need_id: {sorted(dupes)}")
    owners: list[tuple[str, str]] = [(p, n.id) for n in tax.needs for p in n.okved]
    for i, (p1, n1) in enumerate(owners):
        for p2, n2 in owners[i + 1:]:
            if n1 != n2 and (_covers(p1, p2) or _covers(p2, p1)):
                raise ValueError(f"ОКВЭД пересекаются без доли: {n1}:{p1} и {n2}:{p2}")


def need_for_okved(tax: Taxonomy, code: str | None) -> str | None:
    """need_id для основного кода ОКВЭД субъекта; самый длинный совпавший префикс."""
    if not code:
        return None
    best: tuple[int, str] | None = None
    for need in tax.needs:
        if need.status != "active":
            continue
        for p in need.okved:
            if _covers(p, code) and (best is None or len(p) > best[0]):
                best = (len(p), need.id)
    return best[1] if best else None
