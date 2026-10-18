"""Query-spec — единственный способ получить данные (docs/01-architecture.md, «API»).

`{metrics[], filters[], group_by, period, compare_to, map_binding}`. Схема — Pydantic,
смысл — по семантическому слою: метрики, измерения и значения справочников только из
белого списка. В SQL из запроса попадают лишь значения, и только параметрами;
идентификаторы и выражения берутся из config/metrics.yaml.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from rf_api.refs import ALL_NEEDS, Refs
from rf_api.semantic import PERIOD, Metric, Semantic

MAX_ROWS = 50_000


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dim: str
    values: list[str] = Field(min_length=1, max_length=200)


class Period(BaseModel):
    """Без `period` в group_by — одна точка: последняя не позже `to`. С ним — ряд [from, to]."""
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_: dt.date | None = Field(None, alias="from")
    to: dt.date | None = None


class MapBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: str
    dim: str = "region_id"


class QuerySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metrics: list[str] = Field(min_length=1, max_length=4)
    filters: list[Filter] = Field(default=[], max_length=8)
    group_by: list[str] = Field(default=[], max_length=3)
    period: Period = Period()
    compare_to: None = None  # сравнение — после M1; пока любое значение отклоняется схемой
    map_binding: MapBinding | None = None
    limit: int = Field(default=10_000, ge=1, le=MAX_ROWS)


class SpecError(ValueError):
    """Spec синтаксически верен, но вне семантического слоя → 422."""

    def __init__(self, code: str, message: str, **extra: object) -> None:
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra

    def detail(self) -> dict[str, object]:
        return {"error": self.code, "message": self.message, **self.extra}


@dataclass
class Plan:
    metric_id: str
    metric: Metric
    sql: str
    params: list[object] = field(default_factory=list)
    dims: list[str] = field(default_factory=list)


def validate(spec: QuerySpec, sem: Semantic, refs: Refs) -> None:
    unknown = [m for m in spec.metrics if m not in sem.metrics]
    if unknown:
        raise SpecError("unknown_metric", f"метрики нет в семантическом слое: {', '.join(unknown)}",
                        allowed=sorted(sem.metrics))
    if len(set(spec.metrics)) != len(spec.metrics):
        raise SpecError("duplicate_metric", "метрика указана дважды")
    if len(set(spec.group_by)) != len(spec.group_by):
        raise SpecError("duplicate_dimension", "измерение в group_by указано дважды")
    for d in spec.group_by:
        if d not in sem.dimensions:
            raise SpecError("unknown_dimension", f"измерения нет в семантическом слое: {d}",
                            allowed=sorted(sem.dimensions))
    seen: set[str] = set()
    for f in spec.filters:
        if f.dim not in sem.dimensions or f.dim == PERIOD:
            raise SpecError("unknown_dimension", f"фильтр по измерению невозможен: {f.dim}",
                            allowed=sorted(set(sem.dimensions) - {PERIOD}))
        if f.dim in seen:
            raise SpecError("duplicate_filter", f"два фильтра по {f.dim}")
        seen.add(f.dim)
        allowed = refs.allowed(sem.dimensions[f.dim].ref)
        bad = sorted(set(f.values) - allowed) if allowed is not None else []
        if bad:
            raise SpecError("unknown_value", f"значений нет в справочнике {f.dim}: {', '.join(bad[:10])}")
    p = spec.period
    if p.from_ and p.to and p.from_ > p.to:
        raise SpecError("bad_period", "period.from позже period.to")
    filters = {f.dim: f.values for f in spec.filters}
    for mid in spec.metrics:
        m = sem.metrics[mid]
        outside = [d for d in [*spec.group_by, *filters] if d not in m.grain]
        if outside:
            raise SpecError("dimension_not_in_metric", f"{mid} не разрезается по {', '.join(outside)}",
                            metric=mid, grain=m.grain)
        if not m.rollup and "region_id" not in spec.group_by and len(filters.get("region_id", [])) != 1:
            raise SpecError("no_rollup", f"{mid} не суммируется по регионам: группируйте по region_id "
                            "или выберите один регион", metric=mid)
        for d in m.columns:
            vals = filters.get(d, [])
            if d not in spec.group_by and len(vals) > 1 and m.defaults.get(d) in vals:
                raise SpecError("double_count", f"{mid}: {m.defaults[d]} вместе с другими {d} "
                                "без группировки задвоит сумму", metric=mid)
    if spec.map_binding:
        if spec.map_binding.metric not in spec.metrics:
            raise SpecError("bad_map_binding", "map_binding.metric должен быть среди metrics")
        if spec.map_binding.dim not in spec.group_by:
            raise SpecError("bad_map_binding", "map_binding.dim должен быть в group_by")


def _time_value(m: Metric, d: dt.date) -> object:
    return d.year if m.time.type == "year" else d


def plan(spec: QuerySpec, sem: Semantic, refs: Refs) -> list[Plan]:
    validate(spec, sem, refs)
    filters = {f.dim: f.values for f in spec.filters}
    plans = []
    for mid in spec.metrics:
        m = sem.metrics[mid]
        t = m.time.column
        where: list[str] = []
        params: list[object] = []
        for col, val in m.where.items():
            where.append(f"{col} = ?")
            params.append(val)
        for d in m.columns:
            if d in filters:
                where.append(f"{d} IN ({', '.join('?' * len(filters[d]))})")
                params.extend(filters[d])
            elif d not in spec.group_by and d in m.defaults:
                where.append(f"{d} = ?")
                params.append(m.defaults[d])
        if PERIOD in spec.group_by:
            if spec.period.from_:
                where.append(f"{t} >= ?")
                params.append(_time_value(m, spec.period.from_))
            if spec.period.to:
                where.append(f"{t} <= ?")
                params.append(_time_value(m, spec.period.to))
        else:
            # Одна точка: последняя дата витрины (с постоянным фильтром) не позже period.to.
            sub = [f"{c} = ?" for c in m.where]
            sub_params: list[object] = list(m.where.values())
            if spec.period.to:
                sub.append(f"{t} <= ?")
                sub_params.append(_time_value(m, spec.period.to))
            sub_sql = f"SELECT max({t}) FROM {m.mart}" + (f" WHERE {' AND '.join(sub)}" if sub else "")
            where.append(f"{t} = ({sub_sql})")
            params.extend(sub_params)
        dims = [d for d in spec.group_by if d != PERIOD]
        select = [*dims, f"{t} AS {PERIOD}"] if PERIOD in spec.group_by else list(dims)
        if PERIOD not in spec.group_by:
            select.append(f"max({t}) AS {PERIOD}")
        sql = (f"SELECT {', '.join([*select, f'{m.expr} AS value'])} FROM {m.mart}"
               + (f" WHERE {' AND '.join(where)}" if where else ""))
        group = [*dims, *([t] if PERIOD in spec.group_by else [])]
        if group:
            sql += f" GROUP BY {', '.join(group)} ORDER BY {', '.join(group)}"
        sql += " LIMIT ?"
        params.append(spec.limit + 1)
        plans.append(Plan(mid, m, sql, params, [*dims, PERIOD]))
    return plans


def need_default_note(sem: Semantic, spec: QuerySpec) -> dict[str, dict[str, str]]:
    """Какие измерения подставлены по умолчанию — показывается в ответе (чипы конструктора)."""
    grouped, filtered = set(spec.group_by), {f.dim for f in spec.filters}
    return {mid: {d: v for d, v in sem.metrics[mid].defaults.items() if d not in grouped | filtered}
            for mid in spec.metrics}


__all__ = ["ALL_NEEDS", "MAX_ROWS", "Plan", "QuerySpec", "SpecError", "need_default_note", "plan", "validate"]
