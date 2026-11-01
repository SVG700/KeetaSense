// F6: trap health from the heartbeat - online/offline, tape left, upload queue, motor fault.
import type { TrapHealth } from "../api";
import { useT } from "../i18n";
import { SimulatedTag, Tag, timeAgo } from "./ui";

/** Small badge for the overview card: only shown when something is wrong. */
export function HealthBadge({ health }: { health: TrapHealth | undefined }) {
  const t = useT();
  if (!health?.known || health.problems.length === 0) return null;
  return (
    <Tag tone="stone" title={health.problems.map((p) => t(`health.problem.${p}`)).join(", ")}>
      🩺 {health.problems.map((p) => t(`health.problem.${p}`)).join(" · ")}
    </Tag>
  );
}

function Row({ label, value, bad }: { label: string; value: string; bad?: boolean }) {
  return (
    <div className="flex justify-between gap-3 py-1">
      <dt className="text-stone-500">{label}</dt>
      <dd className={`tabular-nums font-medium ${bad ? "text-red-700 dark:text-red-400" : ""}`}>{value}</dd>
    </div>
  );
}

export default function HealthCard({ health }: { health: TrapHealth | undefined }) {
  const t = useT();
  return (
    <section className="card p-5">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="font-semibold">{t("health.title")}</h2>
        {health?.simulated && <SimulatedTag />}
      </div>
      {!health?.known ? (
        <p className="text-sm text-stone-500">{t("health.none")}</p>
      ) : (
        <>
          <dl className="divide-y divide-stone-100 text-sm dark:divide-stone-800">
            <Row label={t("health.state")} bad={!health.online}
                 value={health.online ? t("health.online") : t("health.offline", { min: health.offline_minutes ?? 0 })} />
            <Row label={t("health.last_seen")} value={timeAgo(health.last_seen)} />
            <Row label={t("health.tape")} bad={health.problems.includes("TAPE_LOW")}
                 value={health.tape_remaining_pct == null ? "–" : `${health.tape_remaining_pct}%`} />
            <Row label={t("health.queue")} bad={(health.queue_depth ?? 0) > 0} value={String(health.queue_depth ?? 0)} />
            <Row label={t("health.motor")} bad={!!health.motor_fault}
                 value={health.motor_fault ? `${t("health.fault")}${health.motor_fault_detail ? `: ${health.motor_fault_detail}` : ""}` : t("health.ok")} />
          </dl>
          {health.tape_remaining_pct != null && (
            <div className="mt-3 h-2 overflow-hidden rounded bg-stone-200 dark:bg-stone-800" aria-hidden>
              <div className={`h-full ${health.problems.includes("TAPE_LOW") ? "bg-red-600" : "bg-leaf-600"}`}
                   style={{ width: `${Math.max(0, Math.min(100, health.tape_remaining_pct))}%` }} />
            </div>
          )}
          <p className="mt-3 text-xs text-stone-500">{t("health.note", { min: health.offline_limit_minutes ?? 0, n: health.offline_after_intervals ?? "–",
                                                             pct: health.tape_low_pct ?? "–" })}</p>
        </>
      )}
    </section>
  );
}
