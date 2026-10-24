// Phone check: a farmer without the smart trap uploads a photo of an ordinary
// yellow sticky trap and gets counts plus a recommendation.
import { useEffect, useState, type FormEvent } from "react";
import { api, mediaUrl, type PhoneCheckResult } from "../api";
import { DecisionBadge, DetectorTag, ErrorState, prettyPest } from "../components/ui";

export default function PhoneCheck() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [days, setDays] = useState(1);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PhoneCheckResult | null>(null);
  const [error, setError] = useState<Error | null>(null);

  // show the chosen photo immediately, and free the memory when it changes
  useEffect(() => {
    if (!file) return setPreview(null);
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.phoneCheck(file, days));
    } catch (err) {
      setError(err as Error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Phone check</h1>
        <p className="text-sm text-stone-500 dark:text-stone-400">
          No smart trap? Photograph your yellow sticky trap straight-on, in good light, filling the frame.
        </p>
      </div>

      <form onSubmit={submit} className="card grid gap-4 p-5 md:grid-cols-[1fr_auto] md:items-end">
        <label className="block">
          <span className="text-sm font-medium">Trap photo</span>
          <input type="file" accept="image/*" capture="environment"
                 onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                 className="mt-1 block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-trap-400 file:px-3 file:py-2 file:font-medium file:text-stone-900 hover:file:bg-trap-300" />
        </label>
        <div className="flex flex-wrap items-end gap-3">
          <label className="block">
            <span className="text-sm font-medium">Days the trap has been hanging</span>
            <input type="number" min={1} max={60} value={days}
                   onChange={(e) => setDays(Math.max(1, Math.min(60, Number(e.target.value) || 1)))}
                   className="mt-1 block w-28 rounded-lg border border-stone-300 bg-white px-3 py-2 dark:border-stone-700 dark:bg-stone-900" />
          </label>
          <button type="submit" disabled={!file || busy}
                  className="rounded-lg bg-leaf-700 px-5 py-2 font-medium text-white hover:bg-leaf-800 disabled:cursor-not-allowed disabled:opacity-50">
            {busy ? "Counting insects…" : "Check my trap"}
          </button>
        </div>
      </form>

      {error && <ErrorState error={error} />}

      <div className="grid gap-6 lg:grid-cols-2">
        {preview && !result && (
          <section className="card p-4">
            <h2 className="mb-2 font-semibold">Your photo</h2>
            <img src={preview} alt="Selected trap photo" className="w-full rounded-xl" />
          </section>
        )}
        {result && (
          <>
            <section className="card p-4">
              <h2 className="mb-2 font-semibold">Detected insects</h2>
              <img src={mediaUrl(result.annotated_url)} alt="Your photo with detection boxes" className="w-full rounded-xl" />
              <p className="mt-2 text-xs text-stone-500">Red boxes = pests, green boxes = predators.</p>
            </section>
            <section className="card space-y-4 p-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <DecisionBadge action={result.decision.action} size="lg" />
                <DetectorTag mode={result.detector_mode} />
              </div>
              <p className="leading-relaxed">{result.decision.reason}</p>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl bg-stone-100 p-3 dark:bg-stone-800">
                  <div className="text-xs text-stone-600 dark:text-stone-300">Pests</div>
                  <div className="text-2xl font-bold tabular-nums">{result.pest_total}</div>
                </div>
                <div className="rounded-xl bg-stone-100 p-3 dark:bg-stone-800">
                  <div className="text-xs text-stone-600 dark:text-stone-300">Predators</div>
                  <div className="text-2xl font-bold tabular-nums">{result.predator_total}</div>
                </div>
              </div>
              <table className="w-full text-sm">
                <tbody>
                  {Object.entries(result.counts).map(([k, v]) => (
                    <tr key={k} className="border-t border-stone-100 dark:border-stone-800">
                      <td className="py-1">{prettyPest(k)}</td><td className="text-right tabular-nums">{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {result.warning && (
                <p className="rounded-lg bg-amber-50 p-3 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-200">{result.warning}</p>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}
