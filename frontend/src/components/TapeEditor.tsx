// F3: the latest tape photo with its boxes, and an "Edit counts" mode for scouts.
// Click a box -> delete it or change its class. Drag on the photo -> add a missed insect.
// Every edit is saved at once; the backend recomputes the counts and the decision.
import { useCallback, useEffect, useRef, useState, type PointerEvent } from "react";
import { api, mediaUrl, type Box, type SectionDetail } from "../api";
import { useT } from "../i18n";
import { prettyPest, Tag } from "./ui";

const STROKE = { pest: "#d03b3b", predator: "#0ca30c", unknown: "#8a8984" };

export default function TapeEditor({ sectionId, onChanged }: { sectionId: number; onChanged: () => void }) {
  const t = useT();
  const [data, setData] = useState<SectionDetail | null>(null);
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [newClass, setNewClass] = useState("whitefly");
  const [draft, setDraft] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const load = useCallback(() => {
    api.section(sectionId).then(setData).catch((e: Error) => setError(e.message));
  }, [sectionId]);
  useEffect(load, [load]);

  async function save(body: Parameters<typeof api.addCorrection>[1]) {
    setBusy(true);
    setError(null);
    try {
      const r = await api.addCorrection(sectionId, body);
      setData(r.section);
      setSelected(null);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function undo(id: number) {
    setBusy(true);
    try {
      setData((await api.undoCorrection(id)).section);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // screen point -> photo pixel coordinates
  function toPhoto(e: PointerEvent<SVGSVGElement>) {
    const svg = svgRef.current!;
    const r = svg.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * data!.image_width, y: ((e.clientY - r.top) / r.height) * data!.image_height };
  }

  if (error && !data) return <p className="text-sm text-red-700 dark:text-red-400">{error}</p>;
  if (!data) return <p className="text-sm text-stone-500">…</p>;
  const classes = Object.keys(data.counts);
  const sel = data.boxes.find((b) => b.id === selected) ?? null;
  const w = data.image_width || 1;
  const h = data.image_height || 1;
  const thin = Math.max(1.5, w / 600);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium tabular-nums">
          {t("edit.counts", { pests: data.effective_pest_total, predators: data.effective_predator_total })}
        </span>
        {data.corrected && <Tag tone="green">✎ {t("edit.corrected")}</Tag>}
        {data.corrected && (
          <span className="text-xs text-stone-500">{t("edit.model_counts", { pests: data.pest_total, predators: data.predator_total })}</span>
        )}
        <button onClick={() => { setEditing(!editing); setSelected(null); setDraft(null); }}
                className={`ml-auto rounded-lg px-3 py-1.5 text-sm font-medium ${editing ? "bg-leaf-700 text-white" : "border border-stone-300 dark:border-stone-700"}`}>
          {editing ? t("edit.done") : `✎ ${t("edit.button")}`}
        </button>
      </div>

      {editing && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg bg-stone-100 p-3 text-sm dark:bg-stone-800">
          <span className="w-full text-xs text-stone-600 dark:text-stone-300">{t("edit.help")}</span>
          <label className="flex items-center gap-2">
            {t("edit.new_class")}
            <select value={newClass} onChange={(e) => setNewClass(e.target.value)}
                    className="rounded border border-stone-300 bg-white px-2 py-1 dark:border-stone-600 dark:bg-stone-900">
              {classes.map((c) => <option key={c} value={c}>{prettyPest(c)}</option>)}
            </select>
          </label>
          {sel && (
            <span className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{t("edit.selected")}: {prettyPest(sel.class_name)}</span>
              <select defaultValue="" disabled={busy}
                      onChange={(e) => e.target.value && save({ action: "relabel", target: sel.id, class_name: e.target.value })}
                      className="rounded border border-stone-300 bg-white px-2 py-1 dark:border-stone-600 dark:bg-stone-900"
                      aria-label={t("edit.relabel")}>
                <option value="">{t("edit.relabel")}…</option>
                {classes.filter((c) => c !== sel.class_name).map((c) => <option key={c} value={c}>{prettyPest(c)}</option>)}
              </select>
              <button disabled={busy} onClick={() => save({ action: "remove", target: sel.id })}
                      className="rounded bg-red-700 px-2.5 py-1 text-white hover:bg-red-800">{t("edit.delete")}</button>
            </span>
          )}
        </div>
      )}
      {error && <p className="text-sm text-red-700 dark:text-red-400" role="alert">{error}</p>}

      <div className="relative">
        <img src={mediaUrl(data.image_url)} alt="Tape section" className="w-full rounded-xl border border-stone-200 dark:border-stone-800" />
        <svg ref={svgRef} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none"
             className={`absolute inset-0 h-full w-full rounded-xl ${editing ? "cursor-crosshair" : "pointer-events-none"}`}
             onPointerDown={(e) => { if (!editing) return; const p = toPhoto(e); setDraft({ x1: p.x, y1: p.y, x2: p.x, y2: p.y }); (e.target as Element).setPointerCapture?.(e.pointerId); }}
             onPointerMove={(e) => { if (draft) { const p = toPhoto(e); setDraft({ ...draft, x2: p.x, y2: p.y }); } }}
             onPointerUp={() => {
               if (!draft) return;
               const box = [Math.min(draft.x1, draft.x2), Math.min(draft.y1, draft.y2), Math.max(draft.x1, draft.x2), Math.max(draft.y1, draft.y2)];
               setDraft(null);
               if (box[2] - box[0] >= 4 && box[3] - box[1] >= 4) save({ action: "add", class_name: newClass, bbox: box });
             }}>
          {data.boxes.map((b: Box) => (
            <rect key={b.id} x={b.bbox[0]} y={b.bbox[1]} width={b.bbox[2] - b.bbox[0]} height={b.bbox[3] - b.bbox[1]}
                  fill={b.id === selected ? "rgba(250,178,25,0.25)" : "transparent"}
                  stroke={STROKE[b.category] ?? STROKE.unknown} strokeWidth={b.id === selected ? thin * 2.5 : thin}
                  strokeDasharray={b.source === "scout" ? `${thin * 3} ${thin * 2}` : undefined}
                  style={{ pointerEvents: editing ? "all" : "none", cursor: "pointer" }}
                  onPointerDown={(e) => { e.stopPropagation(); setSelected(b.id === selected ? null : b.id); }}>
              <title>{prettyPest(b.class_name)}{b.confidence != null ? ` (${Math.round(b.confidence * 100)}%)` : ""}{b.source === "scout" ? " - scout" : ""}</title>
            </rect>
          ))}
          {draft && (
            <rect x={Math.min(draft.x1, draft.x2)} y={Math.min(draft.y1, draft.y2)} width={Math.abs(draft.x2 - draft.x1)}
                  height={Math.abs(draft.y2 - draft.y1)} fill="rgba(250,178,25,0.2)" stroke="#fab219" strokeWidth={thin * 2} />
          )}
        </svg>
      </div>

      {data.corrected && <p className="text-xs text-stone-500">{t("edit.decision_note")}</p>}
      {data.corrections.length > 0 && (
        <details className="text-sm" open={editing}>
          <summary className="cursor-pointer text-xs font-medium">{t("edit.history")} ({data.corrections.length})</summary>
          <ul className="mt-1 space-y-1">
            {data.corrections.slice(-8).reverse().map((c) => (
              <li key={c.id} className="flex items-center gap-2 text-xs text-stone-600 dark:text-stone-300">
                <span>{t(`edit.action.${c.action}`)}: {c.class_name ? prettyPest(c.class_name) : ""} {c.target ? `(${c.target})` : ""}</span>
                <span className="text-stone-400">{new Date(c.created_at).toLocaleTimeString()}</span>
                <button disabled={busy} onClick={() => undo(c.id)} className="ml-auto underline">{t("edit.undo")}</button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
