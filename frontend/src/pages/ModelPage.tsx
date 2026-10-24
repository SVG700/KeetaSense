// Model page: which detector is running, and how well it MEASURED on its test set.
// Every number here comes from ml/evaluate.py reports - nothing is estimated in the UI.
import { useState } from "react";
import { api, type EvalReport } from "../api";
import { useLiveData } from "../settings";
import { EmptyState, ErrorState, Spinner, Tag, prettyPest } from "../components/ui";

const pct = (v: number | null | undefined) => (v == null ? "–" : `${(v * 100).toFixed(1)}%`);
const num = (v: number | null | undefined, digits = 2) => (v == null ? "–" : v.toFixed(digits));

function ReportView({ r }: { r: EvalReport }) {
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {r.synthetic_data ? <Tag>⚗ Synthetic test data</Tag> : <Tag tone="green">Real test data</Tag>}
        <Tag tone="stone">{r.detector_mode === "demo_detector" ? "Demo detector" : `YOLOv8 + SAHI${r.weights ? ` · ${r.weights}` : ""}`}</Tag>
        <span className="text-stone-500 dark:text-stone-400">
          {r.test_images} test images · {r.created ? new Date(r.created).toLocaleString() : "unknown date"}
        </span>
      </div>
      <p className="text-xs text-stone-500 dark:text-stone-400">
        Dataset: <code>{r.dataset}</code> · IoU {r.iou_threshold} · confidence ≥ {r.confidence_threshold} · report file <code>ml/reports/{r.file}</code>
      </p>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-xl bg-stone-100 p-3 dark:bg-stone-800">
          <div className="text-xs text-stone-500 dark:text-stone-400">mAP@0.5</div>
          <div className="text-2xl font-bold tabular-nums">{num(r.map50, 3)}</div>
        </div>
        {(["all_pests", "all_predators"] as const).map((k) => (
          <div key={k} className="rounded-xl bg-stone-100 p-3 dark:bg-stone-800">
            <div className="text-xs text-stone-500 dark:text-stone-400">Counting error, {k === "all_pests" ? "pests" : "predators"}</div>
            <div className="text-2xl font-bold tabular-nums">{num(r.counting_error[k]?.mae)} <span className="text-sm font-medium">MAE</span></div>
            <div className="text-xs text-stone-500 dark:text-stone-400">
              MAPE {r.counting_error[k]?.mape_percent ?? "–"}% · avg true count {r.counting_error[k]?.mean_true_count ?? "–"}
            </div>
          </div>
        ))}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] text-sm">
          <thead className="text-left text-stone-500 dark:text-stone-400">
            <tr>
              <th className="py-1">Class</th><th>Category</th><th className="text-right">Test objects</th>
              <th className="text-right">Precision</th><th className="text-right">Recall</th><th className="text-right">AP@0.5</th>
              <th className="text-right">Count MAE</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {Object.entries(r.per_class).map(([name, c]) => (
              <tr key={name} className="border-t border-stone-100 dark:border-stone-800">
                <td className="py-1">{prettyPest(name)}</td><td>{c.category}</td>
                <td className="text-right">{c.ground_truth}</td><td className="text-right">{pct(c.precision)}</td>
                <td className="text-right">{pct(c.recall)}</td><td className="text-right">{num(c.ap50, 3)}</td>
                <td className="text-right">{num(r.counting_error[name]?.mae)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-stone-500 dark:text-stone-400">
        MAE = average |predicted − true| insects per image. MAPE = average percentage error, over images with at least one insect.
      </p>
    </div>
  );
}

export default function ModelPage() {
  const { data, error, loading, reload } = useLiveData(api.model);
  const [selected, setSelected] = useState<string | null>(null);

  if (loading && !data) return <Spinner label="Loading model information…" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  const { detector: d, featured, reports, warning } = data;
  const shown = reports.find((r) => r.name === selected) ?? featured;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">Model</h1>

      <section className="card p-5">
        <h2 className="font-semibold">Active detector</h2>
        <p className="mt-1 text-lg">{d.label}</p>
        <dl className="mt-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
          <div><dt className="inline text-stone-500">Weights file: </dt><dd className="inline break-all"><code>{d.weights_path}</code>{d.mode === "demo_detector" ? " (not found or not loadable)" : ""}</dd></div>
          {d.trained_at && <div><dt className="inline text-stone-500">Trained: </dt><dd className="inline">{new Date(d.trained_at).toLocaleString()} ({d.trained_at_source})</dd></div>}
          {d.classes && <div><dt className="inline text-stone-500">Classes: </dt><dd className="inline">{d.classes.join(", ")}</dd></div>}
          {d.load_error && <div className="sm:col-span-2 text-red-700 dark:text-red-400"><dt className="inline">Load error: </dt><dd className="inline">{d.load_error}</dd></div>}
        </dl>
        {d.mode === "demo_detector" && (
          <p className="mt-3 text-sm text-stone-600 dark:text-stone-300">
            To switch to the AI model: train on Colab (<code>ml/train_colab.ipynb</code>), then run{" "}
            <code>python -m ml.install_model keetasense_model_&lt;date&gt;.zip</code> and restart the backend.
          </p>
        )}
        {d.synthetic_data && <p className="mt-3 font-semibold text-amber-800 dark:text-amber-300">⚠ This model was trained on synthetic data only.</p>}
      </section>

      {warning && (
        <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200" role="alert">
          <strong>⚠ {warning}</strong>
        </div>
      )}

      <section className="card p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold">Evaluation report</h2>
          {reports.length > 1 && (
            <label className="text-sm">
              <span className="mr-2 text-stone-500">Report:</span>
              <select value={shown?.name ?? ""} onChange={(e) => setSelected(e.target.value)}
                      className="rounded-lg border border-stone-300 bg-white px-2 py-1 dark:border-stone-700 dark:bg-stone-900">
                {reports.map((r) => (
                  <option key={r.name} value={r.name}>{r.name}{r.synthetic_data ? " (synthetic)" : " (real)"}</option>
                ))}
              </select>
            </label>
          )}
        </div>
        {shown ? <ReportView r={shown} /> : <EmptyState title="No evaluation report yet">Run <code>python -m ml.evaluate</code> on the real test split.</EmptyState>}
      </section>
    </div>
  );
}
