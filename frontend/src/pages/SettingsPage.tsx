// Settings: view and edit the decision thresholds in config/pests.yaml.
// IIHR mentors may give real values during the event; saving marks them
// "Confirmed with IIHR mentor on <date>" and the decisions update immediately.
import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type ThresholdField } from "../api";
import { useLiveData } from "../settings";
import { DecisionBadge, ErrorState, Spinner, prettyPest } from "../components/ui";

/** Same rules as the backend (backend/thresholds_editor.py), so errors show while typing. */
function validate(f: ThresholdField, raw: string): string | null {
  if (!raw.trim()) return "Required - enter a number.";
  const n = Number(raw);
  if (!Number.isFinite(n)) return "Must be a number.";
  if (f.type === "int" && !Number.isInteger(n)) return "Must be a whole number.";
  if (n < 0) return "Cannot be negative.";
  if (f.min_exclusive && n <= f.min) return `Must be greater than ${f.min}.`;
  if (n < f.min) return `Must be at least ${f.min}.`;
  if (n > f.max) return `Must be at most ${f.max} (is this a typo?).`;
  return null;
}

function StatusChip({ f }: { f: ThresholdField }) {
  if (f.status === "confirmed")
    return <span className="rounded-md bg-leaf-50 px-2 py-0.5 text-xs font-medium text-leaf-800 dark:bg-leaf-900/40 dark:text-leaf-100">✓ Confirmed {f.confirmed_on}</span>;
  if (f.status === "placeholder")
    return <span className="rounded-md bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-950 dark:text-amber-200">Placeholder</span>;
  return <span className="text-xs text-stone-500">not marked</span>;
}

function PestForm({ pest, fields, onSaved }: { pest: string; fields: Record<string, ThresholdField>; onSaved: () => void }) {
  const initial = () => Object.fromEntries(Object.entries(fields).map(([k, f]) => [k, String(f.value)]));
  const [values, setValues] = useState<Record<string, string>>(initial);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const [confirmUnchanged, setConfirmUnchanged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ text: string; decisions: Record<string, string> } | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => setValues(initial()), [fields]); // eslint-disable-line react-hooks/exhaustive-deps

  const errors: Record<string, string> = {};
  for (const [k, f] of Object.entries(fields)) {
    const e = validate(f, values[k] ?? "") ?? serverErrors[k];
    if (e) errors[k] = e;
  }
  const dirty = Object.entries(fields).some(([k, f]) => Number(values[k]) !== Number(f.value));
  const hasErrors = Object.keys(errors).length > 0;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (hasErrors) return;
    setBusy(true);
    setFailure(null);
    setResult(null);
    try {
      const r = await api.saveThresholds(pest, Object.fromEntries(Object.entries(values).map(([k, v]) => [k, Number(v)])), confirmUnchanged);
      const parts = [];
      if (r.changed.length) parts.push(`changed: ${r.changed.map((k) => fields[k]?.label ?? k).join(", ")}`);
      if (r.confirmed_unchanged.length) parts.push(`confirmed: ${r.confirmed_unchanged.map((k) => fields[k]?.label ?? k).join(", ")}`);
      setResult({ text: parts.length ? `Saved (${parts.join("; ")}). Old file backed up.` : "Nothing changed.", decisions: r.decisions });
      setServerErrors({});
      setConfirmUnchanged(false);
      onSaved();
    } catch (err) {
      const detail = (err as ApiError & { errors?: Record<string, string> }).errors;
      if (detail) setServerErrors(detail);
      setFailure((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="card space-y-4 p-5" noValidate>
      <h2 className="text-lg font-semibold">{prettyPest(pest)}</h2>
      <div className="grid gap-4 md:grid-cols-2">
        {Object.entries(fields).map(([k, f]) => (
          <div key={k}>
            <div className="flex items-center justify-between gap-2">
              <label htmlFor={`${pest}-${k}`} className="text-sm font-medium">{f.label}</label>
              <StatusChip f={f} />
            </div>
            <div className="mt-1 flex items-center gap-2">
              <input id={`${pest}-${k}`} inputMode="decimal" value={values[k] ?? ""}
                     aria-invalid={!!errors[k]} aria-describedby={`${pest}-${k}-help`}
                     onChange={(e) => { setValues({ ...values, [k]: e.target.value }); setServerErrors({ ...serverErrors, [k]: "" }); }}
                     className={`w-36 rounded-lg border bg-white px-3 py-2 tabular-nums dark:bg-stone-900 ${errors[k]
                       ? "border-red-500 focus:outline-red-600" : "border-stone-300 dark:border-stone-700"}`} />
              <span className="text-sm text-stone-500 dark:text-stone-400">{f.unit}</span>
            </div>
            {errors[k] ? (
              <p className="mt-1 text-sm text-red-700 dark:text-red-400" role="alert">{errors[k]}</p>
            ) : (
              <p id={`${pest}-${k}-help`} className="mt-1 text-xs text-stone-500 dark:text-stone-400">{f.help}</p>
            )}
          </div>
        ))}
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={confirmUnchanged} onChange={(e) => setConfirmUnchanged(e.target.checked)} />
        Also mark the values I did not change as confirmed by the IIHR mentor
      </label>
      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" disabled={busy || hasErrors || (!dirty && !confirmUnchanged)}
                className="rounded-lg bg-leaf-700 px-5 py-2 font-medium text-white hover:bg-leaf-800 disabled:cursor-not-allowed disabled:opacity-50">
          {busy ? "Saving…" : "Save"}
        </button>
        <button type="button" onClick={() => { setValues(initial()); setServerErrors({}); }} disabled={busy}
                className="rounded-lg border border-stone-300 px-4 py-2 text-sm dark:border-stone-700">Undo changes</button>
        {hasErrors && <span className="text-sm text-red-700 dark:text-red-400">Fix the highlighted values first.</span>}
      </div>
      {failure && <p className="text-sm text-red-700 dark:text-red-400" role="alert">Not saved: {failure}</p>}
      {result && (
        <div className="rounded-lg bg-leaf-50 p-3 text-sm text-leaf-900 dark:bg-leaf-900/30 dark:text-leaf-100" role="status">
          <p>{result.text}</p>
          {Object.keys(result.decisions).length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              Decisions recalculated:
              {Object.entries(result.decisions).map(([trap, action]) => (
                <span key={trap} className="flex items-center gap-1">{trap} <DecisionBadge action={action as "SPRAY"} /></span>
              ))}
            </div>
          )}
        </div>
      )}
    </form>
  );
}

export default function SettingsPage() {
  const { data, error, loading, reload } = useLiveData(api.thresholds);
  if (loading && !data) return <Spinner label="Loading settings…" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings: decision thresholds</h1>
        <p className="text-sm text-stone-500 dark:text-stone-400">
          Values come from <code>{data.file}</code>. Saving keeps a backup of the old file, marks edited values
          "Confirmed with IIHR mentor on &lt;today&gt;" and recalculates every trap's decision immediately.
        </p>
      </div>
      {Object.entries(data.pests).map(([pest, fields]) => <PestForm key={pest} pest={pest} fields={fields} onSaved={reload} />)}
      {data.backups.length > 0 && (
        <p className="text-xs text-stone-500 dark:text-stone-400">
          Backups in <code>config/backups/</code>: {data.backups.slice(0, 3).join(", ")}{data.backups.length > 3 ? " …" : ""}
        </p>
      )}
    </div>
  );
}
