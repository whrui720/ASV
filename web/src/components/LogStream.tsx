import { useEffect, useRef } from "react";
import type { LogLine, ProgressEvent } from "../hooks/useRunEvents";

export function LogStream({ logs }: { logs: LogLine[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight });
  }, [logs.length]);

  return (
    <div
      ref={ref}
      className="h-96 overflow-y-auto rounded-lg border bg-gray-950 text-gray-100 font-mono text-xs p-3 leading-relaxed"
    >
      {logs.length === 0 && <div className="text-gray-500">No log output yet…</div>}
      {logs.map((l, i) => (
        <div key={i} className="whitespace-pre-wrap break-all">
          {l.line}
        </div>
      ))}
    </div>
  );
}

export function EventTimeline({ events }: { events: ProgressEvent[] }) {
  return (
    <div className="h-96 overflow-y-auto rounded-lg border bg-white p-3 space-y-1">
      {events.length === 0 && <div className="text-sm text-gray-500">No events yet…</div>}
      {events.map((e, i) => (
        <div key={i} className="text-xs flex gap-2">
          <span className="text-gray-400 tabular-nums flex-none">
            {new Date(e.ts).toLocaleTimeString()}
          </span>
          <span className="font-medium text-gray-700 flex-none">{e.type}</span>
          <span className="text-gray-500 truncate">
            {Object.entries(e)
              .filter(([k]) => k !== "ts" && k !== "type")
              .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
              .join(" ")}
          </span>
        </div>
      ))}
    </div>
  );
}
