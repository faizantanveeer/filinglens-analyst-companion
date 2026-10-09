"use client";

import { useState } from "react";
import { ShieldCheck, Table2, LineChart as LineIcon } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Button } from "@/components/ui/button";
import type { ChartData, Citation } from "@/lib/sse";

// Validated categorical palette (dataviz validator, light + dark); fixed order, never cycled.
const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];

const compact = (n: number) => new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n);
const full = (n: number) => n.toLocaleString("en", { maximumFractionDigits: 2 });

type Row = { x: string; xn?: number } & Record<string, number | string | undefined>;

const YEAR = /^(19|20)\d\d$/;

function toRows(chart: ChartData): Row[] {
  const rows = new Map<string, Row>();
  chart.series.forEach((s, si) =>
    s.points.forEach((p) => {
      const row = rows.get(p.x) ?? { x: p.x, xn: YEAR.test(p.x) ? Number(p.x) : undefined };
      row[`s${si}`] = p.y;
      row[`p${si}`] = p.page;
      row[`l${si}`] = p.label;
      rows.set(p.x, row);
    }),
  );
  return [...rows.values()];
}

function ChartTooltip({
  active,
  payload,
  label,
  chart,
}: {
  active?: boolean;
  payload?: { dataKey?: string | number; value?: number | string; payload?: Row }[];
  label?: string;
  chart: ChartData;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md">
      <p className="mb-1 font-medium">{label}</p>
      {payload.map((item) => {
        const si = Number(String(item.dataKey).slice(1));
        return (
          <p key={String(item.dataKey)} className="flex items-center gap-2">
            <span aria-hidden className="size-2 rounded-full" style={{ background: SERIES[si] }} />
            <span className="text-muted-foreground">{chart.series[si]?.name}</span>
            <span className="ml-auto pl-3 font-medium tabular-nums">
              {full(Number(item.value))} {chart.unit}
            </span>
            <span className="text-muted-foreground">p. {String(item.payload?.[`p${si}`])}</span>
          </p>
        );
      })}
    </div>
  );
}

/** A chart built only from values verified against their cited page. */
export function AnswerChart({ chart, citations, onCite }: { chart: ChartData; citations: Citation[]; onCite: (c: Citation) => void }) {
  const [table, setTable] = useState(false);
  const rows = toRows(chart);
  const multi = chart.series.length > 1;
  // Years go on a proportional time axis: 2020→2022→2023 must not look evenly spaced with 1970→1980.
  const timeAxis = chart.kind === "line" && rows.length > 1 && rows.every((r) => r.xn !== undefined);
  const byLabel = new Map(citations.map((c) => [c.label, c]));
  const axisTick = { fill: "var(--muted-foreground)", fontSize: 12 };

  const common = (
    <>
      <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
      {timeAxis ? (
        <XAxis
          dataKey="xn"
          type="number"
          domain={["dataMin", "dataMax"]}
          ticks={rows.map((r) => r.xn as number)}
          tickFormatter={(v) => String(v)}
          tickLine={false}
          axisLine={{ stroke: "var(--chart-grid)" }}
          tick={axisTick}
          interval="preserveStartEnd"
          minTickGap={16}
          padding={{ left: 8, right: 8 }}
        />
      ) : (
        <XAxis dataKey="x" tickLine={false} axisLine={{ stroke: "var(--chart-grid)" }} tick={axisTick} interval="preserveStartEnd" minTickGap={12} />
      )}
      <YAxis tickLine={false} axisLine={false} tick={axisTick} tickFormatter={compact} width={48} />
      <Tooltip content={<ChartTooltip chart={chart} />} labelFormatter={(v) => String(v)} cursor={{ stroke: "var(--border)", fill: "var(--muted)", opacity: 0.5 }} />
    </>
  );

  return (
    <figure className="mt-4 rounded-xl border bg-background p-3 sm:p-4">
      <figcaption className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium wrap-break-word">{chart.title}</p>
          {chart.unit && <p className="text-xs text-muted-foreground">{chart.unit}</p>}
        </div>
        <Button variant="ghost" size="sm" onClick={() => setTable((t) => !t)} aria-pressed={table}>
          {table ? <LineIcon aria-hidden /> : <Table2 aria-hidden />}
          {table ? "Show chart" : "Show data"}
        </Button>
      </figcaption>

      {multi && !table && (
        <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Legend">
          {chart.series.map((s, i) => (
            <li key={s.name} className="flex items-center gap-1.5">
              <span aria-hidden className="h-0.5 w-3 rounded-full" style={{ background: SERIES[i], height: 3 }} />
              {s.name}
            </li>
          ))}
        </ul>
      )}

      {table ? (
        <div className="max-h-72 overflow-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-muted text-left text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">Period</th>
                {chart.series.map((s) => (
                  <th key={s.name} scope="col" className="px-3 py-2 text-right font-medium">
                    {s.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.map((r) => (
                <tr key={r.x}>
                  <td className="px-3 py-1.5 whitespace-nowrap">{r.x}</td>
                  {chart.series.map((s, si) => {
                    const c = byLabel.get(String(r[`l${si}`]));
                    return (
                      <td key={s.name} className="px-3 py-1.5 text-right whitespace-nowrap tabular-nums">
                        {r[`s${si}`] === undefined ? "–" : full(Number(r[`s${si}`]))}
                        {c && (
                          <button
                            type="button"
                            onClick={() => onCite(c)}
                            className="ml-2 text-xs text-primary underline-offset-2 hover:underline"
                            aria-label={`Open source for ${s.name} ${r.x}`}
                          >
                            p. {String(r[`p${si}`])}
                          </button>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="h-60 w-full sm:h-64" role="img" aria-label={`${chart.kind} chart: ${chart.title}`}>
          <ResponsiveContainer width="100%" height="100%">
            {chart.kind === "bar" ? (
              <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barGap={2} barCategoryGap="20%">
                {common}
                {chart.series.map((s, i) => (
                  <Bar key={s.name} dataKey={`s${i}`} name={s.name} fill={SERIES[i]} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} />
                ))}
              </BarChart>
            ) : (
              <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                {common}
                {chart.series.map((s, i) => (
                  <Line
                    key={s.name}
                    type="linear"
                    dataKey={`s${i}`}
                    name={s.name}
                    stroke={SERIES[i]}
                    strokeWidth={2}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    dot={{ r: 4, fill: SERIES[i], stroke: "var(--background)", strokeWidth: 2 }}
                    activeDot={{ r: 6, stroke: "var(--background)", strokeWidth: 2 }}
                    connectNulls
                    isAnimationActive={false}
                  />
                ))}
              </LineChart>
            )}
          </ResponsiveContainer>
        </div>
      )}

      <p className="mt-2 flex items-start gap-1.5 text-xs text-muted-foreground">
        <ShieldCheck className="mt-0.5 size-3 shrink-0 text-primary" aria-hidden />
        <span>
          Every value was checked against its cited page.
          {chart.dropped_points > 0 &&
            ` ${chart.dropped_points} value${chart.dropped_points > 1 ? "s" : ""} couldn't be verified and ${chart.dropped_points > 1 ? "were" : "was"} left out.`}
        </span>
      </p>
    </figure>
  );
}
