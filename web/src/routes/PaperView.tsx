import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { api } from "../api/client";
import { VERDICT_DOT } from "../lib/verdict";

pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

const PAGE_WIDTH = 760;

// S5: the original PDF with claim spans highlighted, colored by verdict.
// `location_in_text` offsets don't map 1:1 to PDF coordinates (C5) — the
// backend resolves this server-side (§7) and just hands back normalized
// quads per claim; this component only has to paint boxes.
export function PaperView() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [numPages, setNumPages] = useState(0);

  const { data: highlights } = useQuery({
    queryKey: ["highlights", runId],
    queryFn: () => api.getHighlights(runId!),
    enabled: !!runId,
  });
  const { data: claimsPage } = useQuery({
    queryKey: ["claims-for-paper", runId],
    queryFn: () => api.listClaims(runId!, { page: 1, page_size: 1000 }),
    enabled: !!runId,
  });

  const verdictByClaim = new Map(
    (claimsPage?.claims ?? []).map((c) => [c.claim_id, c.result?.verdict ?? "skipped"])
  );

  const byPage = new Map<number, typeof highlights>();
  (highlights ?? []).forEach((h) => {
    if (!byPage.has(h.page)) byPage.set(h.page, []);
    byPage.get(h.page)!.push(h);
  });

  return (
    <div className="flex gap-4">
      <div className="flex-1">
        <Document
          file={api.paperPdfUrl(runId!)}
          onLoadSuccess={({ numPages }) => setNumPages(numPages)}
          loading={<div className="text-sm text-gray-500">Loading PDF…</div>}
          error={
            <div className="text-sm text-red-600">
              Could not load the original PDF (expected under pdfs/&lt;stem&gt;.pdf).
            </div>
          }
        >
          {Array.from({ length: numPages }, (_, i) => (
            <div key={i} className="relative mb-4 shadow border" style={{ width: PAGE_WIDTH }}>
              <Page pageNumber={i + 1} width={PAGE_WIDTH} />
              {(byPage.get(i) ?? []).map((h) =>
                h!.quads.map((q, qi) => {
                  const verdict = verdictByClaim.get(h!.claim_id) ?? "skipped";
                  const color = VERDICT_DOT[verdict as keyof typeof VERDICT_DOT];
                  return (
                    <div
                      key={`${h!.claim_id}-${qi}`}
                      title={h!.claim_id}
                      onClick={() => navigate(`/runs/${runId}/claims/${encodeURIComponent(h!.claim_id)}`)}
                      className="absolute cursor-pointer"
                      style={{
                        left: `${q[0] * 100}%`,
                        top: `${q[1] * 100}%`,
                        width: `${(q[2] - q[0]) * 100}%`,
                        height: `${(q[3] - q[1]) * 100}%`,
                        backgroundColor: color,
                        opacity: 0.28,
                        mixBlendMode: "multiply",
                      }}
                    />
                  );
                })
              )}
            </div>
          ))}
        </Document>
      </div>
      <aside className="w-72 flex-none">
        <div className="text-sm font-medium text-gray-700 mb-2">Claims in document order</div>
        <div className="space-y-1 max-h-[80vh] overflow-y-auto pr-1">
          {(claimsPage?.claims ?? [])
            .filter((c) => c.location_in_text?.start !== null && c.location_in_text?.start !== undefined)
            .sort((a, b) => (a.location_in_text!.start ?? 0) - (b.location_in_text!.start ?? 0))
            .map((c) => (
              <button
                key={c.claim_id}
                onClick={() => navigate(`/runs/${runId}/claims/${encodeURIComponent(c.claim_id)}`)}
                className="block w-full text-left text-xs p-2 rounded border hover:bg-gray-50"
              >
                <span
                  className="inline-block w-2 h-2 rounded-full mr-1 align-middle"
                  style={{ backgroundColor: VERDICT_DOT[c.result?.verdict ?? "skipped"] }}
                />
                {c.text.slice(0, 90)}
              </button>
            ))}
        </div>
      </aside>
    </div>
  );
}
