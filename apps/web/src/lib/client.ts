// Typed API client generated from FastAPI's OpenAPI schema (src/lib/api/schema.d.ts - do not hand-edit that file).
import createClient from "openapi-fetch";
import type { paths, components } from "./api/schema";

export const api = createClient<paths>({ baseUrl: "", credentials: "include" });
export type Schemas = components["schemas"];
export type JobRow = Schemas["JobRow"];
export type JobDetail = Schemas["JobDetail"];
export type ProposalOut = Schemas["ProposalOut"];
export type UserOut = Schemas["UserOut"];
export type Settings = Schemas["Settings"];

/** Unwraps an openapi-fetch result, throwing a readable error. */
export function unwrap<T>(r: { data?: T; error?: unknown; response: Response }): T {
  if (r.error !== undefined || r.data === undefined) {
    const e = r.error as { detail?: unknown } | undefined;
    const msg = typeof e?.detail === "string" ? e.detail : JSON.stringify(e?.detail ?? e ?? r.response.statusText);
    throw new Error(`${r.response.status}: ${msg}`);
  }
  return r.data;
}

export const fmtMoney = (q?: { amount?: number; bid_type?: string } | null) =>
  q?.amount ? `$${Math.round(q.amount).toLocaleString()}${q.bid_type === "hourly" ? "/h" : ""}` : "—";
export const pct = (x?: number | null) => (x === null || x === undefined ? "—" : `${Math.round(x * 100)}%`);
export const stripMarkers = (t: string) => t.replace(/\s*\[E:[^\]]+\]/g, "");
