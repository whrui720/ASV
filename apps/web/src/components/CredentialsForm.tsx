import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CredentialField } from "../api/client";

// Editable credentials (SOURCE_ACQUISITION.md §3). The point of putting these
// in the UI is that the load-bearing ones fail *silently*: without
// UNPAYWALL_EMAIL the whole Unpaywall step is skipped behind a debug log, and
// the run that measured 31% source acquisition had exactly one key set. So each
// field states what breaks without it, and links to where to get it.
//
// Secrets are write-only: the server returns a masked hint, and a field left at
// its mask is dropped server-side rather than written back over the real value.

function FieldRow({
  field,
  draft,
  onChange,
}: {
  field: CredentialField;
  draft: string | undefined;
  onChange: (value: string) => void;
}) {
  const value = draft ?? field.value ?? "";
  const dirty = draft !== undefined && draft !== (field.value ?? "");
  const Input = field.input_type === "textarea" ? "textarea" : "input";

  return (
    <div className="rounded border bg-white p-3">
      <div className="flex items-start justify-between gap-3">
        <label htmlFor={field.name} className="min-w-0">
          <span className="text-sm font-medium text-gray-800">{field.label}</span>
          <span className="ml-2 font-mono text-xs text-gray-400">{field.name}</span>
          {field.required && <span className="ml-2 text-xs text-red-600">required</span>}
        </label>
        <span
          className={`flex-none rounded-full px-2 py-0.5 text-xs ${
            field.present ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-500"
          }`}
        >
          {field.present ? "set" : "not set"}
        </span>
      </div>

      <Input
        id={field.name}
        // A secret is never pre-filled with anything usable, so the browser has
        // nothing to autofill and nothing to leak into a password manager.
        type={field.input_type === "email" ? "email" : "text"}
        rows={field.input_type === "textarea" ? 3 : undefined}
        autoComplete="off"
        spellCheck={false}
        className={`mt-2 w-full rounded border px-2 py-1 font-mono text-sm ${
          dirty ? "border-blue-400 bg-blue-50" : "border-gray-300"
        }`}
        placeholder={field.placeholder || (field.present ? field.value : "")}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />

      <div className="mt-1.5 text-xs text-gray-600">{field.help}</div>
      {field.impact && (
        <div className="mt-1 text-xs text-gray-500">
          <span className="font-medium">Without it: </span>
          {field.impact}
        </div>
      )}
      <div className="mt-1 flex gap-3 text-xs">
        {field.signup_url && (
          <a
            href={field.signup_url}
            target="_blank"
            rel="noreferrer"
            className="text-blue-600 hover:underline"
          >
            Get a key →
          </a>
        )}
        {field.from_shell && (
          <span className="text-amber-700">
            Set in the shell environment — editing here will not override it.
          </span>
        )}
      </div>
    </div>
  );
}

export function CredentialsForm() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["credentials"],
    queryFn: api.getCredentials,
  });
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);

  const save = useMutation({
    mutationFn: (values: Record<string, string>) => api.saveCredentials(values),
    onSuccess: () => {
      setDrafts({});
      setSaved(true);
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
      // The presence dots on the rest of the page read the same catalogue.
      queryClient.invalidateQueries({ queryKey: ["config"] });
    },
  });

  // Any fresh edit clears the confirmation, so "Saved" never describes stale state.
  useEffect(() => {
    if (Object.keys(drafts).length > 0) setSaved(false);
  }, [drafts]);

  const grouped = useMemo(() => {
    if (!data) return [];
    return data.group_order
      .map((group) => ({
        group,
        blurb: data.group_blurb[group] ?? "",
        fields: data.fields.filter((f) => f.group === group),
      }))
      .filter((g) => g.fields.length > 0);
  }, [data]);

  if (isLoading || !data) return <div className="text-sm text-gray-500">Loading…</div>;

  const dirtyCount = Object.entries(drafts).filter(([name, v]) => {
    const field = data.fields.find((f) => f.name === name);
    return v !== (field?.value ?? "");
  }).length;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-base font-semibold">Credentials</h2>
        <p className="mt-1 max-w-3xl text-sm text-gray-600">
          Source acquisition is the pipeline's weakest stage: 80% of failed fetches are
          publishers refusing an unauthenticated request. Most of what fixes that is free
          — the fields below are the difference between finding an open-access mirror and
          reporting <span className="font-mono text-xs">source_download_failed</span>.
        </p>
        <p className="mt-1 text-xs text-gray-500">
          Saved to <span className="font-mono">{data.env_path}</span>. Each run is a fresh
          subprocess that re-reads that file, so a key added here applies to the next run
          without restarting the server. Secrets are never sent back to this page.
        </p>
      </div>

      {grouped.map(({ group, blurb, fields }) => (
        <section key={group} className="space-y-2">
          <div>
            <div className="text-sm font-medium text-gray-700">{group}</div>
            {blurb && <div className="text-xs text-gray-500">{blurb}</div>}
          </div>
          <div className="grid gap-2 lg:grid-cols-2">
            {fields.map((field) => (
              <FieldRow
                key={field.name}
                field={field}
                draft={drafts[field.name]}
                onChange={(value) => setDrafts((d) => ({ ...d, [field.name]: value }))}
              />
            ))}
          </div>
        </section>
      ))}

      <div className="sticky bottom-0 flex items-center gap-3 border-t bg-white/95 py-3 backdrop-blur">
        <button
          type="button"
          disabled={dirtyCount === 0 || save.isPending}
          onClick={() => save.mutate(drafts)}
          className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white disabled:bg-gray-300"
        >
          {save.isPending ? "Saving…" : `Save ${dirtyCount || ""} change${dirtyCount === 1 ? "" : "s"}`}
        </button>
        {dirtyCount > 0 && (
          <button
            type="button"
            onClick={() => setDrafts({})}
            className="text-sm text-gray-600 hover:underline"
          >
            Discard
          </button>
        )}
        {saved && <span className="text-sm text-green-700">Saved to .env</span>}
        {save.isError && (
          <span className="text-sm text-red-600">{(save.error as Error).message}</span>
        )}
      </div>
    </div>
  );
}
