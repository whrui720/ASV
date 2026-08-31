import type { RunDetail } from "../api/client";
import { GROUP_LABEL } from "../lib/verdict";
import { pct, seconds } from "../lib/format";

const STEP_ORDER = ["qualitative_uncited", "quantitative_uncited", "qualitative_cited", "quantitative_cited"];

export function StepCards({ steps }: { steps: RunDetail["steps"] }) {
  const stepMap = steps ?? {};
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
      {STEP_ORDER.map((key) => {
        const s = stepMap[key];
        if (!s) return null;
        const groupKey = key === "qualitative_uncited" ? "qual_uncited"
          : key === "quantitative_uncited" ? "quant_uncited"
          : key === "qualitative_cited" ? "qual_cited" : "quant_cited";
        const passRate = s.count ? s.passed / s.count : null;
        return (
          <div key={key} className="rounded-lg border bg-white p-4">
            <div className="text-xs font-medium text-gray-500 uppercase tracking-wide">
              {GROUP_LABEL[groupKey]}
            </div>
            <div className="mt-1 text-2xl font-semibold">{s.count}</div>
            <div className="mt-1 text-sm text-gray-600">
              {s.passed} passed · {s.failed} failed
            </div>
            <div className="mt-1 text-xs text-gray-400">
              {pct(passRate)} pass rate · {seconds(s.elapsed_seconds)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
