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
// Tier 0.2 ontology. Kept in sync with src/asv/core/verdicts.py; the generated
// `types.ts` carries the same unions, these aliases just give them short names.
export type Verdict =
  | "substantiated"
  | "partially_substantiated"
  | "not_substantiated"
  | "contradicted"
  | "not_checkable";
export type NotCheckableReason =
  | "no_source_available"
  | "original_contribution"
  | "source_not_resolved"
  | "source_download_failed"
  | "abstract_only"
  | "paywall_interstitial"
  | "content_rejected"
  | "retrieval_empty"
  | "evidence_unverifiable"
  | "reference_not_found"
  | "reference_unverified"
  | "unresolvable_by_design"
  | "validation_error";
export type ContentQuality =
  | "full_text"
  | "abstract_only"
  | "paywall_interstitial"
  | "rejected";
export type ReferenceCheckRow = components["schemas"]["ReferenceCheckRow"];
export type GoldPair = components["schemas"]["GoldPair"];
export type GoldStats = components["schemas"]["GoldStats"];
export type LabelRequest = components["schemas"]["LabelRequest"];
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
  // Tier 0.6 bibliography audit: every reference in the paper, whether the
  // free indexes found it, and whether it has been retracted.
  listReferences: (runId: string) =>
    req<ReferenceCheckRow[]>(`/runs/${runId}/references`),

  // Tier 0.4 gold set. Not scoped to a run: the benchmark spans runs, and
  // lives in the repo rather than in runs/.
  benchmarkStats: (name = "gold") => req<GoldStats>(`/benchmark/${name}/stats`),
  benchmarkPairs: (
    params: { unlabelled_only?: boolean; needs_second_pass?: boolean },
    name = "gold"
  ) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined) qs.set(k, String(v));
    });
    return req<GoldPair[]>(`/benchmark/${name}/pairs?${qs.toString()}`);
  },
  benchmarkLabel: (body: LabelRequest, name = "gold") =>
    req<GoldPair>(`/benchmark/${name}/label`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
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
