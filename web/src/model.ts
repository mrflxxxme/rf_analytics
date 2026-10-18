// Чистые функции: состояние в URL, ряды по периодам, шкалы цвета, починка антимеридиана.
// Покрыты тестами (model.test.ts).
import type { Geo, Row } from "./api";

export type Mode = "niche" | "region";
export type MetricId = "msp_active" | "msp_growth_12m";

export const METRICS: Record<MetricId, { short: string; diverging: boolean }> = {
  msp_active: { short: "Число субъектов", diverging: false },
  msp_growth_12m: { short: "Прирост за 12 мес.", diverging: true },
};

export interface ViewState {
  mode: Mode;
  need: string | null;
  region: string | null;
  metric: MetricId;
  t: string | null; // период ISO (YYYY-MM-DD)
}

const isMetric = (v: string | null): v is MetricId => v !== null && v in METRICS;

/** Каждое состояние экрана — URL (docs/04-ux.md, «Ограничения»). */
export function parseState(search: string): ViewState {
  const p = new URLSearchParams(search);
  const metric = p.get("m");
  const t = p.get("t");
  return {
    mode: p.get("mode") === "region" ? "region" : "niche",
    need: p.get("need"),
    region: p.get("region"),
    metric: isMetric(metric) ? metric : "msp_active",
    t: t && /^\d{4}-\d{2}-\d{2}$/.test(t) ? t : null,
  };
}

export function stateToSearch(s: ViewState): string {
  const p = new URLSearchParams();
  p.set("mode", s.mode);
  if (s.need) p.set("need", s.need);
  if (s.region) p.set("region", s.region);
  p.set("m", s.metric);
  if (s.t) p.set("t", s.t);
  return `?${p.toString()}`;
}

/** Ряды «ключ × период → значение» из строк /api/query. */
export interface Series {
  periods: string[];
  byKey: Map<string, Map<string, number>>;
}

export function buildSeries(rows: Row[], key: "region_id" | "need_id"): Series {
  const periods = new Set<string>();
  const byKey = new Map<string, Map<string, number>>();
  for (const r of rows) {
    const k = r[key];
    if (k === undefined || r.value === null || !Number.isFinite(r.value)) continue;
    if (key === "need_id" && k === "_all") continue; // итог региона — не ниша
    periods.add(r.period);
    let m = byKey.get(k);
    if (!m) byKey.set(k, (m = new Map()));
    m.set(r.period, r.value);
  }
  return { periods: [...periods].sort(), byKey };
}

export function valuesAt(s: Series, t: string): Map<string, number> {
  const out = new Map<string, number>();
  for (const [k, m] of s.byKey) {
    const v = m.get(t);
    if (v !== undefined) out.set(k, v);
  }
  return out;
}

export function topN(values: Map<string, number>, n = 10): [string, number][] {
  return [...values].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, n);
}

export type RGB = [number, number, number];

/** Варианты hero-экрана T2.4 (?theme=): CSS-токены — в styles.css, шкалы и цвета карты — здесь. */
export type ThemeId = "tablo" | "magma" | "led";

export interface Palette {
  name: string;
  seq: RGB[]; // последовательная шкала, от малого к большому
  div: RGB[]; // расходящаяся: падение → 0 → рост
  bg: string; // фон карты (= --bg)
  noData: RGB;
  border: RGB; // границы регионов
}

export const THEMES: Record<ThemeId, Palette> = {
  // А: нейтральная тема T2.2 — сине-зелёно-жёлтая шкала, крупная дата на карте.
  tablo: {
    name: "Табло",
    seq: [[29, 42, 78], [33, 102, 140], [32, 158, 136], [124, 200, 84], [240, 226, 70]],
    div: [[214, 96, 77], [244, 165, 130], [60, 66, 78], [146, 197, 222], [67, 147, 195]],
    bg: "#0e1116", noData: [52, 58, 68], border: [14, 17, 22],
  },
  // Б: тёплый чёрный, шкала «магма», заголовок-ниша как у издания.
  magma: {
    name: "Магма",
    seq: [[40, 17, 66], [114, 31, 129], [183, 55, 121], [241, 96, 93], [254, 176, 120], [252, 253, 191]],
    div: [[94, 60, 153], [178, 171, 210], [58, 50, 46], [253, 184, 99], [230, 97, 1]],
    bg: "#120d0b", noData: [58, 50, 46], border: [18, 13, 11],
  },
  // В: графит и один оттенок (лёд), сводка-чипы вместо крупной даты.
  led: {
    name: "Лёд",
    seq: [[22, 38, 52], [27, 74, 99], [36, 120, 150], [86, 180, 206], [200, 240, 250]],
    div: [[255, 122, 89], [140, 82, 70], [44, 50, 58], [44, 112, 140], [110, 220, 245]],
    bg: "#0a0d10", noData: [40, 46, 54], border: [10, 13, 16],
  },
};

const isTheme = (v: string | null): v is ThemeId => v !== null && v in THEMES;

/** Тема — параметр предпросмотра, не часть состояния экрана: по умолчанию «Табло». */
export function parseTheme(search: string): ThemeId {
  const v = new URLSearchParams(search).get("theme");
  return isTheme(v) ? v : "tablo";
}

export function withTheme(search: string, theme: ThemeId): string {
  return theme === "tablo" ? search : `${search}&theme=${theme}`;
}

function ramp(stops: RGB[], x: number): RGB {
  const c = Math.min(1, Math.max(0, x)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(c));
  const f = c - i;
  const a = stops[i]!;
  const b = stops[i + 1]!;
  return [0, 1, 2].map((j) => Math.round(a[j]! + (b[j]! - a[j]!) * f)) as RGB;
}

export interface Scale {
  color(v: number | undefined): RGB | null;
  min: number;
  max: number;
  diverging: boolean;
  stops: RGB[]; // для легенды
}

/** Домен по всем периодам ряда: при проигрывании видно рост, а не перекраску под каждый год. */
export function makeScale(s: Series, diverging: boolean, pal: Palette = THEMES.tablo): Scale {
  const SEQ = pal.seq;
  const DIV = pal.div;
  const all: number[] = [];
  for (const m of s.byKey.values()) for (const v of m.values()) all.push(v);
  if (diverging) {
    const abs = all.map(Math.abs).sort((a, b) => a - b);
    const lim = abs.length ? abs[Math.floor((abs.length - 1) * 0.95)]! || 1e-9 : 1;
    return {
      min: -lim, max: lim, diverging, stops: DIV,
      color: (v) => (v === undefined ? null : ramp(DIV, (v / lim + 1) / 2)),
    };
  }
  const pos = all.filter((v) => v > 0);
  const lo = pos.length ? Math.min(...pos) : 1;
  const hi = pos.length ? Math.max(...pos) : 1;
  const span = Math.log(hi) - Math.log(lo) || 1;
  return {
    min: lo, max: hi, diverging, stops: SEQ,
    color: (v) => (v === undefined ? null : ramp(SEQ, v > 0 ? (Math.log(v) - Math.log(lo)) / span : 0)),
  };
}

const NUM = new Intl.NumberFormat("ru-RU");
const PCT = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1, signDisplay: "exceptZero" });

/** msp_growth_12m в API — ln(t / t−12); на экране — проценты (exp − 1), это та же измеренная величина. */
export function formatValue(metric: MetricId, v: number | undefined): string {
  if (v === undefined) return "нет данных";
  return metric === "msp_growth_12m" ? `${PCT.format((Math.exp(v) - 1) * 100)} %` : NUM.format(Math.round(v));
}

export function formatPeriod(t: string): string {
  const [y, m] = t.split("-");
  const months = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
  return `${months[Number(m) - 1] ?? m} ${y}`;
}

/** Чукотка (87) разрезана по 180°: восточные части сдвигаем на +360°, чтобы полигон был цельным. */
export function fixAntimeridian(geo: Geo): Geo {
  const shift = (c: number[]): number[] => (c[0]! < 0 ? [c[0]! + 360, ...c.slice(1)] : c);
  return {
    ...geo,
    features: geo.features.map((f) => {
      const g = f.geometry;
      if (f.properties.region_id !== "87") return f;
      if (g.type === "MultiPolygon")
        return { ...f, geometry: { ...g, coordinates: g.coordinates.map((p) => p.map((r) => r.map(shift))) } };
      if (g.type === "Polygon") return { ...f, geometry: { ...g, coordinates: g.coordinates.map((r) => r.map(shift)) } };
      return f;
    }),
  };
}
