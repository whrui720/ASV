import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { RunDetail } from "../api/client";
import { GROUP_LABEL, VERDICT_DOT, VERDICT_LABEL } from "../lib/verdict";

// The chart that makes the real shape of a run visible at a glance
// (docs/FRONTEND_PLAN.md §6, S2). Grey — "not checkable" — dominating a bar
// means those claims were never judged. That is usually a source-acquisition
// problem (Tier 1), not a verification result, and the previous version of
// this chart could not say so: it had one amber "unresolved_source" bucket and
// folded every unsourced plausibility pass into green "Passed".
export function VerdictBreakdownChart({ data }: { data: RunDetail["verdict_breakdown"] }) {
  const chartData = (data ?? []).map((d) => ({
    group: GROUP_LABEL[d.group] ?? d.group,
    substantiated: d.substantiated,
    partially_substantiated: d.partially_substantiated,
    not_substantiated: d.not_substantiated,
    contradicted: d.contradicted,
    not_checkable: d.not_checkable,
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
          <Bar dataKey="contradicted" stackId="v" fill={VERDICT_DOT.contradicted} name={VERDICT_LABEL.contradicted} />
          <Bar dataKey="not_substantiated" stackId="v" fill={VERDICT_DOT.not_substantiated} name={VERDICT_LABEL.not_substantiated} />
          <Bar dataKey="partially_substantiated" stackId="v" fill={VERDICT_DOT.partially_substantiated} name={VERDICT_LABEL.partially_substantiated} />
          <Bar dataKey="substantiated" stackId="v" fill={VERDICT_DOT.substantiated} name={VERDICT_LABEL.substantiated} />
          <Bar dataKey="not_checkable" stackId="v" fill={VERDICT_DOT.not_checkable} name={VERDICT_LABEL.not_checkable} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
