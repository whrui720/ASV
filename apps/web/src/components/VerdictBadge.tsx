import type { NotCheckableReason, Verdict } from "../api/client";
import {
  REASON_LABEL,
  VERDICT_COLOR,
  VERDICT_DESCRIPTION,
  VERDICT_LABEL,
} from "../lib/verdict";

// Tier 0.2. An abstention renders as "Not checkable — <reason>", because the
// reason is the actionable half: "abstract only" and "reference not found"
// need completely different responses from a reader, and the pre-Tier-0 UI
// showed both as a red "Failed" badge indistinguishable from a real finding.
export function VerdictBadge({
  verdict,
  reason,
  legacy,
}: {
  verdict: Verdict;
  reason?: NotCheckableReason | null;
  legacy?: boolean;
}) {
  const label =
    verdict === "not_checkable" && reason
      ? `${VERDICT_LABEL[verdict]} — ${REASON_LABEL[reason] ?? reason}`
      : VERDICT_LABEL[verdict];

  return (
    <span className="inline-flex items-center gap-1">
      <span
        title={VERDICT_DESCRIPTION[verdict]}
        className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${VERDICT_COLOR[verdict]}`}
      >
        {label}
      </span>
      {legacy && (
        <span
          title="This run predates the Tier 0 verdict layer. Its verdicts were reconstructed on read; passes from the old plausibility path are shown as abstentions because that is what they were."
          className="inline-flex items-center rounded-full border border-dashed border-gray-300 px-1.5 py-0.5 text-[10px] text-gray-500"
        >
          legacy
        </span>
      )}
    </span>
  );
}
