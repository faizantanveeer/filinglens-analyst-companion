"use client";

import { useState } from "react";
import {
  AlertCircle,
  ArrowUpRight,
  Calculator,
  Check,
  ChevronRight,
  Copy,
  FileText,
  Globe,
  Info,
  Layers,
  Loader2,
  SearchX,
  ShieldAlert,
  Sparkles,
  Telescope,
  Brain,
  BookOpen,
  Zap,
} from "lucide-react";
import { toast } from "sonner";

import type { Message } from "@/components/chat/chat-provider";
import { AnswerChart } from "@/components/chat/answer-chart";
import { AnswerText } from "@/components/chat/answer-text";
import { Skeleton } from "@/components/ui/skeleton";
import type { Citation } from "@/lib/sse";
import { cn } from "@/lib/utils";

const NOTICE = {
  not_found: {
    icon: SearchX,
    title: "Not found in your documents",
    hint: "FilingLens couldn't find support for this, so it didn't guess.",
  },
  refusal: { icon: ShieldAlert, title: "Request blocked", hint: "" },
  out_of_scope: { icon: Info, title: "Outside your documents", hint: "Turn on Web in the question box to answer questions like this." },
} as const;

function SectionLabel({ icon: Icon, children }: { icon: typeof Sparkles; children: React.ReactNode }) {
  return (
    <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-muted-foreground">
      <Icon className="size-4 text-primary" aria-hidden />
      {children}
    </h3>
  );
}

/** Live progress: completed steps get a check, the current one spins. */
function Progress({ m }: { m: Message }) {
  const steps = [...new Set(m.steps ?? [])];
  const visible = m.deep ? steps : steps.slice(-3);
  return (
    <ol className="space-y-2" aria-live="polite" aria-label="Progress">
      {visible.map((s, i) => {
        const current = i === visible.length - 1;
        return (
          <li key={s} className={cn("flex items-start gap-2.5 text-sm", current ? "text-foreground" : "text-muted-foreground")}>
            {current ? (
              <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin text-primary" aria-hidden />
            ) : (
              <Check className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
            )}
            <span className="min-w-0 wrap-anywhere">{s}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** Horizontal row of source cards, one per distinct page or web page, in citation order. */
function SourceCards({ citations, onOpen }: { citations: Citation[]; onOpen: (c: Citation) => void }) {
  const seen = new Set<string>();
  const unique = citations.filter((c) => {
    const k = c.kind === "web" ? c.url : `${c.doc_id}:${c.page}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  if (!unique.length) return null;
  return (
    <details open className="group/src" aria-label="Sources">
      <summary className="cursor-pointer list-none rounded-md outline-none select-none focus-visible:ring-[3px] focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden mb-3 flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground">
        <ChevronRight className="size-4 transition-transform group-open/src:rotate-90" aria-hidden />
        <Layers className="size-4 text-primary" aria-hidden />
        Sources <span className="text-xs font-normal">({unique.length})</span>
      </summary>
      <ul className="-mx-1 flex snap-x gap-2 overflow-x-auto px-1 pb-2 [scrollbar-width:thin]">
        {unique.map((c, i) => (
          <li key={c.label} className="w-52 shrink-0 snap-start sm:w-56">
            <button
              type="button"
              onClick={() => onOpen(c)}
              className="flex h-full w-full flex-col gap-2 rounded-xl border bg-card p-3 text-left transition-colors outline-none hover:border-primary/40 hover:bg-accent/50 focus-visible:ring-[3px] focus-visible:ring-ring/50"
            >
              <span className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                {c.text.replace(/[#*_|>`-]+/g, " ").replace(/\s+/g, " ").trim()}
              </span>
              <span className="mt-auto flex min-w-0 items-center gap-1.5 text-xs font-medium">
                {c.kind === "web" ? (
                  <Globe className="size-3.5 shrink-0 text-primary" aria-hidden />
                ) : (
                  <FileText className="size-3.5 shrink-0 text-primary" aria-hidden />
                )}
                <span className="truncate">{c.kind === "web" ? c.site.replace(/^www\./, "") : `p. ${c.page} · ${c.filename}`}</span>
                <span className="ml-auto shrink-0 rounded bg-muted px-1.5 text-[10px] text-muted-foreground tabular-nums">{i + 1}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </details>
  );
}

function Actions({ m }: { m: Message }) {
  const [copied, setCopied] = useState(false);
  const d = m.meta;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(m.content.replace(/\s*\[[CW]\d+\]/g, ""));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Couldn't copy to the clipboard.");
    }
  };
  if (!d) return null;
  const tokens = d.usage.input_tokens + d.usage.output_tokens;
  return (
    <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2 border-t pt-3 text-xs text-muted-foreground">
      <button
        type="button"
        onClick={copy}
        className="-ml-1.5 inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 transition-colors outline-none hover:bg-muted hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50"
      >
        {copied ? <Check className="size-3.5 text-primary" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
        {copied ? "Copied" : "Copy"}
      </button>
      {d.cached && (
        <span className="inline-flex items-center gap-1 font-medium text-primary">
          <Zap className="size-3" aria-hidden /> Cached
        </span>
      )}
      {d.memories_used && d.memories_used.length > 0 && (
        <span className="inline-flex items-center gap-1 text-primary" title={`Shaped by: ${d.memories_used.join(" · ")}`}>
          <Brain className="size-3" aria-hidden /> Used {d.memories_used.length} memor{d.memories_used.length === 1 ? "y" : "ies"}
        </span>
      )}
      {d.model && <span>{d.model.replace(/^[a-z]+\//, "")}</span>}
      <span>{tokens.toLocaleString()} tokens</span>
      {d.usage.cost > 0 && <span>${d.usage.cost.toFixed(4)}</span>}
      <span>{(d.latency_ms / 1000).toFixed(1)}s</span>
      {d.verification === "retry_pass" && <span>verified on retry</span>}
      {d.judge && !d.judge.faithful && (
        <span className="inline-flex items-center gap-1 text-destructive" title={d.judge.reason}>
          <AlertCircle className="size-3" aria-hidden /> Judge flagged this answer
        </span>
      )}
    </div>
  );
}

/** Plain-English definitions of jargon in the answer. General knowledge, clearly separated from the
 *  document-backed answer; the server drops any definition containing a number. */
function KeyTerms({ terms }: { terms: { term: string; definition: string }[] }) {
  return (
    <details className="group/terms mt-5 rounded-xl border bg-muted/30 p-4" aria-label="Key terms">
      <summary className="cursor-pointer list-none rounded-md outline-none select-none focus-visible:ring-[3px] focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-medium">
        <ChevronRight className="size-4 transition-transform group-open/terms:rotate-90" aria-hidden />
        <BookOpen className="size-4 text-primary" aria-hidden /> Key terms ({terms.length})
        <span className="text-xs font-normal text-muted-foreground">General definitions, not from your documents</span>
      </summary>
      <dl className="mt-3 grid gap-3 sm:grid-cols-2">
        {terms.map((t) => (
          <div key={t.term}>
            <dt className="text-sm font-medium">{t.term}</dt>
            <dd className="text-sm leading-relaxed text-muted-foreground">{t.definition}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

export function Related({ items, onPick, disabled }: { items: string[]; onPick: (q: string) => void; disabled?: boolean }) {
  return (
    <section aria-label="Related questions" className="mt-8">
      <SectionLabel icon={ArrowUpRight}>Related</SectionLabel>
      <ul className="divide-y border-y">
        {items.map((q) => (
          <li key={q}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onPick(q)}
              className="group flex w-full items-center gap-3 py-3 text-left text-[15px] transition-colors outline-none hover:text-primary focus-visible:text-primary focus-visible:underline disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span className="min-w-0 flex-1 wrap-break-word">{q}</span>
              <ArrowUpRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-primary" aria-hidden />
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** One question and its answer, laid out like a short research note rather than chat bubbles. */
export function Turn({ question, m, onCite }: { question: string; m?: Message; onCite: (c: Citation) => void }) {
  const citations = m?.citations ?? [];
  const working = m?.status === "streaming" && !m.content;
  const notice = m?.answerType && m.answerType in NOTICE ? NOTICE[m.answerType as keyof typeof NOTICE] : null;
  const web = m?.answerType === "web";
  const steps = [...new Set(m?.steps ?? [])];

  return (
    <article className="scroll-mt-20">
      <h2 className="text-lg leading-snug font-semibold tracking-tight wrap-break-word sm:text-xl">{question}</h2>
      {m?.deep && (
        <p className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-accent px-2.5 py-0.5 text-xs font-medium text-accent-foreground">
          <Telescope className="size-3.5" aria-hidden /> Deep research
        </p>
      )}

      <div className="mt-6 space-y-7">
        {!m ? null : m.status === "error" ? (
          <div role="alert" className="flex items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm">
            <AlertCircle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
            <p className="min-w-0 wrap-anywhere">{m.error}</p>
          </div>
        ) : working ? (
          <>
            <Progress m={m} />
            <div className="space-y-2.5" aria-hidden>
              <Skeleton className="h-4 w-11/12" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-4/6" />
            </div>
          </>
        ) : notice ? (
          <div className="rounded-2xl border border-dashed bg-muted/30 p-5">
            <div className="flex items-center gap-2 font-medium">
              <notice.icon className="size-5 shrink-0 text-muted-foreground" aria-hidden />
              {notice.title}
            </div>
            <p className="mt-2 text-[15px] wrap-break-word text-muted-foreground">{m.content}</p>
            {notice.hint && <p className="mt-1 text-sm text-muted-foreground">{notice.hint}</p>}
            <Actions m={m} />
          </div>
        ) : (
          <>
            <SourceCards citations={citations} onOpen={onCite} />
            <section aria-label="Answer">
              <SectionLabel icon={web ? Globe : Sparkles}>
                Answer
                {web && (
                  <span className="rounded-full border border-dashed px-2 py-0.5 text-xs font-normal">
                    From the web · {m.meta?.web_reason ?? "not in your documents"}
                  </span>
                )}
              </SectionLabel>
              {m.deep && m.status === "done" && steps.length > 0 && (
                <details className="group mb-4 text-xs text-muted-foreground">
                  <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded-md py-1 font-medium outline-none select-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden">
                    <ChevronRight className="size-3 transition-transform group-open:rotate-90" aria-hidden />
                    {steps.length} research steps
                  </summary>
                  <ol className="mt-2 space-y-1 border-l pl-4">
                    {steps.map((s) => (
                      <li key={s} className="wrap-anywhere">
                        {s}
                      </li>
                    ))}
                  </ol>
                </details>
              )}
              <div className="text-[15px] sm:text-base">
                <AnswerText text={m.content} citations={citations} onCite={onCite} />
              </div>
              {m.chart && <AnswerChart chart={m.chart} citations={citations} onCite={onCite} />}
              {m.meta?.key_terms && m.meta.key_terms.length > 0 && <KeyTerms terms={m.meta.key_terms} />}
              {m.meta?.calculation && (
                <p className="mt-4 inline-flex max-w-full items-center gap-1.5 rounded-lg bg-muted px-2.5 py-1.5 text-xs wrap-break-word text-muted-foreground">
                  <Calculator className="size-3.5 shrink-0" aria-hidden />
                  Computed in Python: {m.meta.calculation.label} = {m.meta.calculation.value.toLocaleString()} {m.meta.calculation.unit}
                </p>
              )}
              <Actions m={m} />
            </section>
          </>
        )}
      </div>
    </article>
  );
}
