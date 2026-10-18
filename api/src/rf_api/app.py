"""FastAPI-приложение RADAR (docs/01-architecture.md, «API»). Запуск: uvicorn --factory rf_api.app:create_app."""

from __future__ import annotations

import datetime as dt
import math
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from rf_api import query as q
from rf_api import refs as rf
from rf_api import semantic
from rf_api.store import NoSnapshot, Store

NOINDEX = "noindex, nofollow"  # D27: API не индексируется


def _jsonable(v: object) -> object:
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v.isoformat() if isinstance(v, dt.date) else v


def create_app(marts_dir: str | Path | None = None, config_dir: str | Path | None = None) -> FastAPI:
    marts_dir = marts_dir or os.environ.get("RF_MARTS_DIR", "/marts")
    config_dir = Path(config_dir or os.environ.get("RF_CONFIG_DIR", "/config"))
    sem = semantic.load(config_dir / "metrics.yaml")
    refs = rf.load(config_dir)
    store = Store(marts_dir, sem.marts)
    app = FastAPI(title="RADAR API", version="0.1.0", docs_url=None, redoc_url=None, openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def noindex(request: Request, call_next):  # type: ignore[no-untyped-def]
        resp = await call_next(request)
        resp.headers["X-Robots-Tag"] = NOINDEX
        return resp

    @app.exception_handler(NoSnapshot)
    async def no_snapshot(_: Request, exc: NoSnapshot) -> JSONResponse:
        return JSONResponse({"error": "no_snapshot", "message": str(exc)}, status_code=503)

    @app.exception_handler(q.SpecError)
    async def spec_error(_: Request, exc: q.SpecError) -> JSONResponse:
        return JSONResponse(exc.detail(), status_code=422)

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {"ok": True}

    @app.get("/api/meta")
    def meta() -> dict[str, object]:
        snap = store.get()
        m = snap.manifest
        keys = ("snapshot", "created_at", "git_sha", "methodology_version", "taxonomy_version", "data_date")
        sources = m.get("sources") or {}
        return {
            **{k: m.get(k) for k in keys},
            "beta": True,
            "calibrated": False,  # прогнозов нет до T3.5; на M1 только измеренные факты (Э-51)
            "backtest": m.get("backtest"),
            "sources": {
                "fns_rsmp": [{k: s.get(k) for k in ("snapshot_date", "docs_parsed")} for s in sources.get("fns_rsmp", [])],
                "rosstat": len(sources.get("rosstat", [])),
            },
            "marts": sorted(snap.marts),
            "semantic_version": sem.version,
        }

    @app.get("/api/geo")
    def geo() -> FileResponse:
        return FileResponse(refs.geojson, media_type="application/geo+json",
                            headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/api/regions")
    def regions() -> dict[str, object]:
        return {"regions": refs.regions}

    @app.get("/api/needs")
    def needs() -> dict[str, object]:
        return {"taxonomy_version": refs.taxonomy_version,
                "needs": [n for n in refs.needs if n["status"] == "active"]}

    @app.get("/api/metrics")
    def metrics() -> dict[str, object]:
        return {"version": sem.version,
                "dimensions": {k: d.model_dump() for k, d in sem.dimensions.items()},
                "metrics": {k: {f: getattr(m, f) for f in ("label", "unit", "kind", "source", "grain", "rollup")}
                            for k, m in sem.metrics.items()}}

    @app.post("/api/query")
    def run_query(spec: q.QuerySpec) -> JSONResponse:
        plans = q.plan(spec, sem, refs)
        snap = store.get()
        missing = sorted({p.metric.mart for p in plans} - snap.marts)
        if missing:
            return JSONResponse({"error": "mart_missing", "snapshot": snap.id,
                                 "message": f"в snapshot нет витрин: {', '.join(missing)}"}, status_code=409)
        rows: list[dict[str, object]] = []
        truncated = False
        cur = snap.con.cursor()
        try:
            for p in plans:
                res = cur.execute(p.sql, p.params).fetchall()
                if len(res) > spec.limit:
                    truncated, res = True, res[: spec.limit]
                for r in res:
                    rec = {"metric": p.metric_id, **{d: _jsonable(v) for d, v in zip(p.dims, r[:-1])}}
                    rec["value"] = _jsonable(r[-1])
                    rows.append(rec)
        finally:
            cur.close()
        return JSONResponse({
            "snapshot": snap.id,
            "spec": spec.model_dump(mode="json", by_alias=True),
            "defaults": q.need_default_note(sem, spec),
            "metrics": {p.metric_id: {"label": p.metric.label, "unit": p.metric.unit, "kind": p.metric.kind,
                                      "source": p.metric.source} for p in plans},
            "rows": rows,
            "truncated": truncated,
        })

    return app
