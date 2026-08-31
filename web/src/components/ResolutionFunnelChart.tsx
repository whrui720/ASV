import type { RunDetail } from "../api/client";

const STAGE_LABEL: Record<string, string> = {
  citations_total: "Citations",
  url_found: "URL found",
  downloaded: "Downloaded",
  text_extracted: "Text extracted",
  validated: "Validated",
};

// Source-resolution funnel (§6, S2): citations total -> URL found ->
// downloaded -> text extracted -> validated. Shows exactly where the
// resolution cascade leaks.
export function ResolutionFunnelChart({ data }: { data: RunDetail["resolution_funnel"] }) {
  const stages = data ?? [];
  const total = stages[0]?.count || 1;
  return (
    <div className="rounded-lg border bg-white p-4">
      <div className="text-sm font-medium text-gray-700 mb-3">Source-resolution funnel</div>
      <div className="space-y-2">
        {stages.map((stage) => {
          const w = Math.max(2, Math.round((stage.count / total) * 100));
          return (
            <div key={stage.stage} className="flex items-center gap-3">
              <div className="w-28 text-xs text-gray-600">{STAGE_LABEL[stage.stage] ?? stage.stage}</div>
              <div className="flex-1 h-5 bg-gray-100 rounded overflow-hidden">
                <div className="h-full bg-indigo-500" style={{ width: `${w}%` }} />
              </div>
              <div className="w-10 text-xs text-right tabular-nums text-gray-700">{stage.count}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
