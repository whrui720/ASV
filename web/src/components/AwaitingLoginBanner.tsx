import { useState } from "react";
import { api } from "../api/client";

// §8: "Chromium has opened on this machine. Log in to nature.com,
// sciencedirect.com, then click Continue." The browser window Playwright
// opened is on the machine running the backend — for v1 (localhost) that's
// the user's own screen, so this banner states that plainly.
export function AwaitingLoginBanner({ runId, domains }: { runId: string; domains: string[] }) {
  const [confirming, setConfirming] = useState(false);

  async function handleContinue() {
    setConfirming(true);
    try {
      await api.confirmLogin(runId);
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 flex items-start gap-3">
      <div className="flex-1">
        <div className="font-medium text-amber-900">Waiting for login</div>
        <p className="text-sm text-amber-800 mt-1">
          A Chromium window has opened on this machine. Log in to{" "}
          <strong>{domains.join(", ")}</strong>, then click Continue.
        </p>
      </div>
      <button
        onClick={handleContinue}
        disabled={confirming}
        className="flex-none rounded-md bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
      >
        {confirming ? "Confirming…" : "Continue"}
      </button>
    </div>
  );
}
