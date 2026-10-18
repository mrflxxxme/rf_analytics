"""Семантический слой (config/metrics.yaml): белый список метрик и измерений для query-spec."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
PERIOD = "period"


def _ident(v: str) -> str:
    if not IDENT.match(v):
        raise ValueError(f"недопустимый идентификатор: {v!r}")
    return v


class Dimension(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    ref: Literal["regions", "needs"] | None = None


class TimeAxis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str
    type: Literal["date", "year"]

    _c = field_validator("column")(_ident)


class Metric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    unit: str
    kind: Literal["measured"]
    source: str
    mart: str
    time: TimeAxis
    grain: list[str] = Field(min_length=1)
    defaults: dict[str, str] = {}
    where: dict[str, str] = {}
    expr: str
    rollup: bool

    _m = field_validator("mart")(_ident)

    @field_validator("grain")
    @classmethod
    def _grain(cls, v: list[str]) -> list[str]:
        for d in v:
            _ident(d)
        if PERIOD not in v:
            raise ValueError("grain должен включать period")
        return v

    @field_validator("where")
    @classmethod
    def _where(cls, v: dict[str, str]) -> dict[str, str]:
        for k in v:
            _ident(k)
        return v

    @property
    def columns(self) -> list[str]:
        """Измерения-колонки витрины (без period)."""
        return [d for d in self.grain if d != PERIOD]


class Semantic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    dimensions: dict[str, Dimension]
    metrics: dict[str, Metric]

    @model_validator(mode="after")
    def _consistent(self) -> Semantic:
        for mid, m in self.metrics.items():
            _ident(mid)
            unknown = set(m.grain) - set(self.dimensions)
            if unknown:
                raise ValueError(f"{mid}: измерения не объявлены: {sorted(unknown)}")
            if set(m.defaults) - set(m.columns):
                raise ValueError(f"{mid}: defaults вне grain")
        return self

    @property
    def marts(self) -> set[str]:
        return {m.mart for m in self.metrics.values()}


def load(path: str | Path) -> Semantic:
    return Semantic.model_validate(yaml.safe_load(Path(path).read_text("utf-8")))
