import { Link } from "react-router-dom";
import type { RunDetail } from "../api/client";

// Tier 0.6 summary on the run overview.
//
// This is the only part of ASV that produces findings without needing full
// text, so it is also the only part that reliably has something to say on a
// paper whose sources are all paywalled.
export function ReferenceAuditCard({
  runId,
  audit,
}: {
  runId: string;
  audit: NonNullable<RunDetail["reference_audit"]>;
}) {
  const actionable = audit.not_found_in_indexes + audit.retracted + audit.concern_raised;

  return (
    <div className="rounded-lg border bg-white p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm font-medium text-gray-700">Bibliography audit</div>
        <Link
          to={`/runs/${runId}/references`}
          className="text-sm text-indigo-700 hover:underline"
        >
          View all {audit.total} references →
        </Link>
      </div>

      {actionable === 0 ? (
        <p className="text-sm text-gray-600">
          Every reference that could be checked was located in a bibliographic index, and
          none is retracted.
        </p>
      ) : (
        <ul className="text-sm text-gray-700 space-y-1">
          {audit.retracted > 0 && (
            <li className="text-rose-700">
              <strong>{audit.retracted}</strong> cited{" "}
              {audit.retracted === 1 ? "source is" : "sources are"} retracted
            </li>
          )}
          {audit.concern_raised > 0 && (
            <li className="text-amber-700">
              <strong>{audit.concern_raised}</strong> carry an expression of concern
            </li>
          )}
          {audit.not_found_in_indexes > 0 && (
            <li>
              <strong>{audit.not_found_in_indexes}</strong> not found in Crossref, OpenAlex,
              Europe PMC or PubMed — worth verifying by hand
            </li>
          )}
        </ul>
      )}

      <div className="mt-2 text-xs text-gray-500">
        {audit.verified} found · {audit.ambiguous} uncertain ·{" "}
        {audit.unindexed_by_design} not indexable (books, chapters, theses) ·{" "}
        {audit.unverified} could not be checked
      </div>
    </div>
  );
}
