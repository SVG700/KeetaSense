// Overview: summary numbers, one traffic-light card per trap, recent alerts.
import { Link } from "react-router-dom";
import { api, mediaUrl, type AlertItem, type Summary, type TrapSummary } from "../api";
import { useLiveData } from "../settings";
import {
  ActionStrip, DecisionBadge, DetectorTag, EmptyState, ErrorState, SimulatedTag, Spinner, StatusDot,
  Tag, prettyPest, timeAgo,
} from "../components/ui";

interface OverviewData {
  summary: Summary;
  traps: TrapSummary[];
  alerts: AlertItem[];
}

const loadOverview = async (): Promise<OverviewData> => {
  const [summary, traps, alerts] = await Promise.all([api.summary(), api.traps(), api.alerts(6)]);
  return { summary, traps, alerts };
};

function Stat({ label, value, note }: { label: string; value: string | number; note?: string }) {
  return (
    <div className="card p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-stone-500 dark:text-stone-400">{label}</div>
      <div className="mt-1 text-2xl font-bold tabular-nums">{value}</div>
      {note && <div className="mt-0.5 text-xs text-stone-500 dark:text-stone-400">{note}</div>}
    </div>
  );
}

function TrapCard({ trap }: { trap: TrapSummary }) {
  const s = trap.latest_section;
  const d = trap.decision;
  const pest = prettyPest(trap.target_pest);
  return (
    <Link to={`/traps/${encodeURIComponent(trap.id)}`}
          className="card relative flex flex-col overflow-hidden pl-2 transition hover:shadow-md focus:outline-none focus:ring-2 focus:ring-leaf-600">
      <ActionStrip action={d.action} />
      <div className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h3 className="text-lg font-semibold">{trap.name}</h3>
            <p className="text-sm text-stone-500 dark:text-stone-400">{trap.location} · {trap.crop}</p>
          </div>
          <DecisionBadge action={d.action} />
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3">
          <div className="rounded-xl bg-stone-100 p-3 dark:bg-stone-800">
            <div className="flex items-center gap-1.5 text-xs text-stone-600 dark:text-stone-300">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: "var(--series-pest)" }} aria-hidden />
              Pests ({pest}) latest
            </div>
            <div className="text-2xl font-bold tabular-nums">{s ? s.pest_total : "–"}</div>
          </div>
          <div className="rounded-xl bg-stone-100 p-3 dark:bg-stone-800">
            <div className="flex items-center gap-1.5 text-xs text-stone-600 dark:text-stone-300">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: "var(--series-predator)" }} aria-hidden />
              Predators latest
            </div>
            <div className="text-2xl font-bold tabular-nums">{s ? s.predator_total : "–"}</div>
          </div>
        </div>

        <p className="mt-4 text-sm leading-relaxed text-stone-700 dark:text-stone-300">{d.reason}</p>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <StatusDot status={trap.status} />
          <span className="text-xs text-stone-500">· updated {timeAgo(trap.last_seen)}</span>
          {trap.latest_climate && (
            <span className="text-xs text-stone-500">· {trap.latest_climate.temperature_c} °C, {trap.latest_climate.humidity_pct}% RH</span>
          )}
          <span className="ml-auto flex gap-1.5">
            {(trap.simulated || s?.simulated) && <SimulatedTag />}
            {s && <DetectorTag mode={s.detector_mode} />}
          </span>
        </div>
      </div>
      {s?.annotated_url && (
        <img src={mediaUrl(s.annotated_url)} alt={`Latest tape section from ${trap.name}`}
             className="mt-auto h-28 w-full border-t border-stone-200 object-cover dark:border-stone-800" loading="lazy" />
      )}
    </Link>
  );
}

export default function Overview() {
  const { data, error, loading, reload, updatedAt } = useLiveData(loadOverview);

  if (loading && !data) return <Spinner label="Loading traps…" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  const { summary, traps, alerts } = data;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Trap overview</h1>
          <p className="text-sm text-stone-500 dark:text-stone-400">
            One recommendation per trap: spray, release biocontrol, or wait.
            {updatedAt && <> Refreshed {updatedAt.toLocaleTimeString()}.</>}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {summary.simulated_data && <SimulatedTag />}
          <DetectorTag mode={summary.detector_mode} />
          <Tag tone="stone" title="Telegram bot token in .env">
            Telegram: {summary.telegram_configured ? "on" : "log only"}
          </Tag>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
          Connection problem: {error.message} Showing the last data received.
        </div>
      )}

      <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Traps" value={summary.traps_total} note={`${summary.sections_total} tape sections analysed`} />
        <Stat label="Need action" value={summary.actions.SPRAY + summary.actions.RELEASE_BIOCONTROL}
              note={`${summary.actions.SPRAY} spray · ${summary.actions.RELEASE_BIOCONTROL} biocontrol`} />
        <Stat label="Pests today" value={summary.pests_today} note={`${summary.sections_today} section(s) today`} />
        <Stat label="Predators today" value={summary.predators_today} />
      </section>

      {traps.length === 0 ? (
        <EmptyState title="No traps configured">Add traps to config/traps.yaml and restart the backend.</EmptyState>
      ) : (
        <section className="grid gap-4 md:grid-cols-2">
          {traps.map((t) => <TrapCard key={t.id} trap={t} />)}
        </section>
      )}

      {summary.sections_total === 0 && (
        <EmptyState title="No tape sections yet">
          Load demo history with <code>python -m demo.seed</code>, or start the edge service with{" "}
          <code>python -m edge.main --demo</code>.
        </EmptyState>
      )}

      <section className="card p-5">
        <h2 className="font-semibold">Recent alerts</h2>
        <p className="text-xs text-stone-500 dark:text-stone-400">Sent to Telegram when a trap's recommendation changes (English + Kannada).</p>
        {alerts.length === 0 ? (
          <p className="mt-3 text-sm text-stone-500">No alerts yet.</p>
        ) : (
          <ul className="mt-3 divide-y divide-stone-100 dark:divide-stone-800">
            {alerts.map((a) => (
              <li key={a.id} className="flex flex-wrap items-start gap-3 py-2 text-sm">
                <DecisionBadge action={a.action} />
                <span className="text-stone-500">{a.trap_id} · {a.language.toUpperCase()} · {timeAgo(a.timestamp)}</span>
                <Tag tone="stone">{a.status === "logged" ? "logged (no Telegram token)" : a.status}</Tag>
                <details className="w-full text-stone-600 dark:text-stone-300">
                  <summary className="cursor-pointer text-xs">Message</summary>
                  <pre className="mt-1 whitespace-pre-wrap font-sans text-sm">{a.message}</pre>
                </details>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
