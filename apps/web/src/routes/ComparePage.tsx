import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { VerdictBadge } from "../components/VerdictBadge";

// S8: two runs of the same paper side by side, per-claim verdict deltas —
// answers "did the change to X actually help?" without diffing JSON by hand.
export function ComparePage() {
  const { data: runs } = useQuery({ queryKey: ["runs"], queryFn: api.listRuns });
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [onlyChanged, setOnlyChanged] = useState(true);

  const { data: result, isLoading } = useQuery({
    queryKey: ["compare", a, b],
    queryFn: () => api.compareRuns(a, b),
    enabled: !!a && !!b && a !== b,
  });

  const rows = (result?.rows ?? []).filter((r) => !onlyChanged || r.changed);

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Compare runs</h1>
      <div className="flex items-center gap-3">
        <RunSelect label="Run A" value={a} onChange={setA} runs={runs} />
        <RunSelect label="Run B" value={b} onChange={setB} runs={runs} />
        <label className="flex items-center gap-2 text-sm text-gray-600">
          <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} />
          Changed only
        </label>
      </div>

      {isLoading && <div className="text-sm text-gray-500">Comparing…</div>}

      {result && (
        <div className="overflow-x-auto rounded-lg border bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-gray-50 border-b text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-3 py-2">Claim</th>
                <th className="px-3 py-2">Run A</th>
                <th className="px-3 py-2">Run B</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.claim_id} className="border-b last:border-0">
                  <td className="px-3 py-2 text-gray-900">{r.text.slice(0, 100)}</td>
                  <td className="px-3 py-2">
                    {r.a_verdict ? <VerdictBadge verdict={r.a_verdict} /> : "—"}
                  </td>
                  <td className="px-3 py-2">
                    {r.b_verdict ? <VerdictBadge verdict={r.b_verdict} /> : "—"}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={3} className="px-3 py-8 text-center text-gray-400">
                    No differences.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function RunSelect({
  label,
  value,
  onChange,
  runs,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  runs: { run_id: string; pdf_stem: string; timestamp: string }[] | undefined;
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className="rounded border-gray-300 text-sm">
      <option value="">{label}…</option>
      {runs?.map((r) => (
        <option key={r.run_id} value={r.run_id}>
          {r.pdf_stem} · {r.timestamp}
        </option>
      ))}
    </select>
  );
}
