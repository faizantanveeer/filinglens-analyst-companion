"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ArrowDown, Calculator, Download, FileSearch, FileText, KeyRound, Plus, ShieldAlert, TrendingUp, Upload } from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { useChat } from "@/components/chat/chat-provider";
import { Composer } from "@/components/chat/composer";
import { SourcePanel } from "@/components/chat/source-panel";
import { Related, Turn } from "@/components/chat/turn";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type DocumentInfo } from "@/lib/api";
import { downloadText, threadToMarkdown } from "@/lib/export";
import { useSettings } from "@/lib/settings";
import type { Citation } from "@/lib/sse";

// Starter questions. "Briefing" runs Deep research: the quickest way for a non-specialist to get oriented in a filing.
const STARTERS = [
  {
    icon: FileSearch,
    label: "Executive briefing · Deep research",
    q: "Give me an executive briefing on this report: what the business does, key financial results, segment performance, main risks and outlook.",
    text: "Brief me on this report: business, results, segments, risks and outlook",
    deep: true,
  },
  { icon: TrendingUp, label: "Trends", q: "How has the insurance float changed over the years?", text: "", deep: false },
  { icon: Calculator, label: "Figures", q: "By what percentage did operating earnings grow last year?", text: "", deep: false },
  { icon: ShieldAlert, label: "Risks", q: "What are the main risks the company highlights?", text: "", deep: false },
];

/** True when the page is scrolled (nearly) to the bottom. */
function nearBottom() {
  return window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 120;
}

/** Scroll to the true bottom: the pinned input bar would otherwise cover the newest content. */
function toBottom(smooth = false) {
  window.scrollTo({ top: document.documentElement.scrollHeight, behavior: smooth ? "smooth" : "auto" });
}

/** "2 reports ready: report.pdf, …" so the reader knows what they're asking about. */
function DocumentsChip({ docs }: { docs: DocumentInfo[] | null }) {
  if (docs === null) return <Skeleton className="mx-auto h-7 w-56 rounded-full" />;
  const ready = docs.filter((d) => d.status === "ready");
  if (!ready.length)
    return (
      <Link
        href="/documents"
        className="inline-flex items-center gap-2 rounded-full border border-dashed px-3 py-1 text-sm text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
      >
        <Upload className="size-4 text-primary" aria-hidden /> Upload an annual report to get started
      </Link>
    );
  const pages = ready.reduce((n, d) => n + d.pages, 0);
  return (
    <Link
      href="/documents"
      className="inline-flex max-w-full items-center gap-2 rounded-full border bg-card px-3 py-1 text-sm text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
      title={ready.map((d) => d.filename).join("\n")}
    >
      <FileText className="size-4 shrink-0 text-primary" aria-hidden />
      <span className="truncate">
        {ready.length === 1 ? ready[0].filename : `${ready.length} reports`} · {pages.toLocaleString()} pages indexed
      </span>
    </Link>
  );
}

/** sessionId: null on "/" (a new chat), or the id from /c/<id>. */
export function ChatView({ sessionId = null }: { sessionId?: string | null }) {
  const router = useRouter();
  const { messages, busy, loading, send, stop, newChat, openSession, deep, setDeep, docScope, setDocScope, sessionId: openId } = useChat();
  const [docs, setDocs] = useState<DocumentInfo[] | null>(null);
  useEffect(() => {
    api.listDocuments().then(setDocs).catch(() => setDocs([]));
  }, []);
  const readyDocs = docs?.filter((d) => d.status === "ready") ?? null;
  const { ready, settings, update, tokensUsed, hasSearchKey } = useSettings();
  const { me, openAuth } = useAuth();
  const creditsHint = me?.is_guest ? (
    <p className="mt-2 text-center text-xs text-muted-foreground">
      {me.credits.remaining} of {me.credits.limit} free questions left ·{" "}
      <button type="button" onClick={() => openAuth("signup")} className="font-medium text-primary underline-offset-4 hover:underline">
        Create a free account
      </button>
    </p>
  ) : null;
  const [draft, setDraft] = useState("");
  const [source, setSource] = useState<Citation | null>(null);
  const [showJump, setShowJump] = useState(false);
  const followRef = useRef(true); // follow the stream only while the reader is at the bottom
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Route → conversation. /c/<id> opens that session (unless it's already open, e.g. we just
  // created it). Landing on "/" with an old conversation still open starts a fresh chat.
  useEffect(() => {
    if (sessionId && sessionId !== openId) void openSession(sessionId);
    if (!sessionId && openId && !busy) newChat();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const overBudget = settings.token_budget > 0 && tokensUsed >= settings.token_budget;
  const disabled = !ready || overBudget;
  const empty = messages.length === 0 && !loading && !sessionId;

  // Pair each question with its answer.
  const turns: { q: (typeof messages)[number]; a?: (typeof messages)[number] }[] = [];
  messages.forEach((m) => {
    if (m.role === "user") turns.push({ q: m });
    else if (turns.length) turns[turns.length - 1].a = m;
  });
  const lastAnswer = turns[turns.length - 1]?.a;

  useEffect(() => {
    const onScroll = () => {
      followRef.current = nearBottom();
      setShowJump(!followRef.current && !empty);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [empty]);

  // When a question is added (or a saved chat opens), bring that turn's start to the top of the
  // screen so the answer is read from its beginning; the stream doesn't drag the page down.
  const lastTurnId = turns[turns.length - 1]?.q.id;
  useLayoutEffect(() => {
    if (!lastTurnId || loading) return;
    document.getElementById(`turn-${lastTurnId}`)?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [lastTurnId, loading]);

  const submit = (text: string, opts?: { deep?: boolean; fresh?: boolean }) => {
    if (disabled || busy || !text.trim()) return;
    setDraft("");
    followRef.current = true;
    void send(text, opts);
  };

  const exportThread = () => {
    const title = turns[0]?.q.content.slice(0, 80) ?? "FilingLens chat";
    downloadText(`${title.replace(/[^\w\- ]+/g, "").trim().slice(0, 60) || "filinglens-chat"}.md`, threadToMarkdown(title, messages));
  };

  const composer = (size: "hero" | "dock") => (
    <Composer
      ref={inputRef}
      size={size}
      value={draft}
      onChange={setDraft}
      onSubmit={() => submit(draft)}
      onStop={stop}
      busy={busy}
      disabled={disabled}
      deep={deep}
      onDeepChange={setDeep}
      webOn={settings.use_web_search}
      hasSearchKey={hasSearchKey}
      onWebChange={(v) => update({ use_web_search: v })}
      docs={readyDocs}
      scope={docScope}
      onScopeChange={setDocScope}
      placeholder={
        !ready ? "Add an API key in Settings first" : size === "hero" ? "Ask anything about your annual reports…" : deep ? "Ask a research question…" : "Ask a follow-up…"
      }
    />
  );

  const notices = (
    <>
      {!ready && (
        <div className="mb-3 flex items-center gap-2 rounded-xl border bg-muted/50 px-4 py-2.5 text-sm">
          <KeyRound className="size-4 shrink-0 text-primary" aria-hidden />
          <span>
            Add an API key in{" "}
            <Link href="/settings" className="font-medium text-primary underline-offset-4 hover:underline">
              Settings
            </Link>{" "}
            to start asking questions.
          </span>
        </div>
      )}
      {overBudget && (
        <div className="mb-3 rounded-xl border bg-muted/50 px-4 py-2.5 text-sm">
          Session token budget used up ({tokensUsed.toLocaleString()} tokens). Raise it in{" "}
          <Link href="/settings" className="font-medium text-primary underline-offset-4 hover:underline">
            Settings
          </Link>
          .
        </div>
      )}
    </>
  );

  if (empty) {
    return (
      // -mb-12 cancels main's bottom padding; the hero fills the viewport below the header.
      <div className="relative -mb-12 flex min-h-[calc(100dvh-3.5rem-1.5rem)] flex-col justify-center pb-16 md:min-h-[calc(100dvh-3.5rem-2.5rem)]">
        {/* Soft accent glow behind the hero; decorative only. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 -z-10 mx-auto h-72 max-w-2xl rounded-full bg-primary/10 blur-3xl dark:bg-primary/15"
        />
        <div className="mx-auto w-full max-w-2xl space-y-8">
          <div className="space-y-4 text-center">
            <h1 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
              Ask your filings <span className="text-primary">anything</span>
            </h1>
            <p className="mx-auto max-w-md text-[15px] text-pretty text-muted-foreground">
              Answers cite the exact page, numbers are computed in code, and if it isn&apos;t in the report, FilingLens says so.
            </p>
            <DocumentsChip docs={docs} />
          </div>
          <div>
            {notices}
            {composer("hero")}
            {creditsHint}
          </div>
          <ul className="grid gap-2 sm:grid-cols-2" aria-label="Example questions">
            {STARTERS.map(({ icon: Icon, label, q, text, deep: starterDeep }) => (
              <li key={q}>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => submit(q, { deep: starterDeep })}
                  className="group flex h-full w-full items-start gap-3 rounded-2xl border bg-card/60 p-3.5 text-left transition-colors outline-none hover:border-primary/40 hover:bg-card focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-accent text-accent-foreground">
                    <Icon className="size-4" aria-hidden />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-xs font-medium text-muted-foreground">{label}</span>
                    <span className="block text-sm leading-snug">{text || q}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>
    );
  }

  return (
    <div className="-mb-12 flex min-h-[calc(100dvh-3.5rem-1.5rem)] flex-col md:min-h-[calc(100dvh-3.5rem-2.5rem)]">
      <div className="mb-6 flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={exportThread} disabled={busy || turns.length === 0} className="rounded-full" title="Download this thread as Markdown">
          <Download aria-hidden /> Export
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            newChat();
            router.push("/");
          }}
          className="rounded-full"
        >
          <Plus aria-hidden /> New thread
        </Button>
      </div>

      <div className="flex-1 space-y-12" aria-busy={busy || loading}>
        {loading && (
          <div className="space-y-4" aria-label="Loading chat">
            <Skeleton className="h-8 w-2/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-11/12" />
            <Skeleton className="h-4 w-4/6" />
          </div>
        )}
        {!loading && sessionId && turns.length === 0 && (
          <p className="text-sm text-muted-foreground">This chat has no messages yet. Ask something below.</p>
        )}
        {turns.map((t, i) => (
          <div key={t.q.id} id={`turn-${t.q.id}`} className={i > 0 ? "scroll-mt-20 border-t pt-10" : "scroll-mt-20"}>
            <Turn
              question={t.q.content}
              m={t.a}
              onCite={setSource}
              onRetry={disabled || busy ? undefined : () => submit(t.q.content, { deep: t.a?.deep ?? false, fresh: true })}
            />
          </div>
        ))}
        {lastAnswer?.status === "done" && lastAnswer.suggestions?.length ? (
          <Related items={lastAnswer.suggestions} onPick={submit} disabled={disabled || busy} />
        ) : null}
      </div>

      {/* Pinned input bar */}
      <div className="sticky bottom-0 z-20 -mx-4 mt-10 bg-linear-to-t from-background from-75% to-transparent px-4 pt-8 pb-4 md:-mx-8 md:px-8">
        {showJump && (
          <Button
            variant="outline"
            size="icon"
            className="absolute top-0 left-1/2 size-8 -translate-x-1/2 rounded-full bg-background shadow-sm"
            onClick={() => {
              followRef.current = true;
              toBottom(true);
            }}
            aria-label="Scroll to latest answer"
          >
            <ArrowDown aria-hidden />
          </Button>
        )}
        {notices}
        {composer("dock")}
        {creditsHint}
        {settings.token_budget > 0 && (
          <p className="mt-2 hidden text-center text-xs text-muted-foreground sm:block">
            {tokensUsed.toLocaleString()} / {settings.token_budget.toLocaleString()} tokens this session
          </p>
        )}
      </div>

      <SourcePanel citation={source} onClose={() => setSource(null)} />
    </div>
  );
}
