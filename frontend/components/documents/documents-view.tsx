"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Download, ExternalLink, FileText, Landmark, Loader2, Trash2, UploadCloud, XCircle } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAuth } from "@/components/auth/auth-provider";
import { ACCEPTED_TYPES, api, ApiError, AUTH_EVENT, type DocumentInfo } from "@/lib/api";
import { cn } from "@/lib/utils";

type Upload = { id: string; name: string; progress: number; state: "uploading" | "indexing" | "failed"; error?: string };

const MAX_MB = 50;

function StatusBadge({ doc }: { doc: DocumentInfo }) {
  if (doc.status === "ready")
    return (
      <Badge variant="secondary" className="gap-1">
        <CheckCircle2 className="size-3 text-primary" aria-hidden /> Ready
      </Badge>
    );
  if (doc.status === "error")
    return (
      <Badge variant="destructive" className="gap-1" title={doc.error ?? undefined}>
        <XCircle className="size-3" aria-hidden /> Failed
      </Badge>
    );
  return (
    <Badge variant="outline" className="gap-1">
      <Loader2 className="size-3 animate-spin" aria-hidden /> Indexing…
    </Badge>
  );
}

const FORMS = [
  { value: "10-K", label: "10-K · annual report" },
  { value: "10-Q", label: "10-Q · quarterly report" },
  { value: "20-F", label: "20-F · foreign annual report" },
  { value: "40-F", label: "40-F · Canadian annual report" },
];

/** Pull the latest filing straight from SEC EDGAR by ticker, so nobody has to hunt for a PDF. */
function EdgarImport({ onImported }: { onImported: () => Promise<void> }) {
  const [ticker, setTicker] = useState("");
  const [form, setForm] = useState("10-K");
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setBusy(true);
    try {
      const doc = await api.importFromEdgar(t, form);
      toast.success(`Fetched ${doc.filename} from SEC EDGAR. Indexing has started.`);
      setTicker("");
      await onImported();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "EDGAR import failed.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} className="rounded-xl border bg-card p-4">
      <div className="mb-3 flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent text-accent-foreground">
          <Landmark className="size-4" aria-hidden />
        </span>
        <div>
          <p className="font-medium">Import from SEC EDGAR</p>
          <p className="text-sm text-muted-foreground">Enter a US-listed ticker to fetch its latest filing. Free, no key needed.</p>
        </div>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row">
        <label htmlFor="ticker" className="sr-only">
          Ticker
        </label>
        <Input
          id="ticker"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase().replace(/[^A-Z.\-]/g, ""))}
          placeholder="Ticker, e.g. AAPL"
          maxLength={10}
          autoComplete="off"
          className="sm:w-44"
        />
        <Select value={form} onValueChange={setForm}>
          <SelectTrigger aria-label="Filing type" className="sm:w-60">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {FORMS.map((f) => (
              <SelectItem key={f.value} value={f.value}>
                {f.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button type="submit" disabled={busy || !ticker.trim()} className="sm:ml-auto">
          {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Download aria-hidden />}
          {busy ? "Fetching…" : "Import"}
        </Button>
      </div>
    </form>
  );
}

export function DocumentsView() {
  const { me, refresh: refreshMe } = useAuth();
  const [docs, setDocs] = useState<DocumentInfo[] | null>(null);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [dragging, setDragging] = useState(false);
  const [toDelete, setToDelete] = useState<DocumentInfo | null>(null);
  const [deleting, setDeleting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      setDocs(await api.listDocuments());
    } catch (err) {
      setDocs((d) => d ?? []);
      toast.error(err instanceof ApiError ? err.message : "Could not load documents.");
    }
  }, []);

  useEffect(() => {
    void refresh();
    window.addEventListener(AUTH_EVENT, refresh);
    return () => window.removeEventListener(AUTH_EVENT, refresh);
  }, [refresh]);

  // Poll while anything is indexing; indexing a 150-page report takes a few minutes.
  const indexing = docs?.some((d) => d.status === "processing");
  useEffect(() => {
    if (!indexing) return;
    const t = setInterval(() => void refresh(), 3000);
    return () => clearInterval(t);
  }, [indexing, refresh]);

  const upload = useCallback(
    async (files: FileList | File[]) => {
      for (const file of Array.from(files)) {
        const id = Math.random().toString(36).slice(2);
        if (!ACCEPTED_TYPES.some((ext) => file.name.toLowerCase().endsWith(ext))) {
          toast.error(`${file.name}: unsupported type. Use ${ACCEPTED_TYPES.join(", ")}.`);
          continue;
        }
        if (file.size > MAX_MB * 1024 * 1024) {
          toast.error(`${file.name} is larger than ${MAX_MB} MB.`);
          continue;
        }
        setUploads((u) => [...u, { id, name: file.name, progress: 0, state: "uploading" }]);
        try {
          // While the server indexes (inside the request on serverless hosts), keep refreshing the list
          // so its live progress bar shows.
          let poll: ReturnType<typeof setInterval> | undefined;
          await api.uploadDocument(
            file,
            (p) => setUploads((u) => u.map((x) => (x.id === id ? { ...x, progress: p } : x))),
            (stage) => {
              setUploads((u) => u.map((x) => (x.id === id ? { ...x, state: stage } : x)));
              if (stage === "indexing") poll = setInterval(() => void refresh(), 3000);
            },
          ).finally(() => poll && clearInterval(poll));
          setUploads((u) => u.filter((x) => x.id !== id));
          toast.success(`${file.name} uploaded and indexed.`);
          void refreshMe();
          await refresh();
        } catch (err) {
          const message = err instanceof ApiError ? err.message : "Upload failed.";
          setUploads((u) => u.map((x) => (x.id === id ? { ...x, state: "failed", error: message } : x)));
          toast.error(message);
        }
      }
    },
    [refresh],
  );

  const confirmDelete = async () => {
    if (!toDelete) return;
    setDeleting(true);
    try {
      await api.deleteDocument(toDelete.id);
      toast.success(`Deleted ${toDelete.filename}.`);
      setToDelete(null);
      await refresh();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Delete failed.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <section aria-labelledby="page-title" className="space-y-8">
      <header className="space-y-2">
        <h1 id="page-title" className="text-2xl font-semibold tracking-tight">
          Documents
        </h1>
        <p className="text-muted-foreground">
          Upload annual reports or import filings from SEC EDGAR. Parsing, embedding and indexing run locally on the server.
        </p>
      </header>

      <EdgarImport onImported={refresh} />

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void upload(e.dataTransfer.files);
        }}
        className={cn(
          "flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors",
          dragging ? "border-primary bg-accent" : "border-border",
        )}
      >
        <UploadCloud className="size-8 text-primary" aria-hidden />
        <div className="space-y-1">
          <p className="font-medium">Drag and drop files here</p>
          <p className="text-sm text-muted-foreground">PDF, HTML (e.g. a saved 10-K), TXT, Markdown or EPUB · up to {MAX_MB} MB each</p>
        </div>
        <Button variant="outline" onClick={() => inputRef.current?.click()}>
          Choose files
        </Button>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_TYPES.join(",")}
          multiple
          className="sr-only"
          aria-label="Choose files to upload"
          onChange={(e) => {
            if (e.target.files) void upload(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {uploads.length > 0 && (
        <ul className="space-y-3" aria-label="Uploads in progress">
          {uploads.map((u) => (
            <li key={u.id} className="rounded-lg border p-4">
              <div className="mb-2 flex items-center justify-between gap-4 text-sm">
                <span className="truncate font-medium">{u.name}</span>
                {u.state === "failed" ? (
                  <button
                    type="button"
                    className="text-xs text-muted-foreground underline-offset-4 hover:underline"
                    onClick={() => setUploads((x) => x.filter((y) => y.id !== u.id))}
                  >
                    Dismiss
                  </button>
                ) : (
                  <span className="inline-flex items-center gap-1.5 text-muted-foreground tabular-nums">
                    {u.state === "indexing" ? (
                      <>
                        <Loader2 className="size-3.5 animate-spin" aria-hidden /> Indexing…
                      </>
                    ) : (
                      `${Math.round(u.progress * 100)}%`
                    )}
                  </span>
                )}
              </div>
              {u.state === "failed" ? (
                <p className="text-sm text-destructive">{u.error}</p>
              ) : (
                <Progress value={u.progress * 100} aria-label={`Uploading ${u.name}`} />
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="space-y-3">
        <h2 className="text-sm font-medium text-muted-foreground">Your documents</h2>
        {docs === null ? (
          <div className="space-y-3">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : docs.length === 0 ? (
          <p className="rounded-lg border px-4 py-6 text-center text-sm text-muted-foreground">No documents yet.</p>
        ) : (
          <ul className="divide-y rounded-xl border">
            {docs.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
                <FileText className="size-5 shrink-0 text-muted-foreground" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{d.filename}</p>
                  <p className="text-xs text-muted-foreground">
                    {d.status === "ready"
                      ? `${d.pages} pages · ${d.chunks} chunks`
                      : d.status === "error"
                        ? d.error
                        : (d.stage ?? "Queued…")}
                    {" · "}
                    {new Date(d.created_at).toLocaleDateString()}
                  </p>
                  {d.suspicious_chunks > 0 && (
                    <p className="mt-1 flex items-center gap-1 text-xs text-destructive">
                      <AlertTriangle className="size-3" aria-hidden />
                      {d.suspicious_chunks} chunk{d.suspicious_chunks > 1 ? "s" : ""} contain instruction-like text (flagged)
                    </p>
                  )}
                </div>
                {d.status === "processing" && (
                  <Progress value={Math.round((d.progress ?? 0) * 100)} className="order-last h-1.5 w-full" aria-label={`Indexing ${d.filename}`} />
                )}
                {d.source_url && (
                  <a
                    href={d.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
                    title="Original filing on SEC EDGAR"
                  >
                    EDGAR <ExternalLink className="size-3" aria-hidden />
                  </a>
                )}
                <StatusBadge doc={d} />
                {d.protected || !(me && (d.owner_id === me.id || me.role === "admin")) ? (
                  <Badge variant="outline" title="Bundled sample document">
                    Sample
                  </Badge>
                ) : (
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => setToDelete(d)}
                    aria-label={`Delete ${d.filename}`}
                    disabled={d.status === "processing"}
                  >
                    <Trash2 aria-hidden />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <Dialog open={toDelete !== null} onOpenChange={(open) => !open && !deleting && setToDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete this document?</DialogTitle>
            <DialogDescription>
              {toDelete?.filename} and its {toDelete?.chunks ?? 0} indexed chunks will be removed. Cached answers are cleared.
              This can&apos;t be undone.
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
    </section>
  );
}
