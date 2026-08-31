// Thin fetch wrapper over the FastAPI backend. Types come from
// `npm run gen-types` (openapi-typescript against api/openapi.json) — see
// docs/FRONTEND_PLAN.md §10: "Frontend types are generated ... never hand-written."
import type { components } from "./types";

export type ClaimRow = components["schemas"]["ClaimRow"];
export type ClaimDetail = components["schemas"]["ClaimDetail"];
export type ClaimsPage = components["schemas"]["ClaimsPage"];
export type RunSummaryRow = components["schemas"]["RunSummaryRow"];
export type RunDetail = components["schemas"]["RunDetail"];
export type SourceRow = components["schemas"]["SourceRow"];
export type HighlightQuad = components["schemas"]["HighlightQuad"];
export type ConfigStatus = components["schemas"]["ConfigStatus"];
export type CompareResult = components["schemas"]["CompareResult"];
export type RunCreateResponse = components["schemas"]["RunCreateResponse"];
export type RetryResponse = components["schemas"]["RetryResponse"];
export type Verdict = "passed" | "failed" | "unresolved_source" | "skipped";
export type RunStatus = "queued" | "running" | "awaiting_login" | "complete" | "failed";

const BASE = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  listRuns: () => req<RunSummaryRow[]>("/runs"),
  getRun: (runId: string) => req<RunDetail>(`/runs/${runId}`),
  deleteRun: (runId: string) => req<{ ok: boolean }>(`/runs/${runId}`, { method: "DELETE" }),
  listPdfs: () => req<string[]>("/pdfs"),
  createRunFromPath: (pdfPath: string) => {
    const form = new FormData();
    form.set("pdf_path", pdfPath);
    return req<RunCreateResponse>("/runs", { method: "POST", body: form });
  },
  createRunFromUpload: (file: File) => {
    const form = new FormData();
    form.set("pdf", file);
    return req<RunCreateResponse>("/runs", { method: "POST", body: form });
  },
  confirmLogin: (runId: string) =>
    req<{ ok: boolean }>(`/runs/${runId}/login-complete`, { method: "POST" }),

  listClaims: (runId: string, params: Record<string, string | number | boolean | undefined>) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "") qs.set(k, String(v));
    });
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return req<ClaimsPage>(`/runs/${runId}/claims${suffix}`);
  },
  getClaim: (runId: string, claimId: string) =>
    req<ClaimDetail>(`/runs/${runId}/claims/${encodeURIComponent(claimId)}`),

  listSources: (runId: string) => req<SourceRow[]>(`/runs/${runId}/sources`),
  retrySource: (runId: string, citationId: string, overrideUrl?: string) =>
    req<RetryResponse>(`/runs/${runId}/sources/${encodeURIComponent(citationId)}/retry`, {
      method: "POST",
      body: JSON.stringify({ override_url: overrideUrl ?? null }),
    }),

  paperPdfUrl: (runId: string) => `${BASE}/runs/${runId}/paper.pdf`,
  getHighlights: (runId: string) => req<HighlightQuad[]>(`/runs/${runId}/highlights`),

  getConfig: () => req<ConfigStatus>("/config"),
  compareRuns: (a: string, b: string) =>
    req<CompareResult>(`/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`),

  eventsUrl: (runId: string) => `${BASE}/runs/${runId}/events`,
};
