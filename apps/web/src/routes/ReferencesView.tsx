import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { REFERENCE_STATUS_COLOR, REFERENCE_STATUS_LABEL } from "../lib/verdict";

// S9 — the Tier 0.6 bibliography audit.
//
// This is the one screen in ASV that produces findings without needing full
// text, and it covers *every* reference in the paper, not only the ones with
// claims attached. Two things a reader acts on immediately: a reference no
// index carries, and a reference that has been retracted.
//
// The wording throughout is deliberately about what ASV observed, never about
// what the author did. "Not found in indexes" is a prompt to check the
// reference; it is not an allegation of fabrication, and books, chapters and
// theses are routed to "Not indexable" precisely so they never read as one.
export function ReferencesView() {
  const { runId } = useParams();
  const [filter, setFilter] = useState<string>("");

  const { data: refs, isLoading } = useQuery({
    queryKey: ["references", runId],
    queryFn: () => api.listReferences(runId!),
    enabled: !!runId,
  });

  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const r of refs ?? []) out[r.status] = (out[r.status] ?? 0) + 1;
    return out;
  }, [refs]);

  const retracted = (refs ?? []).filter((r) => r.retraction_status === "retracted");
  const concerns = (refs ?? []).filter((r) => r.retraction_status === "concern_raised");
  const shown = (refs ?? []).filter((r) => !filter || r.status === filter);

  if (isLoading) return <div className="text-sm text-gray-500">Loading…</div>;

  if (!refs || refs.length === 0) {
    return (
      <div className="rounded-lg border bg-white p-6 text-sm text-gray-600">
        No bibliography audit for this run. Runs created before the reference check
        was added do not have one; re-run the paper to produce it.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold">Bibliography audit</h1>
        <p className="text-sm text-gray-500">
          {refs.length} references checked against Crossref, OpenAlex, Europe PMC and
          PubMed. No full text required.
        </p>
      </div>

      {(retracted.length > 0 || concerns.length > 0) && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {retracted.length > 0 && (
            <div>
              <strong>{retracted.length}</strong> cited{" "}
              {retracted.length === 1 ? "source has" : "sources have"} been retracted.
            </div>
          )}
          {concerns.length > 0 && (
            <div>
              <strong>{concerns.length}</strong> carry an expression of concern.
            </div>
          )}
          <div className="mt-1 text-amber-800">
            A retraction does not by itself mean the citing sentence is wrong — but it is
            usually worth revisiting.
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => setFilter("")}
          className={`rounded-full border px-3 py-1 text-xs ${
            filter === "" ? "bg-gray-900 text-white border-gray-900" : "bg-white text-gray-600"
          }`}
        >
          All ({refs.length})
        </button>
        {Object.entries(counts).map(([status, n]) => (
          <button
            key={status}
            onClick={() => setFilter(status === filter ? "" : status)}
            className={`rounded-full border px-3 py-1 text-xs ${
              filter === status
                ? "bg-gray-900 text-white border-gray-900"
                : REFERENCE_STATUS_COLOR[status] ?? "bg-white text-gray-600"
            }`}
          >
            {REFERENCE_STATUS_LABEL[status] ?? status} ({n})
          </button>
        ))}
      </div>

      <div className="overflow-x-auto rounded-lg border bg-white">
        <table className="min-w-full text-left">
          <thead className="bg-gray-50 border-b text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th className="px-3 py-2 font-medium">#</th>
              <th className="px-3 py-2 font-medium">Reference</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Claims</th>
              <th className="px-3 py-2 font-medium">Match</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.citation_id} className="border-b last:border-0 align-top">
                <td className="px-3 py-2 text-xs text-gray-500">{r.citation_id}</td>
                <td className="px-3 py-2 max-w-xl">
                  <div className="text-sm text-gray-800">{r.raw_citation_text}</div>
                  <div className="text-xs text-gray-500 mt-1">{r.explanation}</div>
                  {r.near_miss && (
                    <div className="text-xs text-gray-500 mt-1">
                      Closest match ({String(r.near_miss.index)}, score{" "}
                      {Number(r.near_miss.score).toFixed(2)}): {String(r.near_miss.title)}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2 whitespace-nowrap">
                  <span
                    className={`inline-flex rounded-full border px-2 py-0.5 text-xs ${
                      REFERENCE_STATUS_COLOR[r.status]
                    }`}
                  >
                    {REFERENCE_STATUS_LABEL[r.status] ?? r.status}
                  </span>
                  {r.retraction_status === "retracted" && (
                    <div className="mt-1 text-xs font-medium text-rose-700">RETRACTED</div>
                  )}
                  {r.retraction_status === "concern_raised" && (
                    <div className="mt-1 text-xs font-medium text-amber-700">
                      Expression of concern
                    </div>
                  )}
                </td>
                <td className="px-3 py-2 text-xs">
                  {r.num_claims > 0 ? (
                    <Link
                      className="text-indigo-700 hover:underline"
                      to={`/runs/${runId}/claims?citation_id=${encodeURIComponent(r.citation_id)}`}
                    >
                      {r.num_claims}
                    </Link>
                  ) : (
                    <span className="text-gray-400" title="No extracted claim cites this reference">
                      0
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-xs">
                  {r.matched_url ? (
                    <a
                      className="text-indigo-700 hover:underline break-all"
                      href={r.matched_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {r.matched_doi ?? r.matched_url}
                    </a>
                  ) : (
                    <span className="text-gray-400">—</span>
                  )}
                  <div className="text-gray-400 mt-1">
                    checked: {(r.indexes_responded ?? []).join(", ") || "none responded"}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
