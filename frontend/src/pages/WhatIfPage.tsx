// F5 What-if simulator: move the sliders, see what KeetaSense would advise.
// Calls POST /api/decision/simulate - the SAME function as the live engine, and nothing is stored.
import { useEffect, useState } from "react";
import { api, type Decision } from "../api";
import { useT } from "../i18n";
import { BorderlineTag, DecisionBadge, ErrorState, prettyPest } from "../components/ui";

type SimResult = Awaited<ReturnType<typeof api.simulate>>;

function Slider({ label, value, min, max, step = 1, unit, onChange }: {
  label: string; value: number; min: number; max: number; step?: number; unit: string; onChange: (v: number) => void;
}) {
  return (
    <label className="block">
      <span className="flex justify-between text-sm"><span>{label}</span><span className="font-semibold tabular-nums">{value} {unit}</span></span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))}
             className="mt-1 w-full accent-leaf-700" />
    </label>
  );
}

export default function WhatIfPage() {
  const t = useT();
  const [crop, setCrop] = useState("tomato");
  const [temp, setTemp] = useState(26);
  const [pests, setPests] = useState(30);
  const [predators, setPredators] = useState(2);
  const [useConf, setUseConf] = useState(false);
  const [conf, setConf] = useState(80);
  const [result, setResult] = useState<SimResult | null>(null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    const id = window.setTimeout(() => {   // small delay so dragging a slider does not flood the backend
      api.simulate({ crop, temperature_c: temp, days: 14, pests_per_day: pests, predators_per_day: predators,
                     pest_confidence: useConf ? conf / 100 : undefined, predator_confidence: useConf ? conf / 100 : undefined })
        .then((r) => { setResult(r); setError(null); })
        .catch((e: Error) => setError(e));
    }, 150);
    return () => window.clearTimeout(id);
  }, [crop, temp, pests, predators, useConf, conf]);

  const d: Decision | undefined = result?.decision;
  const crops = result ? Object.keys(result.crops) : [crop];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold tracking-tight">{t("whatif.title")}</h1>
        <span className="rounded-md border-2 border-dashed border-sky-500 bg-sky-50 px-3 py-1 text-sm font-bold tracking-wide text-sky-900 dark:bg-sky-950 dark:text-sky-200">
          ◇ {t("whatif.badge")}
        </span>
      </div>
      <p className="text-sm text-stone-500 dark:text-stone-400">{t("whatif.help")}</p>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="card space-y-4 p-5">
          <label className="block text-sm">
            {t("whatif.crop")}
            <select value={crop} onChange={(e) => setCrop(e.target.value)}
                    className="mt-1 block w-full rounded-lg border border-stone-300 bg-white px-3 py-2 dark:border-stone-700 dark:bg-stone-900">
              {crops.map((c) => <option key={c} value={c}>{prettyPest(c)}</option>)}
            </select>
          </label>
          <Slider label={t("whatif.temperature")} value={temp} min={10} max={40} unit="°C" onChange={setTemp} />
          <Slider label={t("whatif.pests")} value={pests} min={0} max={150} unit="/day" onChange={setPests} />
          <Slider label={t("whatif.predators")} value={predators} min={0} max={30} unit="/day" onChange={setPredators} />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={useConf} onChange={(e) => setUseConf(e.target.checked)} />
            {t("whatif.use_conf")}
          </label>
          {useConf && <Slider label={t("whatif.confidence")} value={conf} min={50} max={100} unit="%" onChange={setConf} />}
          <p className="text-xs text-stone-500">{t("whatif.temp_note")}</p>
        </section>

        <section className="card space-y-3 border-2 border-dashed border-sky-400 p-5 dark:border-sky-700">
          <p className="text-xs font-bold uppercase tracking-wide text-sky-800 dark:text-sky-300">◇ {t("whatif.badge")}</p>
          {error && <ErrorState error={error} />}
          {d && (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <DecisionBadge action={d.action} size="lg" />
                <BorderlineTag decision={d} pest={result!.target_pest} />
              </div>
              <p className="leading-relaxed">{d.reason}</p>
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div><dt className="text-stone-500">{t("whatif.ratio")}</dt><dd className="text-lg font-semibold tabular-nums">{d.ratio?.toFixed(1) ?? "–"}</dd></div>
                <div><dt className="text-stone-500">{t("whatif.threshold")}</dt><dd className="text-lg font-semibold tabular-nums">{result!.thresholds.action_threshold_per_day} /day</dd></div>
                <div><dt className="text-stone-500">{t("whatif.dd")}</dt><dd className="text-lg font-semibold tabular-nums">{d.degree_days.accumulated}</dd></div>
                <div><dt className="text-stone-500">{t("whatif.next_gen")}</dt><dd className="text-lg font-semibold tabular-nums">{d.degree_days.days_to_next_generation ?? "–"}</dd></div>
              </dl>
              {d.support?.predators_at_risk != null && d.support.predators_at_risk > 0 && (
                <p className="rounded-lg bg-stone-100 p-3 text-sm dark:bg-stone-800">{t("whatif.harm", { n: d.support.predators_at_risk })}</p>
              )}
              {d.support?.release_count != null && (
                <p className="rounded-lg bg-stone-100 p-3 text-sm dark:bg-stone-800">
                  {t("whatif.release", { n: d.support.release_count, predator: prettyPest(d.support.release_class ?? ""),
                                         date: d.support.recheck_date ? new Date(d.support.recheck_date).toLocaleDateString() : "–" })}
                </p>
              )}
              <p className="text-xs text-stone-500">{t("whatif.placeholder_note")}</p>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
