import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { useNavigate, useParams } from "react-router-dom";
import type { ClaimRow } from "../api/client";
import { VerdictBadge } from "./VerdictBadge";
import { ConfidenceGauge } from "./ConfidenceGauge";
import { GROUP_LABEL } from "../lib/verdict";
import { truncate } from "../lib/format";

interface Props {
  rows: ClaimRow[];
  selected: Set<string>;
  onToggleSelect: (claimId: string) => void;
  onToggleSelectAll: () => void;
}

export function ClaimsTable({ rows, selected, onToggleSelect, onToggleSelectAll }: Props) {
  const navigate = useNavigate();
  const { runId } = useParams();

  const columns: ColumnDef<ClaimRow>[] = [
    {
      id: "select",
      header: () => (
        <input
          type="checkbox"
          checked={rows.length > 0 && rows.every((r) => selected.has(r.claim_id))}
          onChange={onToggleSelectAll}
        />
      ),
      cell: ({ row }) => (
        <input
          type="checkbox"
          checked={selected.has(row.original.claim_id)}
          onChange={(e) => {
            e.stopPropagation();
            onToggleSelect(row.original.claim_id);
          }}
          onClick={(e) => e.stopPropagation()}
        />
      ),
    },
    {
      accessorKey: "text",
      header: "Claim",
      cell: ({ row }) => <span className="text-sm text-gray-900">{truncate(row.original.text, 110)}</span>,
    },
    {
      accessorKey: "group",
      header: "Group",
      cell: ({ row }) => <span className="text-xs text-gray-500">{GROUP_LABEL[row.original.group]}</span>,
    },
    {
      id: "citation",
      header: "Citation",
      cell: ({ row }) => (
        <span className="text-xs text-gray-500">{row.original.citation?.id ?? "—"}</span>
      ),
    },
    {
      id: "verdict",
      header: "Verdict",
      cell: ({ row }) =>
        row.original.result ? (
          <VerdictBadge
            verdict={row.original.result.verdict}
            reason={row.original.result.not_checkable_reason}
            legacy={row.original.result.legacy}
          />
        ) : (
          "—"
        ),
    },
    {
      id: "evidence",
      header: "Evidence",
      // Tier 0.5: a finding with no quoted span is not shippable, so showing
      // the count here makes the difference between a checkable finding and an
      // abstention visible without opening the row.
      cell: ({ row }) => {
        const n = row.original.result?.evidence?.length ?? 0;
        return n > 0 ? (
          <span className="text-xs text-gray-700">{n} quote{n === 1 ? "" : "s"}</span>
        ) : (
          <span className="text-xs text-gray-400">—</span>
        );
      },
    },
    {
      id: "confidence",
      header: "Confidence",
      cell: ({ row }) =>
        row.original.result ? <ConfidenceGauge value={row.original.result.confidence} /> : "—",
    },
    {
      id: "method",
      header: "Method",
      cell: ({ row }) => (
        <span className="text-xs text-gray-500">{row.original.result?.method ?? "—"}</span>
      ),
    },
  ];

  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel() });

  return (
    <div className="overflow-x-auto rounded-lg border bg-white">
      <table className="min-w-full text-left">
        <thead className="bg-gray-50 border-b text-xs uppercase tracking-wide text-gray-500">
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((h) => (
                <th key={h.id} className="px-3 py-2 font-medium">
                  {flexRender(h.column.columnDef.header, h.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              className="border-b last:border-0 hover:bg-gray-50 cursor-pointer"
              onClick={() => navigate(`/runs/${runId}/claims/${encodeURIComponent(row.original.claim_id)}`)}
            >
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="px-3 py-2 align-top">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="px-3 py-8 text-center text-sm text-gray-400">
                No claims match the current filters.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
