// Клиент API RADAR (docs/01-architecture.md, «API»). Ответы валидируются zod на границе.
import { z } from "zod";
import type { FeatureCollection, Geometry } from "geojson";

const Meta = z.object({
  snapshot: z.string(),
  data_date: z.string().nullable().optional(),
  methodology_version: z.string().nullable().optional(),
  beta: z.boolean(),
  marts: z.array(z.string()),
});
export type Meta = z.infer<typeof Meta>;

const Need = z.object({ id: z.string(), name: z.string() }).passthrough();
export type Need = z.infer<typeof Need>;

const Region = z.object({ region_id: z.string(), name: z.string() }).passthrough();
export type Region = z.infer<typeof Region>;

const Row = z.object({
  metric: z.string(),
  region_id: z.string().optional(),
  need_id: z.string().optional(),
  period: z.string(),
  value: z.number().nullable(),
});
export type Row = z.infer<typeof Row>;

const QueryResult = z.object({
  snapshot: z.string(),
  metrics: z.record(z.object({ label: z.string(), unit: z.string(), kind: z.string(), source: z.string() })),
  rows: z.array(Row),
  truncated: z.boolean(),
});
export type QueryResult = z.infer<typeof QueryResult>;

export type RegionProps = { region_id: string; name: string };
export type Geo = FeatureCollection<Geometry, RegionProps>;

export interface QuerySpec {
  metrics: string[];
  filters?: { dim: string; values: string[] }[];
  group_by?: string[];
  period?: { from?: string; to?: string };
  limit?: number;
}

export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message);
  }
}

async function json(url: string, init?: RequestInit): Promise<unknown> {
  const r = await fetch(url, init);
  if (!r.ok) {
    let code = "http_error";
    let message = `${url}: HTTP ${r.status}`;
    try {
      const b = (await r.json()) as { error?: string; message?: string };
      code = b.error ?? code;
      message = b.message ?? message;
    } catch {
      /* тело не JSON */
    }
    throw new ApiError(r.status, code, message);
  }
  return r.json();
}

export const getMeta = async (): Promise<Meta> => Meta.parse(await json("/api/meta"));
export const getNeeds = async (): Promise<Need[]> =>
  z.object({ needs: z.array(Need) }).parse(await json("/api/needs")).needs;
export const getRegions = async (): Promise<Region[]> =>
  z.object({ regions: z.array(Region) }).parse(await json("/api/regions")).regions;
export const getGeo = async (): Promise<Geo> => (await json("/api/geo")) as Geo;

export const query = async (spec: QuerySpec, signal?: AbortSignal): Promise<QueryResult> =>
  QueryResult.parse(
    await json("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(spec),
      signal,
    }),
  );
