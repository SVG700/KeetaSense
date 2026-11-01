// F4: record what the farmer did (same as the Telegram alert buttons) + before/after effect card.
import { useState } from "react";
import { api, type ActionRow, type FarmerAction } from "../api";
import { useT } from "../i18n";
import { SimulatedTag } from "./ui";

const ICON: Record<FarmerAction, string> = { sprayed: "✅", released: "🐞", not_yet: "⏳" };

function EffectCard({ a }: { a: ActionRow }) {
  const t = useT();
  const e = a.effect;
  if (!e) return null;
  const change = e.change_pct == null ? "–" : `${e.change_pct > 0 ? "+" : ""}${e.change_pct}%`;
  return (
    <div className="rounded-xl bg-stone-100 p-3 text-sm dark:bg-stone-800">
      <div className="mb-1 flex flex-wrap items-center gap-2 font-medium">
        {t("effect.title", { action: t(`actions.${a.action}`).toLowerCase() })}
        <span className="text-xs font-normal text-stone-500">{new Date(a.timestamp).toLocaleDateString()}</span>
        {a.simulated && <SimulatedTag />}
      </div>
      {e.status === "ok" && (
        <p className="tabular-nums">{t("effect.values", { before: e.before_avg ?? "–", after: e.after_avg ?? "–", days: e.days, change })}</p>
      )}
      {e.status === "waiting_for_data" && <p>{t("effect.waiting", { n: e.n_after, days: e.days })}</p>}
      {e.status === "no_data_before" && <p>{t("effect.no_before")}</p>}
      <p className="mt-1 text-xs text-stone-500">{t("effect.note")}</p>
    </div>
  );
}

export default function ActionPanel({ trapId, actions, onChanged }: { trapId: string; actions: ActionRow[]; onChanged: () => void }) {
  const t = useT();
  const [quantity, setQuantity] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function save(action: FarmerAction) {
    setBusy(true);
    setMessage(null);
    try {
      const q = quantity.trim() === "" ? undefined : Number(quantity);
      const r = await api.postAction(trapId, { action, quantity: q, note });
      setMessage(t("actions.saved") + (r.cooldown_until ? " " + t("actions.cooldown", { until: new Date(r.cooldown_until).toLocaleString() }) : ""));
      setQuantity("");
      setNote("");
      onChanged();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const lastTreatment = [...actions].reverse().find((a) => a.action !== "not_yet");
  const badQty = quantity.trim() !== "" && (!Number.isFinite(Number(quantity)) || Number(quantity) < 0);

  return (
    <section className="card space-y-3 p-5">
      <h2 className="font-semibold">{t("actions.title")}</h2>
      <p className="text-xs text-stone-500 dark:text-stone-400">{t("actions.help")}</p>
      <div className="flex flex-wrap gap-2">
        {(["sprayed", "released", "not_yet"] as FarmerAction[]).map((a) => (
          <button key={a} disabled={busy || badQty} onClick={() => save(a)}
                  className="rounded-lg border border-stone-300 px-3 py-1.5 text-sm font-medium hover:bg-stone-100 disabled:opacity-50 dark:border-stone-700 dark:hover:bg-stone-800">
            {ICON[a]} {t(`actions.${a}`)}
          </button>
        ))}
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="text-xs">
          {t("actions.quantity")}
          <input value={quantity} onChange={(e) => setQuantity(e.target.value)} inputMode="decimal" aria-invalid={badQty}
                 className={`mt-1 block w-full rounded border bg-white px-2 py-1 text-sm dark:bg-stone-900 ${badQty ? "border-red-500" : "border-stone-300 dark:border-stone-700"}`} />
        </label>
        <label className="text-xs">
          {t("actions.note")}
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500}
                 className="mt-1 block w-full rounded border border-stone-300 bg-white px-2 py-1 text-sm dark:border-stone-700 dark:bg-stone-900" />
        </label>
      </div>
      {message && <p className="text-sm" role="status">{message}</p>}

      {lastTreatment && <EffectCard a={lastTreatment} />}

      <div>
        <h3 className="text-sm font-medium">{t("actions.recent")}</h3>
        {actions.length === 0 ? (
          <p className="text-sm text-stone-500">{t("actions.none")}</p>
        ) : (
          <ul className="mt-1 space-y-1 text-sm">
            {[...actions].reverse().slice(0, 5).map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-2">
                <span>{ICON[a.action]} {t(`actions.${a.action}`)}{a.quantity != null ? ` · ${a.quantity}` : ""}</span>
                <span className="text-xs text-stone-500">{new Date(a.timestamp).toLocaleString()} · {t(`actions.source.${a.source}`)}</span>
                {a.note && <span className="text-xs italic text-stone-500">“{a.note}”</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
