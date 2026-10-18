import { describe, expect, it } from "vitest";
import type { Geo, Row } from "./api";
import {
  THEMES, buildSeries, fixAntimeridian, formatValue, makeScale, parseState, parseTheme, stateToSearch, topN, valuesAt,
  withTheme,
} from "./model";

const rows: Row[] = [
  { metric: "msp_active", region_id: "77", period: "2017-10-10", value: 100 },
  { metric: "msp_active", region_id: "77", period: "2026-10-10", value: 200 },
  { metric: "msp_active", region_id: "78", period: "2026-10-10", value: 50 },
  { metric: "msp_active", region_id: "79", period: "2026-10-10", value: null },
];

describe("состояние в URL", () => {
  it("туда и обратно", () => {
    const s = { mode: "region" as const, need: "bars_pubs", region: "77", metric: "msp_growth_12m" as const, t: "2020-10-10" };
    expect(parseState(stateToSearch(s))).toEqual(s);
  });
  it("мусор → значения по умолчанию", () => {
    expect(parseState("?mode=x&m=drop&t=2020")).toEqual({ mode: "niche", need: null, region: null, metric: "msp_active", t: null });
  });
});

describe("ряды", () => {
  it("периоды отсортированы, null пропущен", () => {
    const s = buildSeries(rows, "region_id");
    expect(s.periods).toEqual(["2017-10-10", "2026-10-10"]);
    expect(s.byKey.has("79")).toBe(false);
    expect(topN(valuesAt(s, "2026-10-10"))).toEqual([["77", 200], ["78", 50]]);
  });
  it("итог региона _all не попадает в список ниш", () => {
    const s = buildSeries([{ metric: "m", need_id: "_all", period: "2026-10-10", value: 9 },
      { metric: "m", need_id: "bars_pubs", period: "2026-10-10", value: 1 }], "need_id");
    expect([...s.byKey.keys()]).toEqual(["bars_pubs"]);
  });
});

describe("шкала", () => {
  it("домен по всем периодам: рост виден при проигрывании", () => {
    const sc = makeScale(buildSeries(rows, "region_id"), false);
    expect(sc.min).toBe(50);
    expect(sc.max).toBe(200);
    expect(sc.color(50)).toEqual([29, 42, 78]);
    expect(sc.color(200)).toEqual([240, 226, 70]);
    expect(sc.color(undefined)).toBeNull();
  });
  it("расходящаяся — симметрична вокруг нуля", () => {
    const sc = makeScale(buildSeries([{ metric: "g", region_id: "1", period: "p", value: -0.2 },
      { metric: "g", region_id: "2", period: "p", value: 0.1 }], "region_id"), true);
    expect(sc.min).toBe(-sc.max);
    expect(sc.color(0)).toEqual([60, 66, 78]);
  });
});

describe("темы T2.4", () => {
  it("?theme= разбирается, мусор → «Табло», параметр переживает перезапись URL", () => {
    expect(parseTheme("?mode=niche&theme=magma")).toBe("magma");
    expect(parseTheme("?theme=x")).toBe("tablo");
    expect(withTheme("?mode=niche", "led")).toBe("?mode=niche&theme=led");
    expect(withTheme("?mode=niche", "tablo")).toBe("?mode=niche");
  });
  it("у каждой темы концы шкалы — её собственные", () => {
    const s = buildSeries(rows, "region_id");
    for (const pal of Object.values(THEMES)) {
      const sc = makeScale(s, false, pal);
      expect(sc.color(50)).toEqual(pal.seq[0]);
      expect(sc.color(200)).toEqual(pal.seq[pal.seq.length - 1]);
      expect(sc.stops).toBe(pal.seq);
    }
  });
});

it("прирост: ln → проценты", () => {
  expect(formatValue("msp_growth_12m", Math.log(1.1))).toBe("+10 %");
  expect(formatValue("msp_active", 12345)).toBe("12 345");
});

it("Чукотка склеивается через 180°", () => {
  const geo: Geo = { type: "FeatureCollection", features: [{
    type: "Feature", properties: { region_id: "87", name: "Чукотка" },
    geometry: { type: "MultiPolygon", coordinates: [[[[179, 65], [180, 66], [179, 66], [179, 65]]], [[[-180, 65], [-170, 66], [-180, 66], [-180, 65]]]] },
  }] };
  const g = fixAntimeridian(geo).features[0]!.geometry;
  const xs = g.type === "MultiPolygon" ? g.coordinates.flat(2).map((c) => c[0]!) : [];
  expect(Math.min(...xs)).toBeGreaterThanOrEqual(179);
  expect(Math.max(...xs)).toBe(190);
});
