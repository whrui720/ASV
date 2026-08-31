import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { pct, seconds, timestampLabel, usd } from "../lib/format";

const STATUS_COLOR: Record<string, string> = {
  complete: "bg-green-100 text-green-800",
  running: "bg-blue-100 text-blue-800",
  awaiting_login: "bg-amber-100 text-amber-800",
  queued: "bg-gray-100 text-gray-600",
  failed: "bg-red-100 text-red-800",
};

export function RunsIndex() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showNewRun, setShowNewRun] = useState(false);

  const { data: runs, isLoading } = useQuery({
    queryKey: ["runs"],
    queryFn: api.listRuns,
    refetchInterval: 5000, // cheap poll so in-flight runs update without SSE on this page
  });

  const deleteMutation = useMutation({
    mutationFn: (runId: string) => api.deleteRun(runId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["runs"] }),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Runs</h1>
        <button
          onClick={() => setShowNewRun(true)}
          className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
        >
          New run
        </button>
      </div>

      {showNewRun && <NewRunForm onClose={() => setShowNewRun(false)} />}

      {isLoading && <div className="text-sm text-gray-500">Loading…</div>}

      <div className="overflow-x-auto rounded-lg border bg-white">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-gray-50 border-b text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th className="px-3 py-2">Paper</th>
              <th className="px-3 py-2">Timestamp</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Claims</th>
              <th className="px-3 py-2">Pass rate</th>
              <th className="px-3 py-2">Unresolved</th>
              <th className="px-3 py-2">Elapsed</th>
              <th className="px-3 py-2">Cost</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {runs?.map((r) => (
              <tr
                key={r.run_id}
                className="border-b last:border-0 hover:bg-gray-50 cursor-pointer"
                onClick={() => navigate(`/runs/${r.run_id}`)}
              >
                <td className="px-3 py-2 font-medium text-gray-900">{r.pdf_stem}</td>
                <td className="px-3 py-2 text-gray-500">{timestampLabel(r.timestamp)}</td>
                <td className="px-3 py-2">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLOR[r.status]}`}>
                    {r.status}
                  </span>
                </td>
                <td className="px-3 py-2">{r.total_claims ?? "—"}</td>
                <td className="px-3 py-2">{pct(r.pass_rate)}</td>
                <td className="px-3 py-2">{pct(r.unresolved_source_rate)}</td>
                <td className="px-3 py-2">{seconds(r.total_elapsed_seconds)}</td>
                <td className="px-3 py-2">{usd(r.cost?.total_cost)}</td>
                <td className="px-3 py-2 text-right">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      if (confirm(`Delete run ${r.run_id}? This cannot be undone.`)) {
                        deleteMutation.mutate(r.run_id);
                      }
                    }}
                    className="text-gray-400 hover:text-red-600 text-xs"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {runs?.length === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-8 text-center text-gray-400">
                  No runs yet. Click "New run" to validate a paper.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function NewRunForm({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: pdfs } = useQuery({ queryKey: ["pdfs"], queryFn: api.listPdfs });
  const [selectedPath, setSelectedPath] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const createMutation = useMutation({
    mutationFn: () => (file ? api.createRunFromUpload(file) : api.createRunFromPath(selectedPath)),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      navigate(`/runs/${res.run_id}`);
    },
  });

  return (
    <div className="rounded-lg border bg-white p-4 space-y-3">
      <div className="text-sm font-medium">Launch a new run</div>
      <p className="text-xs text-gray-500">
        The pipeline runs autonomously end-to-end by default — no review gates are enabled here
        (accept-by-default per design). HITL checkpoints, when they occur, surface on the run
        monitor.
      </p>
      <div className="flex items-center gap-3">
        <select
          className="rounded border-gray-300 text-sm flex-1"
          value={selectedPath}
          onChange={(e) => {
            setSelectedPath(e.target.value);
            setFile(null);
          }}
        >
          <option value="">Pick from pdfs/…</option>
          {pdfs?.map((p) => (
            <option key={p} value={`pdfs/${p}`}>
              {p}
            </option>
          ))}
        </select>
        <span className="text-xs text-gray-400">or</span>
        <input
          type="file"
          accept="application/pdf"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setSelectedPath("");
          }}
          className="text-sm"
        />
      </div>
      <div className="flex justify-end gap-2">
        <button onClick={onClose} className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900">
          Cancel
        </button>
        <button
          disabled={(!selectedPath && !file) || createMutation.isPending}
          onClick={() => createMutation.mutate()}
          className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {createMutation.isPending ? "Launching…" : "Launch"}
        </button>
      </div>
      {createMutation.isError && (
        <p className="text-xs text-red-600">{(createMutation.error as Error).message}</p>
      )}
    </div>
  );
}
