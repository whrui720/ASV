import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { VerdictBadge } from "./VerdictBadge";
import { ConfidenceGauge } from "./ConfidenceGauge";
import { ResolutionStepper } from "./ResolutionStepper";
import {
  CONTENT_QUALITY_LABEL,
  FLAG_LABEL,
  GROUP_LABEL,
  REASON_HINT,
  REFERENCE_STATUS_COLOR,
  REFERENCE_STATUS_LABEL,
} from "../lib/verdict";

type Pane = "claim" | "source" | "evidence";

// S4: three panes over a claim — the claim itself, the source-resolution
// chain ("why could this not be checked"), and the evidence.
//
// Tier 0.5 makes the evidence pane the point of the whole drawer: a verdict
// ships only with a verbatim-verified quote and a resolvable URL, so a reader
// can confirm or reject the finding in about ten seconds without leaving
// this panel.
export function ClaimDetailDrawer() {
  const { runId, claimId } = useParams();
  const navigate = useNavigate();

  const { data: claim, isLoading } = useQuery({
    queryKey: ["claim", runId, claimId],
    queryFn: () => api.getClaim(runId!, claimId!),
    enabled: !!runId && !!claimId,
  });

  const result = claim?.result;
  const hasEvidence = (result?.evidence ?? []).length > 0;
  // Open on whatever actually explains this row: the evidence when there is a
  // finding to check, the resolution chain when there is not.
  const defaultPane: Pane =
    result?.verdict === "not_checkable" ? "source" : hasEvidence ? "evidence" : "claim";
  const [pane, setPane] = useState<Pane | null>(null);
  const activePane = pane ?? defaultPane;

  // Path-relative so the drawer returns to whichever parent opened it —
  // the claims explorer or the paper view.
  function close() {
    navigate("..", { relative: "path" });
  }

  function openClaim(id: string) {
    navigate(`../${encodeURIComponent(id)}`, { relative: "path" });
  }

  const ragChunks =
    (result?.validation_metadata as { rag_chunks?: { text: string; score: number }[] } | undefined)
      ?.rag_chunks ?? [];

  return (
    <div className="fixed inset-0 z-20 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={close} />
      <div className="relative w-full max-w-xl bg-white h-full shadow-xl overflow-y-auto">
        <div className="sticky top-0 bg-white border-b px-4 py-3 flex items-center justify-between">
          <div className="text-sm font-medium text-gray-500">{claimId}</div>
          <button onClick={close} className="text-gray-400 hover:text-gray-700 text-lg leading-none">
            ×
          </button>
        </div>

        {isLoading && <div className="p-4 text-sm text-gray-500">Loading…</div>}

        {claim && (
          <div className="p-4 space-y-4">
            <div>
              <div className="text-xs text-gray-500 mb-1">
                {GROUP_LABEL[claim.group]} · {claim.claim_type}
                {claim.originally_uncited && " · originally uncited"}
              </div>
              <p className="text-gray-900">{claim.text}</p>
            </div>

            {(result?.flags ?? []).length > 0 && (
              <div className="flex flex-wrap gap-1">
                {result!.flags!.map((f) => (
                  <span
                    key={f}
                    className={`rounded-full border px-2 py-0.5 text-xs ${
                      f.startsWith("cited_source_")
                        ? "bg-amber-50 border-amber-300 text-amber-800"
                        : "bg-gray-50 border-gray-300 text-gray-600"
                    }`}
                  >
                    {FLAG_LABEL[f] ?? f}
                  </span>
                ))}
              </div>
            )}

            <div className="flex gap-1 border-b">
              {(["claim", "source", "evidence"] as Pane[]).map((p) => (
                <button
                  key={p}
                  onClick={() => setPane(p)}
                  className={`px-3 py-2 text-sm border-b-2 -mb-px ${
                    activePane === p
                      ? "border-indigo-600 text-indigo-700 font-medium"
                      : "border-transparent text-gray-500 hover:text-gray-800"
                  }`}
                >
                  {p === "claim" ? "Claim" : p === "source" ? "Source chain" : "Evidence"}
                  {p === "evidence" && hasEvidence && (
                    <span className="ml-1 text-xs text-gray-400">
                      ({result!.evidence!.length})
                    </span>
                  )}
                </button>
              ))}
            </div>

            {activePane === "claim" && result && (
              <div className="space-y-3">
                <div className="flex items-center gap-3 flex-wrap">
                  <VerdictBadge
                    verdict={result.verdict}
                    reason={result.not_checkable_reason}
                    legacy={result.legacy}
                  />
                  <ConfidenceGauge value={result.confidence} />
                </div>

                {result.verdict === "not_checkable" && result.not_checkable_reason && (
                  <div className="rounded-md bg-gray-50 border border-gray-200 p-3">
                    <div className="text-xs font-medium text-gray-500 mb-1">
                      Why this was not checked
                    </div>
                    <p className="text-sm text-gray-700">
                      {REASON_HINT[result.not_checkable_reason] ?? result.explanation}
                    </p>
                  </div>
                )}

                <div className="text-xs text-gray-500">
                  Method: {result.method}
                  {result.content_quality &&
                    ` · Source: ${CONTENT_QUALITY_LABEL[result.content_quality]}`}
                </div>
                <div>
                  <div className="text-xs font-medium text-gray-500 mb-1">Explanation</div>
                  <p className="text-sm text-gray-800 whitespace-pre-wrap">{result.explanation}</p>
                </div>
                {result.errors && (
                  <div>
                    <div className="text-xs font-medium text-red-500 mb-1">Error</div>
                    <p className="text-sm text-red-700 whitespace-pre-wrap">{result.errors}</p>
                  </div>
                )}
              </div>
            )}

            {activePane === "source" && (
              <div className="space-y-3">
                {claim.raw_citation_text && (
                  <div>
                    <div className="text-xs font-medium text-gray-500 mb-1">Citation</div>
                    <p className="text-sm text-gray-700">{claim.raw_citation_text}</p>
                  </div>
                )}

                {claim.batch?.reference_check && (
                  <div className="rounded-md border p-3">
                    <div className="flex items-center justify-between mb-1">
                      <div className="text-xs font-medium text-gray-500">
                        Does this reference exist?
                      </div>
                      <span
                        className={`rounded-full border px-2 py-0.5 text-xs ${
                          REFERENCE_STATUS_COLOR[claim.batch.reference_check.status]
                        }`}
                      >
                        {REFERENCE_STATUS_LABEL[claim.batch.reference_check.status]}
                      </span>
                    </div>
                    <p className="text-sm text-gray-700">
                      {claim.batch.reference_check.explanation}
                    </p>
                    {claim.batch.reference_check.matched_url && (
                      <a
                        className="text-sm text-indigo-700 hover:underline break-all"
                        href={claim.batch.reference_check.matched_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {claim.batch.reference_check.matched_url}
                      </a>
                    )}
                  </div>
                )}

                {claim.batch && (
                  <div className="text-xs text-gray-500">
                    Source obtained:{" "}
                    {claim.batch.download_successful ? "yes" : "no"}
                    {claim.batch.content_quality &&
                      ` · ${CONTENT_QUALITY_LABEL[claim.batch.content_quality]}`}
                    {claim.batch.download_successful && !claim.batch.judgeable && (
                      <span className="text-amber-700">
                        {" "}
                        · not usable as evidence
                      </span>
                    )}
                  </div>
                )}

                {claim.batch ? (
                  <ResolutionStepper attempts={claim.batch.resolution_attempts ?? []} />
                ) : (
                  <div className="text-sm text-gray-500">
                    This claim was not part of a citation batch (no citation attached).
                  </div>
                )}
              </div>
            )}

            {activePane === "evidence" && (
              <div className="space-y-4">
                {hasEvidence && (
                  <div className="space-y-2">
                    <div className="text-xs font-medium text-gray-500">
                      Quoted evidence
                      <span className="ml-1 font-normal text-gray-400">
                        — verified to appear in the retrieved source text
                      </span>
                    </div>
                    {result!.evidence!.map((e, i) => (
                      <blockquote
                        key={i}
                        className={`rounded border-l-4 p-3 bg-gray-50 ${
                          e.role === "contradicting"
                            ? "border-rose-500"
                            : e.role === "nearest_relevant"
                            ? "border-gray-400"
                            : "border-green-500"
                        }`}
                      >
                        <div className="text-xs text-gray-500 mb-1">
                          {e.role === "contradicting"
                            ? "Contradicts the claim"
                            : e.role === "nearest_relevant"
                            ? "Closest passage in the source"
                            : "Supports the claim"}
                          {e.retrieval_score != null && ` · similarity ${e.retrieval_score.toFixed(2)}`}
                          {e.locator && ` · ${e.locator}`}
                          {!e.verified_verbatim && (
                            <span className="text-amber-700"> · unverified</span>
                          )}
                        </div>
                        <p className="text-sm text-gray-800">“{e.quote}”</p>
                        {e.source_url && (
                          <a
                            className="text-xs text-indigo-700 hover:underline break-all"
                            href={e.source_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {e.source_url}
                          </a>
                        )}
                      </blockquote>
                    ))}
                  </div>
                )}

                {claim.generated_script_source && (
                  <div>
                    <div className="text-xs font-medium text-gray-500 mb-1">
                      Generated validation script
                    </div>
                    <pre className="text-xs bg-gray-950 text-gray-100 rounded-md p-3 overflow-x-auto">
                      {claim.generated_script_source}
                    </pre>
                  </div>
                )}

                {ragChunks.length > 0 && (
                  <div className="space-y-2">
                    <div className="text-xs font-medium text-gray-500">
                      Retrieved passages
                      <span className="ml-1 font-normal text-gray-400">
                        — everything the model was shown
                      </span>
                    </div>
                    {ragChunks.map((c, i) => (
                      <div key={i} className="rounded border p-2 bg-white">
                        <div className="text-xs text-gray-500 mb-1">
                          similarity {c.score.toFixed(2)}
                        </div>
                        <div className="text-sm text-gray-800">{c.text}</div>
                      </div>
                    ))}
                  </div>
                )}

                {!hasEvidence && !claim.generated_script_source && ragChunks.length === 0 && (
                  <div className="text-sm text-gray-500">
                    No evidence was retrieved for this claim
                    {result?.verdict === "not_checkable"
                      ? " — see the source chain for why."
                      : "."}
                  </div>
                )}
              </div>
            )}

            {(claim.sibling_claims ?? []).length > 0 && (
              <div className="pt-3 border-t">
                <div className="text-xs font-medium text-gray-500 mb-2">
                  Sibling claims (same citation)
                </div>
                <ul className="space-y-1">
                  {(claim.sibling_claims ?? []).map((s) => (
                    <li key={s.claim_id}>
                      <button
                        className="text-sm text-indigo-700 hover:underline text-left"
                        onClick={() => openClaim(s.claim_id)}
                      >
                        {s.text.slice(0, 80)}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
