import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useRunEvents } from "../hooks/useRunEvents";
import { LogStream, EventTimeline } from "../components/LogStream";
import { AwaitingLoginBanner } from "../components/AwaitingLoginBanner";

// S7: streamed orchestration.log alongside the structured events.jsonl
// timeline, plus the awaiting-login banner (§8).
export function LiveConsole() {
  const { runId } = useParams();
  const [tab, setTab] = useState<"log" | "events">("log");

  const { data: run } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId!),
    enabled: !!runId,
    refetchInterval: 3000,
  });

  const { logs, events, awaitingLoginDomains, connected } = useRunEvents(runId ?? null, true);

  const domains = run?.awaiting_login_domains?.length ? run.awaiting_login_domains : awaitingLoginDomains;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Console</h1>
        <span className="text-xs text-gray-400">{connected ? "live" : "connecting…"}</span>
      </div>

      {domains && domains.length > 0 && <AwaitingLoginBanner runId={runId!} domains={domains} />}

      <div className="flex gap-1 border-b">
        {(["log", "events"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-2 text-sm border-b-2 -mb-px ${
              tab === t ? "border-indigo-600 text-indigo-700 font-medium" : "border-transparent text-gray-500"
            }`}
          >
            {t === "log" ? "Log tail" : "Event timeline"}
          </button>
        ))}
      </div>

      {tab === "log" ? <LogStream logs={logs} /> : <EventTimeline events={events} />}
    </div>
  );
}
