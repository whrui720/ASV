import type { RunDetail } from "../api/client";
import { GROUP_LABEL, VERDICT_LABEL } from "../lib/verdict";
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
        // Tier 0.2: the denominator is "claims we could check", not "claims".
        // A pass rate over everything counted every unchecked claim as a
        // failure and every unsourced plausibility pass as a success.
        const checkable = s.checkable ?? 0;
        const verdicts = s.verdicts ?? {};
        const substantiated = verdicts.substantiated ?? s.passed ?? 0;
        const rate = checkable ? substantiated / checkable : null;
        return (
          <div key={key} className="rounded-lg border bg-white p-4">
            <div className="text-xs font-medium text-gray-500 uppercase tracking-wide">
              {GROUP_LABEL[groupKey]}
            </div>
            <div className="mt-1 text-2xl font-semibold">{s.count}</div>
            <div className="mt-1 text-sm text-gray-600">
              {checkable} checkable · {s.count - checkable} not checkable
            </div>
            <div className="mt-1 text-xs text-gray-400">
              {checkable > 0
                ? `${substantiated} ${VERDICT_LABEL.substantiated.toLowerCase()} (${pct(rate)} of checkable)`
                : "nothing could be checked"}{" "}
              · {seconds(s.elapsed_seconds)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
