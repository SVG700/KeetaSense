// Small reusable UI pieces: decision badge, labels, error and empty states.
import type { ReactNode } from "react";
import { ApiError, type Action, type DetectorMode } from "../api";

/** Traffic light for a decision. Colour is never alone: always icon + words. */
export const ACTION_INFO: Record<Action, { label: string; icon: string; color: string; hint: string }> = {
  SPRAY: { label: "Spray", icon: "▲", color: "var(--status-critical)", hint: "Pests high, predators not keeping pace" },
  RELEASE_BIOCONTROL: { label: "Release biocontrol", icon: "◆", color: "var(--status-warning)", hint: "Pests high, predators keeping pace" },
  WAIT: { label: "Wait", icon: "●", color: "var(--status-good)", hint: "Below the action threshold" },
};

export function DecisionBadge({ action, size = "md" }: { action: Action; size?: "md" | "lg" }) {
  const info = ACTION_INFO[action];
  const big = size === "lg";
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full border font-semibold ${big ? "px-4 py-1.5 text-base" : "px-3 py-1 text-sm"}`}
      style={{ borderColor: info.color, color: "inherit", background: `color-mix(in srgb, ${info.color} 14%, transparent)` }}
      title={info.hint}
    >
      <span aria-hidden style={{ color: info.color }}>{info.icon}</span>
      {info.label.toUpperCase()}
    </span>
  );
}

/** Coloured strip down the side of a card: the "traffic light". */
export function ActionStrip({ action }: { action: Action }) {
  return <div className="absolute inset-y-0 left-0 w-1.5 rounded-l-2xl" style={{ background: ACTION_INFO[action].color }} aria-hidden />;
}

export function Tag({ children, tone = "amber", title }: { children: ReactNode; tone?: "amber" | "stone" | "green"; title?: string }) {
  const tones = {
    amber: "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200",
    stone: "border-stone-300 bg-stone-100 text-stone-700 dark:border-stone-700 dark:bg-stone-800 dark:text-stone-300",
    green: "border-leaf-600/40 bg-leaf-50 text-leaf-800 dark:border-leaf-700 dark:bg-leaf-900/40 dark:text-leaf-100",
  };
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

export const SimulatedTag = () => (
  <Tag title="This data comes from demo/seed.py or mock hardware, not a real trap">⚗ Simulated data</Tag>
);

export function DetectorTag({ mode }: { mode: DetectorMode | undefined }) {
  if (mode === "demo_detector")
    return <Tag title="No trained model weights yet: counts come from simple blob counting, not the AI model">⚠ Demo detector</Tag>;
  if (mode === "yolo_sahi") return <Tag tone="green" title="Fine-tuned YOLOv8n with SAHI sliced inference">AI model (YOLOv8 + SAHI)</Tag>;
  return null;
}

export function StatusDot({ status }: { status: "online" | "offline" | "no_data" }) {
  const map = {
    online: { c: "bg-leaf-500", t: "Online" },
    offline: { c: "bg-stone-400", t: "Offline" },
    no_data: { c: "bg-stone-300 dark:bg-stone-600", t: "No data yet" },
  };
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-stone-500 dark:text-stone-400">
      <span className={`h-2 w-2 rounded-full ${map[status].c}`} aria-hidden />
      {map[status].t}
    </span>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-16 text-stone-500" role="status">
      <span className="h-5 w-5 animate-spin rounded-full border-2 border-leaf-600 border-t-transparent" />
      {label}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const offline = error instanceof ApiError && error.offline;
  return (
    <div className="card mx-auto max-w-xl p-6 text-center">
      <div className="mb-2 text-3xl" aria-hidden>{offline ? "🔌" : "⚠️"}</div>
      <h2 className="text-lg font-semibold">{offline ? "Backend not reachable" : "Something went wrong"}</h2>
      <p className="mt-2 text-sm text-stone-600 dark:text-stone-400">{error.message}</p>
      {offline && (
        <p className="mt-3 text-sm text-stone-600 dark:text-stone-400">
          Start it with <code className="rounded bg-stone-100 px-1 dark:bg-stone-800">scripts\start.bat</code> (Windows) or{" "}
          <code className="rounded bg-stone-100 px-1 dark:bg-stone-800">scripts/start.sh</code>, then retry.
        </p>
      )}
      {onRetry && (
        <button onClick={onRetry} className="mt-4 rounded-lg bg-leaf-700 px-4 py-2 text-sm font-medium text-white hover:bg-leaf-800">
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-stone-300 p-8 text-center dark:border-stone-700">
      <div className="mb-2 text-3xl" aria-hidden>🟨</div>
      <h3 className="font-semibold">{title}</h3>
      {children && <div className="mt-2 text-sm text-stone-600 dark:text-stone-400">{children}</div>}
    </div>
  );
}

/** "5 min ago" style text for timestamps from the backend (local time). */
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "never";
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return `${Math.floor(seconds / 86400)} days ago`;
}

export const prettyPest = (name: string) => name.charAt(0).toUpperCase() + name.slice(1);
