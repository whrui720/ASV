import type { Verdict } from "../api/client";
import { VERDICT_COLOR, VERDICT_LABEL } from "../lib/verdict";

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${VERDICT_COLOR[verdict]}`}
    >
      {VERDICT_LABEL[verdict]}
    </span>
  );
}
