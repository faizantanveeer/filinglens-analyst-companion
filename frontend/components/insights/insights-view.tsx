"use client";

import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError, type Insights } from "@/lib/api";

const ROUTE_LABELS: Record<string, string> = {
  answer: "Answered",
  web: "Answered from web",
  not_found: "Not found",
  cached: "Cache hit",
  refusal: "Refused",
  out_of_scope: "Out of scope",
  error: "Error",
};

function compact(n: number) {
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight">{value}</p>
    </div>
  );
}

/** One-series horizontal bar chart: accent bars ≤ 24px, 4px rounded data end, value at the tip, hover tooltip. */
function HBar({ title, data, unit }: { title: string; data: { name: string; value: number }[]; unit: string }) {
  const height = Math.max(120, data.length * 36 + 24);
  return (
    <figure className="rounded-xl border bg-card p-4">
      <figcaption className="mb-3 text-sm font-medium">{title}</figcaption>
      {data.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">No data yet.</p>
      ) : (
        <div style={{ height }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} layout="vertical" margin={{ top: 0, right: 48, bottom: 0, left: 0 }} barCategoryGap={8}>
              <CartesianGrid horizontal={false} stroke="var(--chart-grid)" />
              <XAxis type="number" hide domain={[0, "dataMax"]} />
              <YAxis
                type="category"
                dataKey="name"
                width={110}
                tickLine={false}
                axisLine={false}
                tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
              />
              <Tooltip
                cursor={{ fill: "var(--muted)", opacity: 0.6 }}
                formatter={(v) => [`${Number(v).toLocaleString()} ${unit}`, ""]}
                separator=""
                contentStyle={{
                  background: "var(--popover)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  color: "var(--popover-foreground)",
                  fontSize: 12,
                }}
                labelStyle={{ color: "var(--popover-foreground)", fontWeight: 500 }}
              />
              <Bar dataKey="value" fill="var(--chart-1)" radius={[0, 4, 4, 0]} maxBarSize={24} isAnimationActive={false}>
                <LabelList dataKey="value" position="right" fill="var(--foreground)" fontSize={12} formatter={(v) => compact(Number(v))} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </figure>
  );
}

export function InsightsView() {
  const [data, setData] = useState<Insights | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      setData(await api.insights());
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not load insights.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  return (
    <section aria-labelledby="page-title" className="space-y-8">
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 id="page-title" className="text-2xl font-semibold tracking-tight">
            Insights
          </h1>
          <p className="text-muted-foreground">Cost, tokens, cache and latency across all requests.</p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading} aria-label="Refresh insights">
          <RefreshCw className={loading ? "animate-spin" : undefined} aria-hidden /> Refresh
        </Button>
      </header>

      {!data ? (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
            <Stat label="Requests" value={data.requests.toLocaleString()} />
            <Stat label="Total cost" value={`$${data.total_cost.toFixed(4)}`} />
            <Stat label="Avg tokens per query" value={compact(data.avg_tokens)} />
            <Stat label="Cache hit rate" value={`${Math.round(data.cache_hit_rate * 100)}%`} />
            <Stat label="p50 latency" value={`${(data.p50_latency_ms / 1000).toFixed(1)}s`} />
            <Stat label="p95 latency" value={`${(data.p95_latency_ms / 1000).toFixed(1)}s`} />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <HBar
              title="Requests by outcome"
              unit="requests"
              data={data.routes.map((r) => ({ name: ROUTE_LABELS[r.route] ?? r.route, value: r.count }))}
            />
            <HBar
              title="Average time per pipeline step (ms)"
              unit="ms"
              data={[...data.step_latency]
                .filter((s) => s.avg_ms > 0)
                .sort((a, b) => b.avg_ms - a.avg_ms)
                .map((s) => ({ name: s.step.replace("_", " "), value: s.avg_ms }))}
            />
          </div>

          <div className="space-y-3">
            <h2 className="text-sm font-medium text-muted-foreground">Recent requests</h2>
            {data.recent.length === 0 ? (
              <p className="rounded-lg border px-4 py-6 text-center text-sm text-muted-foreground">No requests yet. Ask something in Chat.</p>
            ) : (
              <>
              {/* Phones: one card per request instead of a table that needs sideways scrolling. */}
              <ul className="divide-y rounded-xl border sm:hidden">
                {data.recent.map((r) => (
                  <li key={r.id} className="space-y-1 px-4 py-3 text-sm">
                    <p className="line-clamp-2 wrap-break-word">{r.question}</p>
                    <p className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                      <span className="font-medium text-foreground">{ROUTE_LABELS[r.route] ?? r.route}</span>
                      <span>{(r.input_tokens + r.output_tokens).toLocaleString()} tokens</span>
                      <span>${r.cost.toFixed(4)}</span>
                      <span>{(r.latency_ms / 1000).toFixed(1)}s</span>
                    </p>
                  </li>
                ))}
              </ul>
              <div className="hidden overflow-x-auto rounded-xl border sm:block">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                    <tr>
                      <th scope="col" className="px-4 py-2 font-medium">Question</th>
                      <th scope="col" className="px-4 py-2 font-medium">Outcome</th>
                      <th scope="col" className="px-4 py-2 font-medium">Model</th>
                      <th scope="col" className="px-4 py-2 text-right font-medium">Tokens</th>
                      <th scope="col" className="px-4 py-2 text-right font-medium">Cost</th>
                      <th scope="col" className="px-4 py-2 text-right font-medium">Latency</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {data.recent.map((r) => (
                      <tr key={r.id}>
                        <td className="max-w-xs truncate px-4 py-2" title={r.question}>
                          {r.question}
                        </td>
                        <td className="px-4 py-2 whitespace-nowrap">{ROUTE_LABELS[r.route] ?? r.route}</td>
                        <td className="px-4 py-2 whitespace-nowrap text-muted-foreground">{r.model?.replace(/^[a-z]+\//, "") || "–"}</td>
                        <td className="px-4 py-2 text-right tabular-nums">{(r.input_tokens + r.output_tokens).toLocaleString()}</td>
                        <td className="px-4 py-2 text-right tabular-nums">${r.cost.toFixed(4)}</td>
                        <td className="px-4 py-2 text-right tabular-nums">{(r.latency_ms / 1000).toFixed(1)}s</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              </>
            )}
          </div>
        </>
      )}
    </section>
  );
}
