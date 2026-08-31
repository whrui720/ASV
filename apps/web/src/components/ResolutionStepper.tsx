import type { components } from "../api/types";

type ResolutionAttempt = components["schemas"]["ResolutionAttempt"];

const SOURCE_LABEL: Record<string, string> = {
  direct: "Direct URL",
  open_access: "Open access (Unpaywall/S2/CrossRef)",
  found_dataset: "Found dataset",
  institutional_cookies: "Institutional cookies",
  browser: "Browser (authenticated)",
};

// The "why did this fail" view (S4 §6): the ordered cascade of every URL the
// pipeline tried for a citation, each tagged with the resolution phase and
// pass/fail. Should be the default-open pane for unresolved_source claims.
export function ResolutionStepper({ attempts }: { attempts: ResolutionAttempt[] }) {
  if (attempts.length === 0) {
    return <div className="text-sm text-gray-500">No resolution attempts were recorded for this citation.</div>;
  }
  return (
    <ol className="space-y-2">
      {attempts.map((a, i) => (
        <li key={i} className="flex items-start gap-3">
          <span
            className={`mt-0.5 flex-none w-2.5 h-2.5 rounded-full ${
              a.downloaded ? "bg-green-500" : "bg-red-400"
            }`}
          />
          <div className="min-w-0 flex-1">
            <div className="text-xs text-gray-500">{SOURCE_LABEL[a.source] ?? a.source}</div>
            <div className="text-sm break-all text-gray-800">{a.url}</div>
            {a.error && <div className="text-xs text-red-600 mt-0.5">{a.error}</div>}
          </div>
        </li>
      ))}
    </ol>
  );
}
