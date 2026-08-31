import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";

export interface ProgressEvent {
  ts: string;
  type: string;
  [key: string]: unknown;
}

export interface LogLine {
  ts: number;
  line: string;
}

interface RunEventsState {
  events: ProgressEvent[];
  logs: LogLine[];
  awaitingLoginDomains: string[] | null;
  terminalStatus: string | null;
  connected: boolean;
}

/**
 * Subscribes to /api/runs/{id}/events (SSE) — the live progress + log tail
 * for the run monitor (S7) and the awaiting-login banner (§8). Reconnects on
 * drop; stops once a "terminal" event is received.
 */
export function useRunEvents(runId: string | null, enabled: boolean): RunEventsState {
  const [state, setState] = useState<RunEventsState>({
    events: [],
    logs: [],
    awaitingLoginDomains: null,
    terminalStatus: null,
    connected: false,
  });
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!runId || !enabled) return;

    setState({ events: [], logs: [], awaitingLoginDomains: null, terminalStatus: null, connected: false });

    const es = new EventSource(api.eventsUrl(runId));
    sourceRef.current = es;

    es.onopen = () => setState((s) => ({ ...s, connected: true }));

    es.addEventListener("progress", (ev) => {
      const payload = JSON.parse((ev as MessageEvent).data) as ProgressEvent;
      setState((s) => {
        const next = { ...s, events: [...s.events, payload] };
        if (payload.type === "awaiting_login") {
          next.awaitingLoginDomains = (payload.domains as string[]) ?? [];
        } else if (payload.type === "login_complete" || payload.type === "login_timeout") {
          next.awaitingLoginDomains = null;
        }
        return next;
      });
    });

    es.addEventListener("log", (ev) => {
      const payload = JSON.parse((ev as MessageEvent).data) as { line: string };
      setState((s) => ({ ...s, logs: [...s.logs, { ts: Date.now(), line: payload.line }] }));
    });

    es.addEventListener("terminal", (ev) => {
      const payload = JSON.parse((ev as MessageEvent).data) as { status: string };
      setState((s) => ({ ...s, terminalStatus: payload.status }));
      es.close();
    });

    es.onerror = () => {
      setState((s) => ({ ...s, connected: false }));
    };

    return () => {
      es.close();
      sourceRef.current = null;
    };
  }, [runId, enabled]);

  return state;
}
