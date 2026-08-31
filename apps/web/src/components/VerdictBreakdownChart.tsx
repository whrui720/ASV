import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { RunDetail } from "../api/client";
import { GROUP_LABEL, VERDICT_DOT } from "../lib/verdict";

// The chart that makes the source-acquisition problem visible immediately
// (docs/FRONTEND_PLAN.md §6, S2): a stacked passed/failed/unresolved_source
// bar per group. `unresolved_source` (amber) dominating a bar means the
// claim was never actually judged — it's a source-acquisition problem, not
// a verification failure.
export function VerdictBreakdownChart({ data }: { data: RunDetail["verdict_breakdown"] }) {
  const chartData = (data ?? []).map((d) => ({
    group: GROUP_LABEL[d.group] ?? d.group,
    passed: d.passed,
    failed: d.failed,
    unresolved_source: d.unresolved_source,
    skipped: d.skipped,
  }));

  return (
    <div className="rounded-lg border bg-white p-4">
      <div className="text-sm font-medium text-gray-700 mb-2">Verdict breakdown</div>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={chartData} layout="vertical" margin={{ left: 24 }}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" allowDecimals={false} />
          <YAxis type="category" dataKey="group" width={140} tick={{ fontSize: 12 }} />
          <Tooltip />
          <Legend />
          <Bar dataKey="passed" stackId="v" fill={VERDICT_DOT.passed} name="Passed" />
          <Bar dataKey="failed" stackId="v" fill={VERDICT_DOT.failed} name="Failed" />
          <Bar
            dataKey="unresolved_source"
            stackId="v"
            fill={VERDICT_DOT.unresolved_source}
            name="Unresolved source"
          />
          <Bar dataKey="skipped" stackId="v" fill={VERDICT_DOT.skipped} name="Skipped" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
