import type { components } from "../api/types";

type ResolutionAttempt = components["schemas"]["ResolutionAttempt"];

// Attempts are now tagged with the *resolver* that produced the URL rather than
// a single "open_access" bucket, so this view answers "which service is earning
// its place" — the question SOURCE_ACQUISITION.md could only answer by hand.
// Unknown keys fall through to the raw label, so a new resolver is never hidden.
const SOURCE_LABEL: Record<string, string> = {
  direct: "Direct URL",
  open_access: "Open access (Unpaywall/S2/CrossRef)",
  found_dataset: "Found dataset",
  institutional_cookies: "Institutional cookies",
  browser: "Browser (authenticated)",
  ezproxy: "EZproxy (institutional)",
  // Full-text locators, best first.
  europepmc_fulltext: "Europe PMC full text (XML)",
  pmc_efetch: "PubMed Central full text (XML)",
  europepmc: "Europe PMC",
  openalex: "OpenAlex",
  unpaywall: "Unpaywall",
  semantic_scholar: "Semantic Scholar",
  crossref: "CrossRef",
  core: "CORE (repositories)",
  arxiv: "arXiv",
  wiley_tdm: "Wiley TDM",
  elsevier_tdm: "Elsevier TDM",
  springer_oa: "Springer Nature OA",
  doi_landing: "DOI landing page (last resort)",
  google_scholar: "Google Scholar (browser)",
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
