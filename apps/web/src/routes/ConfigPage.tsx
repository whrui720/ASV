import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { CredentialsForm } from "../components/CredentialsForm";

// Config / health. Two halves: the credentials the user can actually change
// (CredentialsForm — the acquisition fix, see SOURCE_ACQUISITION.md §3) and the
// thresholds currently in effect, which are read-only because changing one
// changes what past runs mean.
export function ConfigPage() {
  const { data: config, isLoading } = useQuery({ queryKey: ["config"], queryFn: api.getConfig });

  return (
    <div className="space-y-8">
      <h1 className="text-lg font-semibold">Config / health</h1>

      <CredentialsForm />

      <div>
        <div className="mb-1 text-sm font-medium text-gray-700">Thresholds</div>
        <p className="mb-2 text-xs text-gray-500">
          Read-only. These decide what counts as evidence, so they are set in code and
          versioned with it — see <span className="font-mono">sourcefinder/config.py</span>{" "}
          and <span className="font-mono">validator/config.py</span>.
        </p>
        {isLoading || !config ? (
          <div className="text-sm text-gray-500">Loading…</div>
        ) : (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {Object.entries(config.thresholds).map(([key, value]) => (
              <div key={key} className="rounded border bg-white p-2">
                <div className="font-mono text-xs text-gray-500">{key}</div>
                <div className="text-sm font-medium">{String(value)}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
