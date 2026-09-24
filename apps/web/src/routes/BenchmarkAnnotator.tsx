import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { GoldPair, Verdict } from "../api/client";
import { VERDICT_DESCRIPTION, VERDICT_LABEL, VERDICT_ORDER } from "../lib/verdict";

// Tier 0.4 annotation surface.
//
// VALUE_PROPOSITION.md §2.5: "There is no labelled set, so no precision, no
// recall, no false-accusation rate. Every quality statement about ASV —
// including the optimistic ones — is currently anecdote."
//
// Nothing here replaces the human judgment; it just removes everything else
// from the loop. Keyboard-first (1-5 to label, h for hard, j/k to move) because
// 250 pairs at 3 minutes is 12.5 hours and at 90 seconds is 6.

const KEY_TO_VERDICT: Record<string, Verdict> = {
  "1": "substantiated",
  "2": "partially_substantiated",
  "3": "not_substantiated",
  "4": "contradicted",
  "5": "not_checkable",
};

export function BenchmarkAnnotator() {
  const queryClient = useQueryClient();
  const [annotator, setAnnotator] = useState(
    () => localStorage.getItem("asv.annotator") ?? ""
  );
  const [index, setIndex] = useState(0);
  const [hard, setHard] = useState(false);
  const [reason, setReason] = useState("");
  const [secondPass, setSecondPass] = useState(false);

  const { data: stats } = useQuery({
    queryKey: ["benchmark", "stats"],
    queryFn: () => api.benchmarkStats(),
  });

  const { data: pairs } = useQuery({
    queryKey: ["benchmark", "pairs", secondPass],
    queryFn: () =>
      api.benchmarkPairs({
        unlabelled_only: !secondPass,
        needs_second_pass: secondPass,
      }),
  });

  const pair: GoldPair | undefined = pairs?.[index];

  const label = useMutation({
    mutationFn: (verdict: Verdict) =>
      api.benchmarkLabel({
        pair_id: pair!.pair_id,
        label: verdict,
        annotator,
        label_reason: reason,
        difficulty: hard ? "hard" : "easy",
        second_pass: secondPass,
        // Keep the stored passages as they are: `notes` carries the retrieved
        // source text the annotator judged against, and blanking it would make
        // the pair unreproducible.
        notes: "",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["benchmark", "stats"] });
      setReason("");
      setHard(false);
      setIndex((i) => i + 1);
    },
  });

  useEffect(() => {
    if (annotator) localStorage.setItem("asv.annotator", annotator);
  }, [annotator]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;
      if (!pair || !annotator) return;
      if (KEY_TO_VERDICT[e.key]) {
        e.preventDefault();
        label.mutate(KEY_TO_VERDICT[e.key]);
      } else if (e.key === "h") {
        setHard((v) => !v);
      } else if (e.key === "j") {
        setIndex((i) => Math.min(i + 1, (pairs?.length ?? 1) - 1));
      } else if (e.key === "k") {
        setIndex((i) => Math.max(i - 1, 0));
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pair, annotator, pairs, label]);

  const progress = useMemo(() => {
    if (!stats) return null;
    const total = stats.labelled + stats.unlabelled;
    return { total, done: stats.labelled, pct: total ? stats.labelled / total : 0 };
  }, [stats]);

  if (!annotator) {
    return (
      <div className="max-w-md space-y-3">
        <h1 className="text-lg font-semibold">Gold-set annotation</h1>
        <p className="text-sm text-gray-600">
          Your initials are recorded on every label you make, so a second annotator
          can be assigned the overlap that makes inter-annotator agreement
          computable.
        </p>
        <input
          autoFocus
          placeholder="Your initials"
          className="rounded border-gray-300 text-sm w-40"
          onKeyDown={(e) => {
            if (e.key === "Enter") setAnnotator((e.target as HTMLInputElement).value.trim());
          }}
        />
        <p className="text-xs text-gray-500">Press Enter to start.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-lg font-semibold">Gold-set annotation</h1>
          <p className="text-sm text-gray-500">
            {progress
              ? `${progress.done} of ${progress.total} pairs labelled (${(progress.pct * 100).toFixed(0)}%)`
              : "…"}{" "}
            · annotator {annotator}
          </p>
        </div>
        <label className="text-xs text-gray-600 flex items-center gap-2">
          <input
            type="checkbox"
            checked={secondPass}
            onChange={(e) => {
              setSecondPass(e.target.checked);
              setIndex(0);
            }}
          />
          Second-pass mode (label pairs someone else already judged)
        </label>
      </div>

      {stats && stats.readiness_problems.length > 0 && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <div className="font-medium mb-1">This gold set is not publishable yet</div>
          <ul className="list-disc ml-5 space-y-0.5">
            {stats.readiness_problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
      )}

      {!pair && (
        <div className="rounded-lg border bg-white p-6 text-sm text-gray-600">
          {secondPass
            ? "Nothing awaiting a second pass."
            : "Every seeded pair has been labelled. Run scripts/seed_miscitations.py to build hard negatives, or scripts/build_gold_seed.py to pull in more runs."}
        </div>
      )}

      {pair && (
        <div className="space-y-4">
          <div className="rounded-lg border bg-white p-4">
            <div className="text-xs text-gray-500 mb-1">
              {pair.pair_id} · {pair.field} · {pair.provenance}
              {pair.is_seeded_negative && " · seeded"}
            </div>
            <p className="text-base text-gray-900">{pair.claim_text}</p>
          </div>

          <div className="rounded-lg border bg-white p-4">
            <div className="text-xs font-medium text-gray-500 mb-2">
              Source passages
              {pair.source?.url && (
                <a
                  className="ml-2 font-normal text-indigo-700 hover:underline break-all"
                  href={pair.source.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  open source ↗
                </a>
              )}
            </div>
            <pre className="text-sm text-gray-800 whitespace-pre-wrap max-h-96 overflow-y-auto">
              {pair.notes || "(no passage stored — open the source link)"}
            </pre>
          </div>

          <div className="rounded-lg border bg-white p-4 space-y-3">
            <div className="text-xs font-medium text-gray-500">
              Does the source substantiate the claim?
            </div>
            <div className="flex flex-wrap gap-2">
              {VERDICT_ORDER.map((v, i) => (
                <button
                  key={v}
                  title={VERDICT_DESCRIPTION[v]}
                  onClick={() => label.mutate(v)}
                  disabled={label.isPending}
                  className="rounded-md border px-3 py-2 text-sm hover:bg-gray-50 disabled:opacity-50"
                >
                  <span className="text-gray-400 mr-1">
                    {Object.entries(KEY_TO_VERDICT).find(([, val]) => val === v)?.[0] ?? i + 1}
                  </span>
                  {VERDICT_LABEL[v]}
                </button>
              ))}
            </div>

            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why? (one line — this is what makes a disputed label resolvable later)"
              className="w-full rounded border-gray-300 text-sm"
            />

            <label className="text-xs text-gray-600 flex items-center gap-2">
              <input type="checkbox" checked={hard} onChange={(e) => setHard(e.target.checked)} />
              Hard case (<kbd className="px-1 border rounded">h</kbd>) — borderline, or one a
              naive system would get wrong
            </label>

            <div className="text-xs text-gray-400">
              <kbd className="px-1 border rounded">1</kbd>–
              <kbd className="px-1 border rounded">5</kbd> label ·{" "}
              <kbd className="px-1 border rounded">h</kbd> hard ·{" "}
              <kbd className="px-1 border rounded">j</kbd>/
              <kbd className="px-1 border rounded">k</kbd> next/previous
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
