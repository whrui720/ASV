// Tier 0.2: confidence is null for every abstention, by construction — a
// number attached to "I could not check this" is precisely the unearned
// confidence Tier 0 removed. Render the absence, never a 0% bar, which would
// read as "checked, and scored zero".
export function ConfidenceGauge({ value }: { value?: number | null }) {
  if (value === null || value === undefined) {
    return (
      <span
        className="text-xs text-gray-400 w-32 inline-block"
        title="No confidence: ASV did not judge this claim."
      >
        —
      </span>
    );
  }

  const pct = Math.round(value * 100);
  const color = value >= 0.8 ? "bg-green-500" : value >= 0.5 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2 w-32">
      <div className="h-2 flex-1 rounded-full bg-gray-200 overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-gray-600 w-9 text-right">{pct}%</span>
    </div>
  );
}
