"use client";

import { Fragment } from "react";

import type { Citation } from "@/lib/sse";

/**
 * Renders the small markdown subset answers use ("### " headings, "- " bullets, **bold**,
 * paragraphs) and turns [C#]/[W#] markers into source chips. Hand-rolled on purpose: no
 * HTML is ever injected, so model output can't smuggle markup into the page.
 */

function chipLabel(c: Citation) {
  return c.kind === "web" ? c.site.replace(/^www\./, "") : `p. ${c.page}`;
}

function Inline({ text, byLabel, onCite }: { text: string; byLabel: Map<string, Citation>; onCite: (c: Citation) => void }) {
  let last: string | null = null;
  return (
    <>
      {text.split(/(\[[CW]\d+\]|\*\*[^*]+\*\*)/g).map((part, i) => {
        const cite = part.match(/^\[([CW]\d+)\]$/);
        if (cite) {
          const c = byLabel.get(cite[1]);
          if (!c) return null;
          const key = c.kind === "web" ? c.url : `${c.doc_id}:${c.page}`;
          if (key === last) return null; // "[C1][C2]" on the same page → one chip
          last = key;
          return (
            <button
              key={i}
              type="button"
              onClick={() => onCite(c)}
              aria-label={c.kind === "web" ? `Open web source: ${c.title || c.site}` : `Open source: page ${c.page} of ${c.filename}`}
              className="mx-0.5 inline-flex max-w-40 items-center truncate rounded-md border border-primary/30 bg-accent px-1.5 align-baseline text-xs leading-5 font-medium text-accent-foreground transition-colors outline-none hover:bg-primary hover:text-primary-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50"
            >
              {chipLabel(c)}
            </button>
          );
        }
        if (part.trim()) last = null;
        const bold = part.match(/^\*\*([^*]+)\*\*$/);
        return bold ? <strong key={i}>{bold[1]}</strong> : <Fragment key={i}>{part}</Fragment>;
      })}
    </>
  );
}

type Block = { type: "h"; text: string } | { type: "p"; text: string } | { type: "ul"; items: string[] };

function toBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length) blocks.push({ type: "p", text: para.join(" ") });
    para = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const heading = line.match(/^#{1,6}\s+(.*)$/);
    const bullet = line.match(/^(?:[-*•]|\d+[.)])\s+(.*)$/);
    if (!line) flush();
    else if (heading) {
      flush();
      blocks.push({ type: "h", text: heading[1] });
    } else if (bullet) {
      flush();
      const prev = blocks[blocks.length - 1];
      if (prev?.type === "ul") prev.items.push(bullet[1]);
      else blocks.push({ type: "ul", items: [bullet[1]] });
    } else para.push(line);
  }
  flush();
  return blocks;
}

export function AnswerText({ text, citations, onCite }: { text: string; citations: Citation[]; onCite: (c: Citation) => void }) {
  const byLabel = new Map(citations.map((c) => [c.label, c]));
  return (
    <div className="space-y-3 leading-relaxed wrap-anywhere">
      {toBlocks(text).map((b, i) =>
        b.type === "h" ? (
          <h3 key={i} className="pt-1 text-sm font-semibold tracking-tight">
            <Inline text={b.text} byLabel={byLabel} onCite={onCite} />
          </h3>
        ) : b.type === "ul" ? (
          <ul key={i} className="list-disc space-y-1 pl-5 marker:text-muted-foreground">
            {b.items.map((item, j) => (
              <li key={j}>
                <Inline text={item} byLabel={byLabel} onCite={onCite} />
              </li>
            ))}
          </ul>
        ) : (
          <p key={i}>
            <Inline text={b.text} byLabel={byLabel} onCite={onCite} />
          </p>
        ),
      )}
    </div>
  );
}
