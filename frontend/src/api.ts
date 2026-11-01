// Talking to the KeetaSense backend.
// Every function throws an ApiError with a friendly message if something goes wrong.

// Default: the same machine that served this page, port 8000. That works for the Vite dev
// server, for the dashboard served by the backend itself, and for a phone on the same Wi-Fi.
export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  `${window.location.protocol}//${window.location.hostname === "localhost" ? "127.0.0.1" : window.location.hostname}:8000`;

export type Action = "SPRAY" | "RELEASE_BIOCONTROL" | "WAIT" | "CHECK_TRAP";
export type QualityStatus = "OK" | "WARN" | "BAD";

export interface QualityReason {
  code: "blurred" | "too_dark" | "too_bright" | "glare" | "tape_not_advanced";
  level: QualityStatus;
  value: number;
  limit: number;
}

export interface QualityMetrics {
  width?: number;
  height?: number;
  blur?: number;
  brightness?: number;
  glare_pct?: number;
  similarity_to_previous?: number | null;
}
export type DetectorMode = "yolo_sahi" | "demo_detector";

export interface DetectorInfo {
  mode: DetectorMode;
  label: string; // "Demo detector (synthetic only)" or "AI model: best.pt, trained 2026-11-02"
  reason: string | null;
  weights_name: string | null;
  weights_path: string;
  trained_at: string | null;
  trained_at_source: string | null;
  synthetic_data: boolean | null;
  classes: string[] | null;
  load_error: string | null;
}

export interface ClassMetrics {
  category: string;
  ground_truth: number;
  predictions: number;
  true_positives: number;
  precision: number | null;
  recall: number | null;
  ap50: number | null;
}

export interface CountingError {
  mae: number;
  mape_percent: number | null;
  images_used_for_mape: number;
  mean_true_count: number;
}

export interface EvalReport {
  name: string;
  file: string;
  created: string | null;
  dataset: string | null;
  synthetic_data: boolean;
  detector_mode: DetectorMode | null;
  weights: string | null;
  test_images: number | null;
  iou_threshold: number | null;
  confidence_threshold: number | null;
  map50: number | null;
  per_class: Record<string, ClassMetrics>;
  counting_error: Record<string, CountingError>;
}

export interface ModelPageData {
  detector: DetectorInfo;
  featured: EvalReport | null;
  reports: EvalReport[];
  warning: string | null;
}

export interface ThresholdField {
  label: string;
  unit: string;
  type: "float" | "int";
  min: number;
  min_exclusive: boolean;
  max: number;
  help: string;
  value: number;
  status: "placeholder" | "confirmed" | "unmarked";
  confirmed_on: string | null;
}

export interface ThresholdsPage {
  pests: Record<string, Record<string, ThresholdField>>;
  backups: string[];
  file: string;
}

export interface SaveThresholdsResult {
  pest: string;
  changed: string[];
  confirmed_unchanged: string[];
  backup: string | null;
  decisions: Record<string, Action>;
}

export interface DegreeDays {
  accumulated: number;
  generations_completed: number;
  progress_dd: number;
  progress_fraction: number;
  dd_remaining: number;
  avg_daily_dd: number | null;
  days_to_next_generation: number | null;
  days_of_data: number;
}

export interface Decision {
  action: Action;
  underlying_action?: Action; // what the counts say when the action is CHECK_TRAP
  quality?: { status: QualityStatus; reasons: QualityReason[]; section_id: number } | null;
  reason: string;
  pests_per_day: number;
  predators_per_day: number;
  ratio: number | null;
  window_days_used: number;
  degree_days: DegreeDays;
}

export interface Section {
  id: number;
  trap_id: string;
  timestamp: string;
  counts: Record<string, number>;
  pest_total: number;
  predator_total: number;
  image_url: string | null;
  annotated_url: string | null;
  detector_mode: DetectorMode;
  simulated: boolean;
  source: "live" | "mock" | "replay" | "seed" | "upload";
  quality_status: QualityStatus | null;
  quality_reasons: QualityReason[];
  quality_metrics: QualityMetrics;
  corrected: boolean;                      // F3: a scout corrected the boxes
  corrected_counts: Record<string, number> | null;
  corrected_pest_total: number | null;
  corrected_predator_total: number | null;
  effective_pest_total: number;            // corrected if corrected, else the model's count
  effective_predator_total: number;
}

export interface Box {
  id: string;                              // "m3" model box, "c12" added by correction 12
  class_name: string;
  category: "pest" | "predator" | "unknown";
  confidence: number | null;
  bbox: [number, number, number, number];
  source: "model" | "scout";
  relabelled_from?: string;
}

export interface CorrectionRow {
  id: number;
  action: "add" | "remove" | "relabel";
  class_name: string | null;
  bbox: number[] | null;
  target: string | null;
  author: string;
  created_at: string;
}

export interface SectionDetail extends Section {
  image_width: number;
  image_height: number;
  boxes: Box[];
  corrections: CorrectionRow[];
}

export interface CorrectionStats {
  captures: number;
  corrected_captures: number;
  correction_rate: number;
  pest_mae: number | null;
  predator_mae: number | null;
  per_class_mae: Record<string, number>;
  simulated_captures?: number;
  label: string;
}

export interface Thresholds {
  base_temp_c: number;
  degree_days_per_generation: number;
  action_threshold_per_day: number;
  spray_ratio: number;
  rolling_window_days: number;
}

export interface TrapSummary {
  id: string;
  name: string;
  location: string;
  crop: string;
  target_pest: string;
  simulated: boolean;
  status: "online" | "offline" | "no_data";
  last_seen: string | null;
  latest_section: Section | null;
  latest_climate: { timestamp: string; temperature_c: number; humidity_pct: number } | null;
  decision: Decision;
  thresholds: Thresholds;
}

export interface ClimateDay {
  date: string;
  tmin: number;
  tmax: number;
  humidity_avg: number;
  degree_days: number;
  readings: number;
  simulated: boolean;
}

export type FarmerAction = "sprayed" | "released" | "not_yet";

export interface ActionEffect {
  before_avg: number | null;
  after_avg: number | null;
  change_pct: number | null;
  n_before: number;
  n_after: number;
  days: number;
  status: "ok" | "waiting_for_data" | "no_data_before";
}

export interface ActionRow {
  id: number;
  trap_id: string;
  action: FarmerAction;
  quantity: number | null;
  note: string;
  timestamp: string;
  source: "dashboard" | "telegram" | "seed";
  alert_id: number | null;
  simulated: boolean;
  effect: ActionEffect | null;
}

export interface TrapHistory {
  trap: TrapSummary;
  sections: Section[];
  climate_daily: ClimateDay[];
  decisions: { timestamp: string; action: Action; reason: string }[];
  actions: ActionRow[];
}

export interface Summary {
  traps_total: number;
  actions: Record<Action, number>;
  pests_today: number;
  predators_today: number;
  sections_today: number;
  sections_total: number;
  last_update: string | null;
  simulated_data: boolean;
  detector_mode: DetectorMode;
  detector: DetectorInfo;
  telegram_configured: boolean;
  alerts_total: number;
}

export interface AlertItem {
  id: number;
  trap_id: string;
  timestamp: string;
  action: Action;
  previous_action: Action | null;
  language: string;
  message: string;
  status: string;
}

export interface PhoneCheckResult {
  counts: Record<string, number>;
  pest_total: number;
  predator_total: number;
  days_exposed: number;
  annotated_url: string;
  detector_mode: DetectorMode;
  detector: DetectorInfo;
  warning: string | null;
  decision: Decision;
}

export class ApiError extends Error {
  offline: boolean; // true = the backend could not be reached at all
  errors?: Record<string, string>; // per-field validation errors (Settings page)
  constructor(message: string, offline = false, errors?: Record<string, string>) {
    super(message);
    this.offline = offline;
    this.errors = errors;
  }
}

export const correctionsExportUrl = () => `${API_BASE}/api/corrections/export.zip`;

/** Full URL for an image path returned by the backend, e.g. "/media/annotated/x.jpg". */
export const mediaUrl = (path: string | null | undefined) => (path ? `${API_BASE}${path}` : "");

async function request<T>(path: string, init?: RequestInit, timeoutMs = 15000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}${path}`, { ...init, signal: controller.signal });
  } catch {
    throw new ApiError(`Cannot reach the KeetaSense backend at ${API_BASE}.`, true);
  } finally {
    clearTimeout(timer);
  }
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    let fieldErrors: Record<string, string> | undefined;
    try {
      const body = await resp.json();
      if (body?.detail?.errors) {
        fieldErrors = body.detail.errors;
        detail = Object.values(fieldErrors!).join(" ");
      } else if (body?.detail) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      /* body was not JSON - keep the status text */
    }
    throw new ApiError(detail, false, fieldErrors);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; detector_mode: DetectorMode; detector: DetectorInfo }>("/api/health"),
  model: () => request<ModelPageData>("/api/model"),
  summary: () => request<Summary>("/api/summary"),
  traps: () => request<TrapSummary[]>("/api/traps"),
  history: (id: string, days = 30) => request<TrapHistory>(`/api/traps/${encodeURIComponent(id)}/history?days=${days}`),
  alerts: (limit = 8) => request<AlertItem[]>(`/api/alerts?limit=${limit}`),
  thresholds: () => request<ThresholdsPage>("/api/settings/thresholds"),
  saveThresholds: (pest: string, values: Record<string, number>, confirmUnchanged: boolean) =>
    request<SaveThresholdsResult>(`/api/settings/thresholds/${encodeURIComponent(pest)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values, confirm_unchanged: confirmUnchanged }),
    }),
  section: (id: number) => request<SectionDetail>(`/api/sections/${id}`),
  addCorrection: (id: number, body: { action: "add" | "remove" | "relabel"; target?: string; class_name?: string; bbox?: number[] }) =>
    request<{ section: SectionDetail; decision: Decision }>(`/api/sections/${id}/corrections`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
  undoCorrection: (id: number) =>
    request<{ section: SectionDetail; decision: Decision }>(`/api/corrections/${id}`, { method: "DELETE" }),
  correctionStats: () => request<CorrectionStats>("/api/corrections/stats"),
  actions: (trapId: string) =>
    request<{ actions: ActionRow[]; cooldown_until: string | null }>(`/api/traps/${encodeURIComponent(trapId)}/actions`),
  postAction: (trapId: string, body: { action: FarmerAction; quantity?: number; note?: string }) =>
    request<{ action: ActionRow; cooldown_until: string | null }>(`/api/traps/${encodeURIComponent(trapId)}/actions`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...body, source: "dashboard" }),
    }),
  resetDemo: () =>
    request<{ removed: Record<string, number>; sections_created: number; seconds: number }>(
      "/api/reset-demo", { method: "POST" }, 120000),
  phoneCheck: (file: File, daysExposed: number) => {
    const form = new FormData();
    form.append("image", file);
    form.append("days_exposed", String(daysExposed));
    // detection on a big photo can take a while on a laptop CPU
    return request<PhoneCheckResult>("/api/phone-check", { method: "POST", body: form }, 120000);
  },
};
