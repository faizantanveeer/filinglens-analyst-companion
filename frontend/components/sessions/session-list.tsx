"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Check, Loader2, MessageSquare, MoreHorizontal, Pencil, Pin, PinOff, Search, SquarePen, Trash2, X } from "lucide-react";

import { useChat } from "@/components/chat/chat-provider";
import { useSessions } from "@/components/sessions/sessions-provider";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import type { SessionInfo } from "@/lib/api";
import { cn } from "@/lib/utils";

/** Today / Yesterday / Previous 7 days / Previous 30 days / Older, by last activity. */
function groupByDate(list: SessionInfo[]) {
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const today = startOfDay(new Date());
  const day = 86_400_000;
  const groups: { label: string; items: SessionInfo[] }[] = [
    { label: "Today", items: [] },
    { label: "Yesterday", items: [] },
    { label: "Previous 7 days", items: [] },
    { label: "Previous 30 days", items: [] },
    { label: "Older", items: [] },
  ];
  for (const s of list) {
    const t = startOfDay(new Date(s.updated_at));
    const i = t >= today ? 0 : t >= today - day ? 1 : t >= today - 7 * day ? 2 : t >= today - 30 * day ? 3 : 4;
    groups[i].items.push(s);
  }
  return groups.filter((g) => g.items.length);
}

function SessionRow({ s, active, onDelete, onNavigate }: { s: SessionInfo; active: boolean; onDelete: () => void; onNavigate?: () => void }) {
  const { rename, pin } = useSessions();
  const [editing, setEditing] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const renameNext = useRef(false); // start editing once the menu has closed, so focus lands in the input
  const [title, setTitle] = useState(s.title);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  const save = async () => {
    setEditing(false);
    if (title.trim() && title.trim() !== s.title) await rename(s.id, title);
    else setTitle(s.title);
  };

  if (editing) {
    return (
      <div className="flex items-center gap-1 rounded-md bg-muted px-1 py-1">
        <input
          ref={inputRef}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void save();
            if (e.key === "Escape") {
              setTitle(s.title);
              setEditing(false);
            }
          }}
          onBlur={() => void save()}
          maxLength={120}
          aria-label="Chat title"
          className="h-7 min-w-0 flex-1 rounded border bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
        />
        <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => void save()} aria-label="Save title" className="rounded p-1 text-muted-foreground hover:text-foreground">
          <Check className="size-3.5" aria-hidden />
        </button>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "group relative flex items-center rounded-md transition-colors",
        active ? "bg-accent text-accent-foreground" : "text-foreground/80 hover:bg-muted hover:text-foreground",
      )}
    >
      <Link
        href={`/c/${s.id}`}
        onClick={onNavigate}
        aria-current={active ? "page" : undefined}
        className="min-w-0 flex-1 rounded-md px-2.5 py-1.5 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
        title={s.title}
      >
        <span className="flex items-center gap-1.5">
          {s.pinned && <Pin className="size-3 shrink-0 text-muted-foreground" aria-label="Pinned" />}
          <span className="truncate">{s.title}</span>
        </span>
        {s.snippet && <span className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{s.snippet}</span>}
      </Link>
      {/* The ⋯ menu: always visible on touch screens; on desktop it appears on hover/focus (or while open),
          so titles use the full width the rest of the time. */}
      <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label={`Options for "${s.title}"`}
            className={cn(
              "mr-1 shrink-0 rounded p-1 text-muted-foreground outline-none hover:bg-background hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50",
              !menuOpen && "md:opacity-0 md:group-focus-within:opacity-100 md:group-hover:opacity-100",
            )}
          >
            <MoreHorizontal className="size-4" aria-hidden />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" side="bottom" onCloseAutoFocus={(e) => {
            if (!renameNext.current) return;
            renameNext.current = false;
            e.preventDefault();
            setEditing(true);
          }}>
          <DropdownMenuItem onSelect={() => void pin(s.id, !s.pinned)}>
            {s.pinned ? <PinOff aria-hidden /> : <Pin aria-hidden />}
            {s.pinned ? "Unpin" : "Pin"}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => (renameNext.current = true)}>
            <Pencil aria-hidden /> Rename
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" onSelect={onDelete}>
            <Trash2 aria-hidden /> Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

export function SessionList({ onNavigate }: { onNavigate?: () => void }) {
  const router = useRouter();
  const { sessions, query, setQuery, remove } = useSessions();
  const { sessionId, newChat } = useChat();
  const [toDelete, setToDelete] = useState<SessionInfo | null>(null);
  const [deleting, setDeleting] = useState(false);

  const confirmDelete = async () => {
    if (!toDelete) return;
    setDeleting(true);
    const ok = await remove(toDelete.id);
    setDeleting(false);
    if (ok && toDelete.id === sessionId) {
      newChat();
      router.push("/");
    }
    setToDelete(null);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="space-y-2 px-3 pb-2">
        <Button
          variant="outline"
          className="w-full justify-start gap-2 bg-background"
          onClick={() => {
            newChat();
            router.push("/");
            onNavigate?.();
          }}
        >
          <SquarePen aria-hidden /> New chat
          <kbd className="ml-auto hidden text-[10px] font-normal text-muted-foreground lg:inline">Ctrl+K</kbd>
        </Button>
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search chats"
            aria-label="Search chats"
            className="h-8 w-full rounded-md border bg-background pr-7 pl-8 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 [&::-webkit-search-cancel-button]:hidden"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="Clear search"
              className="absolute top-1/2 right-1.5 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:text-foreground"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          )}
        </div>
      </div>

      <nav aria-label="Chat history" className="min-h-0 flex-1 overflow-y-auto px-3 pb-4 [scrollbar-width:thin]">
        {sessions === null ? (
          <div className="space-y-2 pt-2">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-7 w-full" />
            ))}
          </div>
        ) : sessions.length === 0 ? (
          <p className="flex items-center gap-2 px-2.5 pt-3 text-xs text-muted-foreground">
            {query ? <Search className="size-3.5" aria-hidden /> : <MessageSquare className="size-3.5" aria-hidden />}
            {query ? "No chats match your search." : "Your chats will appear here."}
          </p>
        ) : (
          [
            ...(query ? [] : [{ label: "Pinned", items: sessions.filter((x) => x.pinned) }].filter((g) => g.items.length)),
            ...groupByDate(query ? sessions : sessions.filter((x) => !x.pinned)),
          ].map((g) => (
            <section key={g.label} className="pt-3">
              <h3 className="px-2.5 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{g.label}</h3>
              <ul className="space-y-0.5">
                {g.items.map((s) => (
                  <li key={s.id}>
                    <SessionRow s={s} active={s.id === sessionId} onDelete={() => setToDelete(s)} onNavigate={onNavigate} />
                  </li>
                ))}
              </ul>
            </section>
          ))
        )}
      </nav>

      <Dialog open={toDelete !== null} onOpenChange={(open) => !open && !deleting && setToDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete this chat?</DialogTitle>
            <DialogDescription>
              &ldquo;{toDelete?.title}&rdquo; and all its messages will be deleted. This can&apos;t be undone. Cross-chat memories are kept; manage
              them in Settings.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline" disabled={deleting}>
                Cancel
              </Button>
            </DialogClose>
            <Button variant="destructive" onClick={confirmDelete} disabled={deleting}>
              {deleting && <Loader2 className="animate-spin" aria-hidden />}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
