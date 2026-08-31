import { useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

// S6: one row per SourceManifestEntry across both manifests — the place to
// fix a bad citation (supply a URL, or just retry after a paywall login).
export function SourcesView() {
  const { runId } = useParams();
  const queryClient = useQueryClient();
  const [failedOnly, setFailedOnly] = useState(false);
  const [overrideDrafts, setOverrideDrafts] = useState<Record<string, string>>({});

  const { data: sources, isLoading } = useQuery({
    queryKey: ["sources", runId],
    queryFn: () => api.listSources(runId!),
    enabled: !!runId,
  });

  const retryMutation = useMutation({
    mutationFn: ({ citationId, url }: { citationId: string; url?: string }) =>
      api.retrySource(runId!, citationId, url),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sources", runId] });
      queryClient.invalidateQueries({ queryKey: ["claims", runId] });
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
    },
  });

  const rows = (sources ?? []).filter((s) => !failedOnly || !s.batch_download_successful);

  if (isLoading) return <div className="text-sm text-gray-500">Loading…</div>;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Sources</h1>
        <label className="flex items-center gap-2 text-sm text-gray-600">
          <input type="checkbox" checked={failedOnly} onChange={(e) => setFailedOnly(e.target.checked)} />
          Failures only
        </label>
      </div>

      <div className="space-y-2">
        {rows.map((s) => (
          <div key={`${s.kind}-${s.citation_id}`} className="rounded-lg border bg-white p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-xs text-gray-500">
                  [{s.kind}] citation {s.citation_id} · {s.batch_num_claims} claim(s)
                </div>
                <div className="text-sm text-gray-800 truncate">
                  {s.raw_citation_text ?? s.citation_text ?? "—"}
                </div>
                {s.winning_url && (
                  <a
                    href={s.winning_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-indigo-600 hover:underline break-all"
                  >
                    {s.winning_url}
                  </a>
                )}
              </div>
              <span
                className={`flex-none rounded-full px-2 py-0.5 text-xs font-medium ${
                  s.batch_download_successful
                    ? "bg-green-100 text-green-800"
                    : "bg-red-100 text-red-800"
                }`}
              >
                {s.batch_download_successful ? "downloaded" : "failed"}
              </span>
            </div>

            {!s.batch_download_successful && (
              <div className="mt-2 flex items-center gap-2">
                <input
                  placeholder="Override URL (optional)"
                  value={overrideDrafts[s.citation_id] ?? ""}
                  onChange={(e) =>
                    setOverrideDrafts((d) => ({ ...d, [s.citation_id]: e.target.value }))
                  }
                  className="flex-1 rounded border-gray-300 text-xs"
                />
                <button
                  onClick={() =>
                    retryMutation.mutate({
                      citationId: s.citation_id,
                      url: overrideDrafts[s.citation_id] || undefined,
                    })
                  }
                  disabled={retryMutation.isPending}
                  className="rounded-md bg-amber-600 px-3 py-1 text-xs font-medium text-white hover:bg-amber-700 disabled:opacity-50"
                >
                  Retry
                </button>
              </div>
            )}
          </div>
        ))}
        {rows.length === 0 && <div className="text-sm text-gray-400">No sources to show.</div>}
      </div>
    </div>
  );
}
