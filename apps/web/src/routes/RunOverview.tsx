import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { StepCards } from "../components/StepCards";
import { VerdictBreakdownChart } from "../components/VerdictBreakdownChart";
import { ResolutionFunnelChart } from "../components/ResolutionFunnelChart";
import { AwaitingLoginBanner } from "../components/AwaitingLoginBanner";
import { ReferenceAuditCard } from "../components/ReferenceAuditCard";
import { CheckableSummary } from "../components/CheckableSummary";
import { useRunEvents } from "../hooks/useRunEvents";
import { seconds, timestampLabel, usd } from "../lib/format";

const LIVE_STATUSES = new Set(["queued", "running", "awaiting_login"]);

export function RunOverview() {
  const { runId } = useParams();

  const { data: run, isLoading } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId!),
    enabled: !!runId,
    refetchInterval: (q) => (LIVE_STATUSES.has(q.state.data?.status ?? "") ? 3000 : false),
  });

  const isLive = !!run && LIVE_STATUSES.has(run.status);
  const liveEvents = useRunEvents(runId ?? null, isLive);

  const awaitingDomains = run?.awaiting_login_domains?.length
    ? run.awaiting_login_domains
    : liveEvents.awaitingLoginDomains;

  if (isLoading || !run) return <div className="text-sm text-gray-500">Loading…</div>;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-lg font-semibold">{run.pdf_stem}</h1>
          <p className="text-sm text-gray-500">
            {timestampLabel(run.timestamp)} · {run.status}
            {run.total_elapsed_seconds !== null && <> · {seconds(run.total_elapsed_seconds)}</>}
            {run.cost && <> · {usd(run.cost.total_cost)}</>}
          </p>
        </div>
      </div>

      {awaitingDomains && awaitingDomains.length > 0 && (
        <AwaitingLoginBanner runId={runId!} domains={awaitingDomains} />
      )}

      {isLive && (
        <div className="rounded-lg border bg-indigo-50 border-indigo-200 px-4 py-2 text-sm text-indigo-800">
          This run is in progress — this page updates live.{" "}
          {liveEvents.connected ? "" : "(reconnecting…)"}
        </div>
      )}

      <CheckableSummary run={run} />

      {run.reference_audit && (
        <ReferenceAuditCard runId={runId!} audit={run.reference_audit} />
      )}

      <StepCards steps={run.steps} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <VerdictBreakdownChart data={run.verdict_breakdown} />
        <ResolutionFunnelChart data={run.resolution_funnel} />
      </div>
    </div>
  );
}
