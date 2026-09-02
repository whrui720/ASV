import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { VerdictBadge } from "./VerdictBadge";
import { ConfidenceGauge } from "./ConfidenceGauge";
import { ResolutionStepper } from "./ResolutionStepper";
import { GROUP_LABEL } from "../lib/verdict";

type Pane = "claim" | "source" | "evidence";

// S4: three panes over a claim — the claim itself, the source-resolution
// chain ("why did this fail" — default-open for unresolved_source), and the
// evidence (RAG chunks or the generated validation script).
export function ClaimDetailDrawer() {
  const { runId, claimId } = useParams();
  const navigate = useNavigate();

  const { data: claim, isLoading } = useQuery({
    queryKey: ["claim", runId, claimId],
    queryFn: () => api.getClaim(runId!, claimId!),
    enabled: !!runId && !!claimId,
  });

  const defaultPane: Pane = claim?.result?.verdict === "unresolved_source" ? "source" : "claim";
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
                {claim.is_original && " · original"}
                {claim.originally_uncited && " · originally uncited"}
              </div>
              <p className="text-gray-900">{claim.text}</p>
            </div>

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
                </button>
              ))}
            </div>

            {activePane === "claim" && claim.result && (
              <div className="space-y-3">
                <div className="flex items-center gap-3">
                  <VerdictBadge verdict={claim.result.verdict} />
                  <ConfidenceGauge value={claim.result.confidence} />
                </div>
                <div className="text-xs text-gray-500">Method: {claim.result.method}</div>
                <div>
                  <div className="text-xs font-medium text-gray-500 mb-1">Explanation</div>
                  <p className="text-sm text-gray-800 whitespace-pre-wrap">{claim.result.explanation}</p>
                </div>
                {claim.result.errors && (
                  <div>
                    <div className="text-xs font-medium text-red-500 mb-1">Error</div>
                    <p className="text-sm text-red-700 whitespace-pre-wrap">{claim.result.errors}</p>
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
                {claim.batch ? (
                  <ResolutionStepper attempts={claim.batch.resolution_attempts ?? []} />
                ) : (
                  <div className="text-sm text-gray-500">
                    This claim was not part of a citation batch (uncited).
                  </div>
                )}
              </div>
            )}

            {activePane === "evidence" && (
              <div className="space-y-3">
                {claim.generated_script_source ? (
                  <div>
                    <div className="text-xs font-medium text-gray-500 mb-1">Generated validation script</div>
                    <pre className="text-xs bg-gray-950 text-gray-100 rounded-md p-3 overflow-x-auto">
                      {claim.generated_script_source}
                    </pre>
                  </div>
                ) : (claim.result?.validation_metadata as { rag_chunks?: unknown[] } | undefined)
                    ?.rag_chunks?.length ? (
                  <div className="space-y-2">
                    {(
                      (claim.result!.validation_metadata as { rag_chunks: { text: string; score: number }[] })
                        .rag_chunks
                    ).map(
                      (c, i) => (
                        <div key={i} className="rounded border p-2 bg-gray-50">
                          <div className="text-xs text-gray-500 mb-1">similarity {c.score.toFixed(2)}</div>
                          <div className="text-sm text-gray-800">{c.text}</div>
                        </div>
                      )
                    )}
                  </div>
                ) : (
                  <div className="text-sm text-gray-500">No retrieved evidence recorded for this claim.</div>
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
