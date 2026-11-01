// Trap detail: counts over time, degree-day progress, latest annotated tape image.
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, mediaUrl } from "../api";
import { useT } from "../i18n";
import { useLiveData } from "../settings";
import { CountsChart, DegreeDayChart, DegreeDayMeter } from "../components/charts";
import TapeEditor from "../components/TapeEditor";
import {
  ActionStrip, DecisionBadge, DetectorTag, EmptyState, ErrorState, QualityBadge, ReplayTag, SimulatedTag, Spinner, StatusDot,
  prettyPest, timeAgo,
} from "../components/ui";

const RANGES = [7, 14, 30];

export default function TrapDetail() {
  const { id = "" } = useParams();
  const [days, setDays] = useState(14);
  const { data, error, loading, reload } = useLiveData(() => api.history(id, days), [id, days]);
  const t = useT();

  if (loading && !data) return <Spinner label="Loading trap history…" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  const { trap, sections, climate_daily, decisions } = data;
  const d = trap.decision;
  const latest = trap.latest_section;
  const pest = trap.target_pest;
  const simulated = trap.simulated || sections.some((s) => s.simulated);

  return (
    <div className="space-y-6">
      <Link to="/" className="text-sm text-leaf-700 hover:underline dark:text-leaf-500">← All traps</Link>

      <section className="card relative overflow-hidden pl-2">
        <ActionStrip action={d.action} />
        <div className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="text-2xl font-bold tracking-tight">{trap.name}</h1>
              <p className="text-sm text-stone-500 dark:text-stone-400">
                {trap.location} · {trap.crop} · target pest: {prettyPest(pest)}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <StatusDot status={trap.status} />
                <span className="text-xs text-stone-500">updated {timeAgo(trap.last_seen)}</span>
                {latest && <QualityBadge status={latest.quality_status} reasons={latest.quality_reasons} showOk />}
                {latest?.source === "replay" && <ReplayTag />}
                {simulated && <SimulatedTag />}
                {latest && <DetectorTag mode={latest.detector_mode} />}
              </div>
            </div>
            <DecisionBadge action={d.action} size="lg" />
          </div>
          <p className="mt-4 max-w-3xl leading-relaxed text-stone-700 dark:text-stone-300">{d.reason}</p>
          <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div><dt className="text-stone-500">Pests / day</dt><dd className="text-lg font-semibold tabular-nums">{d.pests_per_day.toFixed(1)}</dd></div>
            <div><dt className="text-stone-500">Predators / day</dt><dd className="text-lg font-semibold tabular-nums">{d.predators_per_day.toFixed(1)}</dd></div>
            <div><dt className="text-stone-500">Pests per predator</dt><dd className="text-lg font-semibold tabular-nums">{d.ratio != null ? d.ratio.toFixed(1) : "–"}</dd></div>
            <div><dt className="text-stone-500">Averaged over</dt><dd className="text-lg font-semibold tabular-nums">{d.window_days_used} day(s)</dd></div>
          </dl>
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="card p-5 lg:col-span-2">
          <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-semibold">Daily catch: pests vs predators</h2>
            <div className="flex gap-1" role="group" aria-label="Time range">
              {RANGES.map((r) => (
                <button key={r} onClick={() => setDays(r)} aria-pressed={days === r}
                        className={`rounded-md px-2.5 py-1 text-xs font-medium ${days === r ? "bg-leaf-700 text-white" : "bg-stone-100 text-stone-700 dark:bg-stone-800 dark:text-stone-300"}`}>
                  {r} days
                </button>
              ))}
            </div>
          </div>
          <p className="mb-2 text-xs text-stone-500 dark:text-stone-400">Each point is one tape section (one day of exposure).</p>
          {sections.length ? (
            <CountsChart sections={sections} threshold={trap.thresholds.action_threshold_per_day} pestName={pest} />
          ) : (
            <EmptyState title="No tape sections in this period" />
          )}
        </section>

        <section className="card p-5">
          <h2 className="mb-3 font-semibold">Next generation forecast</h2>
          <DegreeDayMeter dd={d.degree_days} perGeneration={trap.thresholds.degree_days_per_generation} pestName={pest} />
          <h3 className="mb-1 mt-5 text-sm font-medium">Degree-days per day</h3>
          <p className="mb-2 text-xs text-stone-500 dark:text-stone-400">
            max(0, (Tmax + Tmin) / 2 − {trap.thresholds.base_temp_c} °C), from the trap's DHT22.
          </p>
          {climate_daily.length ? <DegreeDayChart days={climate_daily} /> : <p className="text-sm text-stone-500">No temperature data yet.</p>}
        </section>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="card p-5 lg:col-span-2">
          <h2 className="font-semibold">Latest tape section</h2>
          {latest ? (
            <>
              {latest.source === "replay" && (
                <p className="mb-2 text-sm font-medium text-sky-800 dark:text-sky-300">▶ Replay: this image was recorded earlier and replayed for the demo.</p>
              )}
              <p className="mb-3 text-xs text-stone-500 dark:text-stone-400">
                {new Date(latest.timestamp).toLocaleString()} ·{" "}
                {Object.entries(latest.counts).map(([k, v]) => `${prettyPest(k)}: ${v}`).join(" · ")}
              </p>
              <TapeEditor key={latest.id} sectionId={latest.id} onChanged={reload} />
              <p className="mt-2 text-xs text-stone-500">
                Boxes: <span className="font-medium">red = pest</span>, <span className="font-medium">green = predator</span>, dashed = added by a scout.{" "}
                <a href={mediaUrl(latest.annotated_url)} target="_blank" rel="noreferrer" className="underline">Open the model's annotated photo</a>
              </p>
              {latest.quality_status && (
                <p className="mt-1 text-xs text-stone-500 dark:text-stone-400">
                  {t("quality.title")}: {t(`quality.${latest.quality_status}`)} · {t("quality.metrics", {
                    blur: latest.quality_metrics.blur ?? "–", brightness: latest.quality_metrics.brightness ?? "–",
                    glare: latest.quality_metrics.glare_pct ?? "–",
                    sim: latest.quality_metrics.similarity_to_previous ?? "–" })}
                </p>
              )}
            </>
          ) : (
            <EmptyState title="No image yet" />
          )}
        </section>

        <section className="card p-5">
          <h2 className="mb-3 font-semibold">Decision history</h2>
          {decisions.length === 0 ? (
            <p className="text-sm text-stone-500">No decisions yet.</p>
          ) : (
            <ol className="space-y-3">
              {/* show only the moments when the action changed */}
              {decisions.filter((x, i) => i === decisions.length - 1 || x.action !== decisions[i + 1].action).slice(0, 8).map((x) => (
                <li key={x.timestamp} className="text-sm">
                  <DecisionBadge action={x.action} />
                  <div className="mt-1 text-xs text-stone-500">since {new Date(x.timestamp).toLocaleString()}</div>
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
    </div>
  );
}
