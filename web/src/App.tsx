// Нишемер: карта «Ниша → где» и «Регион → что нужно» со шкалой времени (T2.2, docs/04-ux.md).
import { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "./api";
import { MapView } from "./MapView";
import { Footer, Hero, Legend, Timeline, TopList } from "./Panels";
import {
  METRICS, THEMES, buildSeries, fixAntimeridian, formatValue, makeScale, parseState, parseTheme, stateToSearch,
  topN, valuesAt, withTheme, type MetricId, type Series, type ViewState,
} from "./model";

// Вариант T2.4 (?theme=tablo|magma|led) — на всё время жизни страницы.
const THEME = parseTheme(window.location.search);
document.documentElement.dataset.theme = THEME;

interface Refs {
  meta: api.Meta;
  needs: api.Need[];
  regions: Map<string, string>;
  geo: api.Geo;
}

const EMPTY: Series = { periods: [], byKey: new Map() };
const UNIT_NOTE: Record<MetricId, string> = {
  msp_active: "Активные субъекты МСП по основному ОКВЭД, реестр ФНС на 10-е число. Измерено.",
  msp_growth_12m: "Изменение числа активных субъектов за 12 месяцев. Измерено.",
};

function useSeries(spec: api.QuerySpec | null, key: "region_id" | "need_id") {
  const [res, setRes] = useState<{ series: Series; error: string | null; loading: boolean }>({
    series: EMPTY, error: null, loading: false,
  });
  const body = spec ? JSON.stringify(spec) : null;
  useEffect(() => {
    if (!body) return setRes({ series: EMPTY, error: null, loading: false });
    const ctl = new AbortController();
    setRes((r) => ({ ...r, loading: true }));
    api.query(JSON.parse(body) as api.QuerySpec, ctl.signal)
      .then((q) => setRes({ series: buildSeries(q.rows, key), error: null, loading: false }))
      .catch((e: unknown) => {
        if (ctl.signal.aborted) return;
        setRes({ series: EMPTY, error: e instanceof Error ? e.message : String(e), loading: false });
      });
    return () => ctl.abort();
  }, [body, key]);
  return res;
}

export function App() {
  const [refs, setRefs] = useState<Refs | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);
  const [view, setView] = useState<ViewState>(() => parseState(window.location.search));
  const [hover, setHover] = useState<{ id: string; name: string; x: number; y: number } | null>(null);

  useEffect(() => {
    Promise.all([api.getMeta(), api.getNeeds(), api.getRegions(), api.getGeo()])
      .then(([meta, needs, regions, geo]) =>
        setRefs({ meta, needs, regions: new Map(regions.map((r) => [r.region_id, r.name])), geo: fixAntimeridian(geo) }),
      )
      .catch((e: unknown) => setFatal(e instanceof Error ? e.message : String(e)));
  }, []);

  const update = useCallback((patch: Partial<ViewState>) => setView((v) => ({ ...v, ...patch })), []);
  useEffect(() => {
    window.history.replaceState(null, "", withTheme(stateToSearch(view), THEME));
  }, [view]);

  const need = view.need ?? (refs?.needs.find((n) => n.id === "restaurants_cafes") ?? refs?.needs[0])?.id ?? null;
  const metric = view.metric;

  const mapSpec: api.QuerySpec | null = !refs ? null : view.mode === "niche" && need
    ? { metrics: [metric], group_by: ["region_id", "period"], filters: [{ dim: "need_id", values: [need] }] }
    : { metrics: [metric], group_by: ["region_id", "period"] };
  const listSpec: api.QuerySpec | null = refs && view.mode === "region" && view.region
    ? { metrics: [metric], group_by: ["need_id", "period"], filters: [{ dim: "region_id", values: [view.region] }] }
    : null;
  const mapS = useSeries(mapSpec, "region_id");
  const listS = useSeries(listSpec, "need_id");

  const periods = mapS.series.periods;
  const t = view.t && periods.includes(view.t) ? view.t : periods[periods.length - 1] ?? null;
  const scale = useMemo(() => makeScale(mapS.series, METRICS[metric].diverging, THEMES[THEME]), [mapS.series, metric]);
  const mapVals = useMemo(() => (t ? valuesAt(mapS.series, t) : new Map<string, number>()), [mapS.series, t]);
  const fill = useCallback((id: string) => scale.color(mapVals.get(id)), [scale, mapVals]);

  const needName = useMemo(() => new Map(refs?.needs.map((n) => [n.id, n.name]) ?? []), [refs]);
  const items = useMemo(() => {
    if (!t) return [];
    if (view.mode === "niche")
      return topN(mapVals).map(([id, value]) => ({ id, value, label: refs?.regions.get(id) ?? id }));
    return topN(valuesAt(listS.series, t)).map(([id, value]) => ({ id, value, label: needName.get(id) ?? id }));
  }, [t, view.mode, mapVals, listS.series, refs, needName]);

  if (fatal) return <div className="fatal">Не удалось загрузить данные: {fatal}</div>;
  if (!refs) return <div className="fatal muted">Загрузка карты…</div>;

  const regionName = view.region ? refs.regions.get(view.region) ?? view.region : null;
  const error = mapS.error ?? listS.error;
  const title = view.mode === "niche"
    ? `Где больше всего: ${needName.get(need ?? "") ?? "—"}`
    : regionName ? `Ниши региона: ${regionName}` : "Выберите регион на карте";

  return (
    <div className="app">
      <header className="hdr">
        <a className="logo" href="/">Нишемер</a>
        <div className="modes" role="tablist">
          <button role="tab" aria-selected={view.mode === "niche"} onClick={() => update({ mode: "niche" })}>
            Ниша → где
          </button>
          <button role="tab" aria-selected={view.mode === "region"} onClick={() => update({ mode: "region" })}>
            Регион → что
          </button>
        </div>
        {view.mode === "niche" ? (
          <select aria-label="Ниша" value={need ?? ""} onChange={(e) => update({ need: e.target.value })}>
            {refs.needs.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
          </select>
        ) : (
          <select aria-label="Регион" value={view.region ?? ""} onChange={(e) => update({ region: e.target.value || null })}>
            <option value="">— регион —</option>
            {[...refs.regions].sort((a, b) => a[1].localeCompare(b[1], "ru")).map(([id, name]) => (
              <option key={id} value={id}>{name}</option>
            ))}
          </select>
        )}
        <select aria-label="Метрика" value={metric} onChange={(e) => update({ metric: e.target.value as MetricId })}>
          {(Object.keys(METRICS) as MetricId[]).map((m) => <option key={m} value={m}>{METRICS[m].short}</option>)}
        </select>
        <span className="beta" title="Только измеренные данные; прогнозов пока нет">бета · факты</span>
      </header>

      <main className="body">
        <div className="mapwrap">
          <MapView
            geo={refs.geo}
            palette={THEMES[THEME]}
            fill={fill}
            fillKey={`${metric}|${need}|${view.mode}|${t}`}
            selected={view.region}
            onHover={(h) => setHover(h ? { id: h.region.region_id, name: h.region.name, x: h.x, y: h.y } : null)}
            onClick={(id) => update({ mode: "region", region: id })}
          />
          {hover && (
            <div className="tip" style={{ left: hover.x + 12, top: hover.y + 12 }}>
              <b>{hover.name}</b>
              <div>{formatValue(metric, mapVals.get(hover.id))}</div>
            </div>
          )}
          {(mapS.loading || listS.loading) && <div className="loading">обновляю…</div>}
          {error && <div className="err">{error}</div>}
          <Legend scale={scale} metric={metric} unitNote={UNIT_NOTE[metric]} />
          <Hero
            title={view.mode === "niche" ? needName.get(need ?? "") ?? "—" : regionName ?? "Выберите регион"}
            t={t}
            leader={items[0] ?? null}
            metric={metric}
          />
        </div>
        <TopList
          title={title}
          items={items}
          metric={metric}
          selected={view.mode === "niche" ? view.region : need}
          hint={view.mode === "niche" ? "Открыть ниши региона" : "Показать нишу на карте"}
          onPick={(id) => (view.mode === "niche" ? update({ mode: "region", region: id }) : update({ mode: "niche", need: id }))}
        />
      </main>

      <Timeline periods={periods} t={t} onChange={(p) => update({ t: p })} />
      <Footer snapshot={refs.meta.snapshot} />
    </div>
  );
}
