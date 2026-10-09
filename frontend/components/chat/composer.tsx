"use client";

import { forwardRef, useLayoutEffect, useRef } from "react";
import Link from "next/link";
import { ArrowUp, Check, ChevronDown, FileStack, Globe, Square, Telescope, Zap } from "lucide-react";
import { Popover } from "radix-ui";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import type { DocumentInfo } from "@/lib/api";
import { cn } from "@/lib/utils";

type Props = {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  busy: boolean;
  disabled: boolean;
  deep: boolean;
  onDeepChange: (v: boolean) => void;
  webOn: boolean; // the user's toggle
  hasSearchKey: boolean; // a Tavily key is set in Settings
  onWebChange: (v: boolean) => void;
  docs: DocumentInfo[] | null; // ready documents, for the scope picker
  scope: string[] | null; // null = all documents
  onScopeChange: (ids: string[] | null) => void;
  size?: "hero" | "dock";
  placeholder?: string;
};

/** Segmented Quick / Deep research switch. */
function ModeSwitch({ deep, onChange }: { deep: boolean; onChange: (v: boolean) => void }) {
  const opt = (active: boolean) =>
    cn(
      "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
      active ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
      "px-2.5 sm:px-3",
    );
  return (
    <div role="radiogroup" aria-label="Answer mode" className="inline-flex rounded-full bg-muted p-0.5">
      <button type="button" role="radio" aria-checked={!deep} onClick={() => onChange(false)} className={opt(!deep)}>
        <Zap className="size-3.5" aria-hidden /> Quick
      </button>
      <button
        type="button"
        role="radio"
        aria-checked={deep}
        onClick={() => onChange(true)}
        className={opt(deep)}
        title="Breaks the question into sub-questions, reads more of the report and writes a structured answer. Slower, uses more tokens."
      >
        <Telescope className="size-3.5" aria-hidden /> Deep<span className="hidden sm:inline"> research</span>
      </button>
    </div>
  );
}

/** Web search on/off. On means "fall back to the web when the documents can't answer", never instead of them. */
function WebToggle({ on, hasKey, onChange }: { on: boolean; hasKey: boolean; onChange: (v: boolean) => void }) {
  const active = on && hasKey;
  return (
    <button
      type="button"
      role="switch"
      aria-checked={active}
      onClick={() => {
        if (!hasKey) {
          toast.info(
            <span>
              Add a Tavily key in{" "}
              <Link href="/settings" className="font-medium underline underline-offset-4">
                Settings
              </Link>{" "}
              to use web search.
            </span>,
          );
          onChange(true);
          return;
        }
        onChange(!on);
      }}
      title={
        !hasKey
          ? "Web search needs a Tavily key (Settings)."
          : active
            ? "On: used only when your documents can't answer. Click to turn off."
            : "Off: answers come from your documents only. Click to turn on."
      }
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
        active ? "border-primary/30 bg-accent text-accent-foreground" : "border-transparent text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      <Globe className="size-3.5" aria-hidden />
      <span>Web</span>
      <span
        aria-hidden
        className={cn("relative h-3.5 w-6 rounded-full transition-colors", active ? "bg-primary" : "bg-muted-foreground/30")}
      >
        <span className={cn("absolute top-0.5 size-2.5 rounded-full bg-background transition-[left]", active ? "left-3" : "left-0.5")} />
      </span>
    </button>
  );
}

/** Which documents this chat searches. Useful once you have several years or companies indexed. */
function ScopePicker({ docs, scope, onChange }: { docs: DocumentInfo[]; scope: string[] | null; onChange: (ids: string[] | null) => void }) {
  const selected = new Set(scope ?? docs.map((d) => d.id));
  const all = scope === null || selected.size === docs.length;
  const label = all ? "All documents" : selected.size === 1 ? docs.find((d) => selected.has(d.id))?.filename ?? "1 document" : `${selected.size} documents`;
  const toggle = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    if (next.size === 0) return; // at least one document must stay selected
    onChange(next.size === docs.length ? null : [...next]);
  };
  const item =
    "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm outline-none hover:bg-muted focus-visible:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50";
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          type="button"
          aria-label={`Search scope: ${label}`}
          className={cn(
            "inline-flex max-w-44 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
            all ? "border-transparent text-muted-foreground hover:bg-muted hover:text-foreground" : "border-primary/30 bg-accent text-accent-foreground",
          )}
        >
          <FileStack className="size-3.5 shrink-0" aria-hidden />
          <span className="hidden truncate sm:inline">{label}</span>
          {!all && <span className="sm:hidden">{selected.size}</span>}
          <ChevronDown className="size-3 shrink-0 opacity-60" aria-hidden />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          side="top"
          align="start"
          sideOffset={8}
          collisionPadding={12}
          className="z-50 w-72 max-w-[calc(100vw-24px)] rounded-xl border bg-popover p-1.5 text-popover-foreground shadow-lg outline-none"
        >
          <p className="px-2.5 pt-1 pb-2 text-xs font-medium text-muted-foreground">Search in</p>
          <button type="button" className={item} onClick={() => onChange(null)}>
            <span className="grid size-4 place-items-center">{all && <Check className="size-4 text-primary" aria-hidden />}</span>
            All documents
          </button>
          <div className="my-1 h-px bg-border" />
          <ul className="max-h-60 overflow-y-auto">
            {docs.map((d) => (
              <li key={d.id}>
                <button type="button" role="menuitemcheckbox" aria-checked={selected.has(d.id)} className={item} onClick={() => toggle(d.id)}>
                  <span className={cn("grid size-4 shrink-0 place-items-center rounded border", selected.has(d.id) && "border-primary bg-primary text-primary-foreground")}>
                    {selected.has(d.id) && <Check className="size-3" aria-hidden />}
                  </span>
                  <span className="min-w-0 flex-1 truncate">{d.filename}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">{d.pages}p</span>
                </button>
              </li>
            ))}
          </ul>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

/** The question box: large and centred on the empty page ("hero"), pinned at the bottom in a thread ("dock"). */
export const Composer = forwardRef<HTMLTextAreaElement, Props>(function Composer(
  {
    value,
    onChange,
    onSubmit,
    onStop,
    busy,
    disabled,
    deep,
    onDeepChange,
    webOn,
    hasSearchKey,
    onWebChange,
    docs,
    scope,
    onScopeChange,
    size = "dock",
    placeholder,
  },
  ref,
) {
  const innerRef = useRef<HTMLTextAreaElement | null>(null);
  const hero = size === "hero";

  // Grow with the content (up to a cap), shrink back after sending.
  useLayoutEffect(() => {
    const el = innerRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, hero ? 220 : 160)}px`;
  }, [value, hero]);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      className={cn(
        "group/composer relative rounded-3xl border bg-card shadow-sm transition-shadow focus-within:border-primary/40 focus-within:shadow-md focus-within:ring-4 focus-within:ring-primary/10",
        hero && "shadow-md",
      )}
    >
      <label htmlFor="question" className="sr-only">
        Your question
      </label>
      <textarea
        id="question"
        ref={(el) => {
          innerRef.current = el;
          if (typeof ref === "function") ref(el);
          else if (ref) ref.current = el;
        }}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            onSubmit();
          }
        }}
        placeholder={placeholder}
        disabled={disabled}
        rows={hero ? 2 : 1}
        maxLength={1000}
        className={cn(
          "block w-full resize-none bg-transparent px-5 text-foreground outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-60",
          hero ? "min-h-20 pt-5 text-base sm:text-lg" : "min-h-12 pt-3.5 text-[15px]",
        )}
      />
      <div className="flex items-center gap-1.5 px-3 pt-1 pb-3 sm:gap-2">
        <ModeSwitch deep={deep} onChange={onDeepChange} />
        <WebToggle on={webOn} hasKey={hasSearchKey} onChange={onWebChange} />
        {docs && docs.length > 1 && <ScopePicker docs={docs} scope={scope} onChange={onScopeChange} />}
        <div className="ml-auto">
          {busy ? (
            <Button type="button" size="icon" variant="secondary" onClick={onStop} aria-label="Stop answering" className="size-9 rounded-full">
              <Square className="fill-current" aria-hidden />
            </Button>
          ) : (
            <Button type="submit" size="icon" disabled={disabled || !value.trim()} aria-label="Send question" className="size-9 rounded-full">
              <ArrowUp aria-hidden />
            </Button>
          )}
        </div>
      </div>
    </form>
  );
});
