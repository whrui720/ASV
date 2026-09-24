import type { RunDetail } from "../api/client";
import { REASON_LABEL, VERDICT_DOT, VERDICT_LABEL, VERDICT_ORDER } from "../lib/verdict";
import type { NotCheckableReason, Verdict } from "../api/client";

// The headline the run page should lead with after Tier 0.
//
// The number that matters is not a pass rate — it is "of N claims, how many
// could ASV check at all". VALUE_PROPOSITION.md §8 makes checkable rate the
// first credibility metric, and §0 of the Tier 0 plan is blunt that this
// number starts low and only source acquisition (Tier 1) moves it. Showing it
// honestly here is the whole point of the exercise.
export function CheckableSummary({ run }: { run: RunDetail }) {
  const totals: Record<Verdict, number> = {
    substantiated: 0,
    partially_substantiated: 0,
    not_substantiated: 0,
    contradicted: 0,
    not_checkable: 0,
  };
  for (const g of run.verdict_breakdown ?? []) {
    totals.substantiated += g.substantiated;
    totals.partially_substantiated += g.partially_substantiated;
    totals.not_substantiated += g.not_substantiated;
    totals.contradicted += g.contradicted;
    totals.not_checkable += g.not_checkable;
  }
  const total = VERDICT_ORDER.reduce((a, v) => a + totals[v], 0);
  const checkable = total - totals.not_checkable;
  if (total === 0) return null;

  const reasons = Object.entries(run.not_checkable_reasons ?? {}).slice(0, 4);

  return (
    <div className="rounded-lg border bg-white p-4 space-y-3">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <div>
          <div className="text-2xl font-semibold text-gray-900">
            {checkable} of {total}
          </div>
          <div className="text-sm text-gray-500">
            claims ASV was able to check against a source
          </div>
        </div>
        {run.schema_version < 2 && (
          <span
            title="This run predates the Tier 0 verdict layer. Its verdicts were reconstructed on read."
            className="rounded-full border border-dashed border-gray-300 px-2 py-0.5 text-xs text-gray-500"
          >
            legacy run
          </span>
        )}
      </div>

      <div className="flex h-3 w-full overflow-hidden rounded-full bg-gray-100">
        {VERDICT_ORDER.map((v) =>
          totals[v] > 0 ? (
            <div
              key={v}
              title={`${VERDICT_LABEL[v]}: ${totals[v]}`}
              style={{ width: `${(totals[v] / total) * 100}%`, background: VERDICT_DOT[v] }}
            />
          ) : null
        )}
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-600">
        {VERDICT_ORDER.filter((v) => totals[v] > 0).map((v) => (
          <span key={v} className="inline-flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: VERDICT_DOT[v] }}
            />
            {VERDICT_LABEL[v]} {totals[v]}
          </span>
        ))}
      </div>

      {reasons.length > 0 && (
        <div className="pt-2 border-t text-xs text-gray-500">
          Most common reasons ASV could not check a claim:{" "}
          {reasons
            .map(([k, n]) => `${REASON_LABEL[k as NotCheckableReason] ?? k} (${n})`)
            .join(" · ")}
        </div>
      )}
    </div>
  );
}
