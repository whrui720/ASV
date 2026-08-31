import { useMemo, useState } from "react";
import { Outlet, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { ClaimsTable } from "../components/ClaimsTable";
import { GROUP_LABEL } from "../lib/verdict";

const PAGE_SIZE = 50;

export function ClaimsExplorer() {
  const { runId } = useParams();
  const [params, setParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(1);

  const filters = {
    group: params.get("group") ?? undefined,
    verdict: params.get("verdict") ?? undefined,
    claim_type: params.get("claim_type") ?? undefined,
    method: params.get("method") ?? undefined,
    q: params.get("q") ?? undefined,
  };

  const { data, isLoading } = useQuery({
    queryKey: ["claims", runId, filters, page],
    queryFn: () =>
      api.listClaims(runId!, { ...filters, page, page_size: PAGE_SIZE }),
    enabled: !!runId,
  });

  const retryMutation = useMutation({
    mutationFn: (citationId: string) => api.retrySource(runId!, citationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["claims", runId] });
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
    },
  });

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
    setPage(1);
  }

  const rows = data?.claims ?? [];
  const facets = data?.facets ?? {};

  const selectedUnresolvedCitations = useMemo(() => {
    const ids = new Set<string>();
    rows.forEach((r) => {
      if (selected.has(r.claim_id) && r.result?.verdict === "unresolved_source" && r.batch) {
        ids.add(r.batch.citation_id);
      }
    });
    return ids;
  }, [rows, selected]);

  function toggleSelect(claimId: string) {
    setSelected((s) => {
      const next = new Set(s);
      next.has(claimId) ? next.delete(claimId) : next.add(claimId);
      return next;
    });
  }

  function toggleSelectAll() {
    setSelected((s) => {
      const allSelected = rows.every((r) => s.has(r.claim_id));
      if (allSelected) return new Set();
      return new Set(rows.map((r) => r.claim_id));
    });
  }

  function exportJson() {
    const blob = new Blob([JSON.stringify(rows, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${runId}_claims.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="text-lg font-semibold">Claims</h1>
        <div className="flex items-center gap-2">
          {selectedUnresolvedCitations.size > 0 && (
            <button
              onClick={() => selectedUnresolvedCitations.forEach((c) => retryMutation.mutate(c))}
              className="rounded-md bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-700"
            >
              Retry {selectedUnresolvedCitations.size} citation(s)
            </button>
          )}
          <button
            onClick={exportJson}
            className="rounded-md border px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Export JSON
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 text-sm">
        <FilterSelect
          label="Group"
          value={filters.group ?? ""}
          onChange={(v) => setFilter("group", v)}
          options={Object.entries(facets.group ?? {}).map(([k, n]) => [k, `${GROUP_LABEL[k] ?? k} (${n})`])}
        />
        <FilterSelect
          label="Verdict"
          value={filters.verdict ?? ""}
          onChange={(v) => setFilter("verdict", v)}
          options={Object.entries(facets.verdict ?? {}).map(([k, n]) => [k, `${k} (${n})`])}
        />
        <FilterSelect
          label="Type"
          value={filters.claim_type ?? ""}
          onChange={(v) => setFilter("claim_type", v)}
          options={Object.entries(facets.claim_type ?? {}).map(([k, n]) => [k, `${k} (${n})`])}
        />
        <FilterSelect
          label="Method"
          value={filters.method ?? ""}
          onChange={(v) => setFilter("method", v)}
          options={Object.entries(facets.method ?? {}).map(([k, n]) => [k, `${k} (${n})`])}
        />
        <input
          placeholder="Search claim text or citation…"
          defaultValue={filters.q}
          onChange={(e) => setFilter("q", e.target.value)}
          className="rounded border-gray-300 text-sm flex-1 min-w-[200px]"
        />
      </div>

      {isLoading ? (
        <div className="text-sm text-gray-500">Loading…</div>
      ) : (
        <>
          <ClaimsTable
            rows={rows}
            selected={selected}
            onToggleSelect={toggleSelect}
            onToggleSelectAll={toggleSelectAll}
          />
          <div className="flex items-center justify-between text-sm text-gray-500">
            <span>
              {data?.total ?? 0} claims · page {page}
            </span>
            <div className="flex gap-2">
              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
                className="px-2 py-1 rounded border disabled:opacity-40"
              >
                Prev
              </button>
              <button
                disabled={!data || page * PAGE_SIZE >= data.total}
                onClick={() => setPage((p) => p + 1)}
                className="px-2 py-1 rounded border disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}

      <Outlet />
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded border-gray-300 text-sm"
    >
      <option value="">{label}: all</option>
      {options.map(([k, l]) => (
        <option key={k} value={k}>
          {l}
        </option>
      ))}
    </select>
  );
}
