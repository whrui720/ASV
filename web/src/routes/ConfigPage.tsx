import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

const KEY_NOTE: Record<string, string> = {
  GEMINI_API_KEY: "Required — primary LLM for every stage.",
  GOOGLE_FACT_CHECK_API_KEY: "Optional — missing means truth-table checks silently no-op.",
  UNPAYWALL_EMAIL: "Optional — required by Unpaywall's ToS for open-access lookups.",
  SEMANTIC_SCHOLAR_API_KEY: "Optional — improves Semantic Scholar rate limits.",
  KAGGLE_USERNAME: "Optional — needed for Kaggle dataset search.",
  KAGGLE_KEY: "Optional — needed for Kaggle dataset search.",
  INSTITUTIONAL_COOKIES: "Optional — enables institutional-cookie fallback for paywalled sources.",
};

// Config/health: which keys are present (never values) — surfaces the
// missing-key issues that otherwise fail silently deep in a run.
export function ConfigPage() {
  const { data: config, isLoading } = useQuery({ queryKey: ["config"], queryFn: api.getConfig });

  if (isLoading || !config) return <div className="text-sm text-gray-500">Loading…</div>;

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold">Config / health</h1>

      <div>
        <div className="text-sm font-medium text-gray-700 mb-2">API keys</div>
        <div className="space-y-1">
          {Object.entries(config.env_keys).map(([key, present]) => (
            <div key={key} className="flex items-start gap-2 text-sm">
              <span className={`mt-1 w-2 h-2 rounded-full flex-none ${present ? "bg-green-500" : "bg-gray-300"}`} />
              <div>
                <span className="font-mono">{key}</span>
                <span className={present ? "text-green-700 ml-2" : "text-gray-400 ml-2"}>
                  {present ? "present" : "missing"}
                </span>
                <div className="text-xs text-gray-500">{KEY_NOTE[key]}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div className="text-sm font-medium text-gray-700 mb-2">Thresholds</div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {Object.entries(config.thresholds).map(([key, value]) => (
            <div key={key} className="rounded border bg-white p-2">
              <div className="text-xs text-gray-500 font-mono">{key}</div>
              <div className="text-sm font-medium">{String(value)}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
