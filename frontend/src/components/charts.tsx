// Charts for the trap detail page (Recharts).
// - CountsChart: pests vs predators per tape section (= per day), with the action threshold
// - DegreeDayChart: daily degree-days (warmth that drives insect development)
// - DegreeDayMeter: progress toward the next pest generation
import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { ClimateDay, DegreeDays, Section } from "../api";

const axisProps = {
  stroke: "var(--chart-axis)",
  tick: { fill: "var(--chart-axis)", fontSize: 12 },
  tickLine: false,
  axisLine: { stroke: "var(--chart-grid)" },
};

/** Label each section by date; add the time when several sections share a day (demo mode). */
function sectionLabels(sections: Section[]): string[] {
  const perDay: Record<string, number> = {};
  sections.forEach((s) => (perDay[s.timestamp.slice(0, 10)] = (perDay[s.timestamp.slice(0, 10)] || 0) + 1));
  return sections.map((s) => {
    const d = new Date(s.timestamp);
    const day = d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
    return perDay[s.timestamp.slice(0, 10)] > 1
      ? `${day} ${d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`
      : day;
  });
}

interface TipProps {
  active?: boolean;
  label?: string | number;
  payload?: { name?: string; value?: number | string; color?: string }[];
  unit?: string;
}

/** Tooltip: values in normal text colour, a small coloured key carries identity. */
function ChartTooltip({ active, payload, label, unit = "" }: TipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm shadow-md dark:border-stone-700 dark:bg-stone-900">
      <div className="mb-1 font-medium">{label}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: p.color }} aria-hidden />
          <span className="text-stone-600 dark:text-stone-300">{p.name}</span>
          <span className="ml-auto pl-3 font-semibold tabular-nums">{p.value}{unit}</span>
        </div>
      ))}
    </div>
  );
}

export function CountsChart({ sections, threshold, pestName }: { sections: Section[]; threshold: number; pestName: string }) {
  const [asTable, setAsTable] = useState(false);
  const labels = sectionLabels(sections);
  const data = sections.map((s, i) => ({ label: labels[i], pests: s.pest_total, predators: s.predator_total }));

  return (
    <div>
      <div className="mb-2 flex justify-end">
        <button onClick={() => setAsTable((v) => !v)} className="text-xs font-medium text-leaf-700 underline-offset-2 hover:underline dark:text-leaf-500">
          {asTable ? "Show chart" : "Show as table"}
        </button>
      </div>
      {asTable ? (
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-white text-left text-stone-500 dark:bg-stone-900">
              <tr><th className="py-1">Section</th><th className="text-right">Pests ({pestName})</th><th className="text-right">Predators</th></tr>
            </thead>
            <tbody className="tabular-nums">
              {data.map((d, i) => (
                <tr key={i} className="border-t border-stone-100 dark:border-stone-800">
                  <td className="py-1">{d.label}</td><td className="text-right">{d.pests}</td><td className="text-right">{d.predators}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="h-72 w-full">
          <ResponsiveContainer>
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -8 }}>
              <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
              <XAxis dataKey="label" {...axisProps} minTickGap={16} />
              <YAxis {...axisProps} allowDecimals={false} />
              <Tooltip content={<ChartTooltip />} />
              <Legend verticalAlign="top" height={28} iconType="circle" wrapperStyle={{ fontSize: 13 }} />
              <ReferenceLine
                y={threshold}
                stroke="var(--chart-threshold)"
                strokeDasharray="5 4"
                label={{ value: `Action threshold (${threshold}/day)`, position: "insideTopLeft", fill: "var(--chart-axis)", fontSize: 11 }}
              />
              <Line type="linear" dataKey="pests" name={`Pests (${pestName})`} stroke="var(--series-pest)"
                    strokeWidth={2} dot={{ r: 4, strokeWidth: 2, fill: "var(--series-pest)", stroke: "var(--surface)" }}
                    activeDot={{ r: 6 }} isAnimationActive={false} />
              <Line type="linear" dataKey="predators" name="Predators" stroke="var(--series-predator)"
                    strokeWidth={2} dot={{ r: 4, strokeWidth: 2, fill: "var(--series-predator)", stroke: "var(--surface)" }}
                    activeDot={{ r: 6 }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

export function DegreeDayChart({ days }: { days: ClimateDay[] }) {
  const data = days.map((d) => ({
    label: new Date(d.date + "T00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" }),
    dd: d.degree_days, tmin: d.tmin, tmax: d.tmax,
  }));
  return (
    <div className="h-48 w-full">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
          <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
          <XAxis dataKey="label" {...axisProps} minTickGap={12} />
          <YAxis {...axisProps} />
          <Tooltip
            cursor={{ fill: "var(--chart-grid)", opacity: 0.4 }}
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              const p = payload[0].payload as (typeof data)[number];
              return (
                <div className="rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm shadow-md dark:border-stone-700 dark:bg-stone-900">
                  <div className="font-medium">{label}</div>
                  <div>{p.dd} degree-days</div>
                  <div className="text-stone-500 dark:text-stone-400">Min {p.tmin} °C · Max {p.tmax} °C</div>
                </div>
              );
            }}
          />
          <Bar dataKey="dd" name="Degree-days" fill="var(--series-climate)" radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function DegreeDayMeter({ dd, perGeneration, pestName }: { dd: DegreeDays; perGeneration: number; pestName: string }) {
  const pct = Math.round(dd.progress_fraction * 100);
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-3xl font-bold tabular-nums">
          {dd.days_to_next_generation ?? "–"}
          <span className="ml-1 text-base font-medium text-stone-500 dark:text-stone-400">
            {dd.days_to_next_generation != null ? "days" : ""}
          </span>
        </span>
        <span className="text-sm text-stone-500 dark:text-stone-400">to next {pestName} generation</span>
      </div>
      <div className="mt-3 h-3 w-full overflow-hidden rounded-full bg-stone-200 dark:bg-stone-800"
           role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}
           aria-label="Degree-day progress toward the next generation">
        <div className="h-full rounded-full bg-trap-400" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-2 flex justify-between text-xs text-stone-500 dark:text-stone-400 tabular-nums">
        <span>{dd.progress_dd} of {perGeneration} degree-days ({pct}%)</span>
        <span>{dd.generations_completed} generation(s) so far</span>
      </div>
      {dd.days_of_data === 0 && <p className="mt-2 text-xs text-stone-500">No temperature readings yet.</p>}
    </div>
  );
}
