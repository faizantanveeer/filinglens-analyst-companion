"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, ExternalLink, FileText, Globe, ImageIcon, TextIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { pageImageUrl } from "@/lib/api";
import type { Citation, DocCitation } from "@/lib/sse";
import { cn } from "@/lib/utils";

/** The real page with the cited passage highlighted, so a reader can check the claim against the filing itself. */
function PageView({ c }: { c: DocCitation }) {
  const [state, setState] = useState<"loading" | "ok" | "error">("loading");
  const src = pageImageUrl(c.doc_id, c.page, c.text);
  useEffect(() => setState("loading"), [src]);
  return (
    <div className="relative">
      {state === "loading" && <Skeleton className="aspect-[8.5/11] w-full" />}
      {state === "error" ? (
        <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
          Couldn&apos;t render this page. The extracted text is in the Text tab.
        </p>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element -- dynamic API image; next/image adds nothing here
        <img
          src={src}
          alt={`Page ${c.page} of ${c.filename}, with the cited passage highlighted`}
          onLoad={() => setState("ok")}
          onError={() => setState("error")}
          className={cn("w-full rounded-lg border bg-white shadow-sm", state !== "ok" && "absolute inset-0 opacity-0")}
        />
      )}
    </div>
  );
}

export function SourcePanel({ citation, onClose }: { citation: Citation | null; onClose: () => void }) {
  const [tab, setTab] = useState<"page" | "text">("page");
  useEffect(() => setTab("page"), [citation]);
  const isDoc = citation?.kind === "document";

  return (
    <Sheet open={citation !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full gap-0 sm:max-w-2xl">
        {citation && (
          <>
            <SheetHeader className="border-b p-6 pr-12">
              {citation.kind === "web" ? (
                <>
                  <SheetTitle className="flex items-start gap-2 wrap-break-word">
                    <Globe className="mt-1 size-4 shrink-0 text-primary" aria-hidden />
                    <span className="min-w-0">{citation.title || citation.site}</span>
                  </SheetTitle>
                  <SheetDescription asChild>
                    <a
                      href={citation.url}
                      target="_blank"
                      rel="noopener noreferrer nofollow"
                      className="inline-flex items-center gap-1 break-all text-primary underline-offset-4 hover:underline"
                    >
                      {citation.site}
                      <ExternalLink className="size-3 shrink-0" aria-hidden />
                    </a>
                  </SheetDescription>
                  <div className="flex flex-wrap gap-2 pt-2">
                    <Badge variant="outline">Web source, not your documents</Badge>
                  </div>
                </>
              ) : (
                <>
                  <SheetTitle className="flex items-center gap-2">
                    <FileText className="size-4 text-primary" aria-hidden />
                    Page {citation.page}
                  </SheetTitle>
                  <SheetDescription className="break-all">
                    {citation.filename}
                    {citation.section ? ` · ${citation.section}` : ""}
                  </SheetDescription>
                  <div className="flex flex-wrap items-center gap-2 pt-2">
                    <Badge variant="secondary">Relevance {citation.score.toFixed(2)}</Badge>
                    <div role="tablist" aria-label="Source view" className="ml-auto inline-flex rounded-full bg-muted p-0.5">
                      {(["page", "text"] as const).map((t) => (
                        <button
                          key={t}
                          role="tab"
                          type="button"
                          aria-selected={tab === t}
                          onClick={() => setTab(t)}
                          className={cn(
                            "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
                            tab === t ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
                          )}
                        >
                          {t === "page" ? <ImageIcon className="size-3.5" aria-hidden /> : <TextIcon className="size-3.5" aria-hidden />}
                          {t === "page" ? "Page" : "Text"}
                        </button>
                      ))}
                    </div>
                  </div>
                </>
              )}
              {citation.suspicious && (
                <Badge variant="destructive" className="mt-2 w-fit gap-1">
                  <AlertTriangle className="size-3" aria-hidden /> Contains instruction-like text
                </Badge>
              )}
            </SheetHeader>
            <div className="min-h-0 flex-1 overflow-y-auto p-6">
              {isDoc && tab === "page" ? (
                <PageView c={citation as DocCitation} />
              ) : (
                <pre className="font-sans text-sm leading-relaxed whitespace-pre-wrap text-foreground wrap-anywhere">{citation.text}</pre>
              )}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
