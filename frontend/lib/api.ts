/**
 * The one typed client for the FastAPI backend. Every request goes through `headers()`,
 * which attaches the session API keys when present. Keys are never logged.
 */

import { getApiKey, getClientId, getFallbackKey, getSearchKey, type AppSettings } from "./settings";
import { readSSE, type AnswerType, type ChartData, type ChatEvent, type Citation, type DoneEvent } from "./sse";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function headers(extra?: HeadersInit): Headers {
  const h = new Headers(extra);
  const key = getApiKey();
  const fallbackKey = getFallbackKey();
  if (key) h.set("X-LLM-Key", key);
  if (fallbackKey) h.set("X-LLM-Fallback-Key", fallbackKey);
  const searchKey = getSearchKey();
  if (searchKey) h.set("X-Search-Key", searchKey);
  const clientId = getClientId();
  if (clientId) h.set("X-Client-Id", clientId);
  return h;
}

async function errorFrom(res: Response): Promise<ApiError> {
  // FastAPI errors look like {"detail": "..."} (or a list for validation errors).
  const body = await res.json().catch(() => null);
  const detail = body?.detail;
  const message = typeof detail === "string" ? detail : Array.isArray(detail) ? detail[0]?.msg : res.statusText;
  return new ApiError(res.status, message || `Request failed (${res.status})`);
}

async function send(path: string, init: RequestInit = {}): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers: headers(init.headers) });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, "Cannot reach the FilingLens API. Is the backend running?");
  }
  if (!res.ok) throw await errorFrom(res);
  return res;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await send(path, init);
  return (res.status === 204 ? undefined : await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

// ---------- types ----------

export type Health = { status: "ok" };

export type DocumentInfo = {
  id: string;
  filename: string;
  status: "processing" | "ready" | "error";
  pages: number;
  chunks: number;
  suspicious_chunks: number;
  error: string | null;
  created_at: string;
  filetype?: string | null;
  progress?: number | null; // 0..1 while processing
  stage?: string | null; // e.g. "Indexed 48/152 pages · 130 chunks"
  source_url?: string | null; // set for filings imported from SEC EDGAR
  protected?: boolean | null; // the bundled sample in the public demo (can't be deleted)
};

export const ACCEPTED_TYPES = [".pdf", ".html", ".htm", ".txt", ".md", ".epub"];

/** URL of a rendered page with the cited passage highlighted (plain <img>, no headers needed). */
export function pageImageUrl(docId: string, page: number, highlight = ""): string {
  const q = highlight ? `?highlight=${encodeURIComponent(highlight.slice(0, 1500))}` : "";
  return `${API_URL}/documents/${encodeURIComponent(docId)}/pages/${page}.png${q}`;
}

export type Turn = { role: "user" | "assistant"; content: string };

export type SessionInfo = { id: string; title: string; created_at: string; updated_at: string; snippet?: string | null };

export type StoredMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  payload: {
    answer_type?: AnswerType;
    citations?: Citation[];
    chart?: ChartData;
    suggestions?: string[];
    meta?: DoneEvent;
    steps?: string[];
    deep?: boolean;
  } | null;
};

export type MemoryItem = { id: number; content: string; source_session: string | null; created_at: string };

export type Insights = {
  requests: number;
  total_cost: number;
  avg_tokens: number;
  cache_hit_rate: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  routes: { route: string; count: number }[];
  step_latency: { step: string; avg_ms: number }[];
  recent: {
    id: string;
    created_at: string;
    question: string;
    route: string;
    model: string;
    input_tokens: number;
    output_tokens: number;
    cost: number;
    latency_ms: number;
    cache_hit: number;
    verification: string;
  }[];
};

/** The settings shape the backend expects (no keys: those travel in headers). */
export function toRequestSettings(s: AppSettings, tokensUsed: number) {
  return {
    provider: s.provider,
    small_model: s.small_model,
    large_model: s.large_model,
    fallback_model: s.fallback_model || null,
    azure_endpoint: s.provider === "azure" ? s.azure_endpoint.trim() || null : null,
    azure_api_version: s.azure_api_version.trim() || "2024-10-21",
    top_k: s.top_k,
    use_cache: s.use_cache,
    use_guardrails: s.use_guardrails,
    use_judge: s.use_judge,
    use_web_search: s.use_web_search,
    use_memory: s.use_memory,
    explain_terms: s.explain_terms,
    token_budget_remaining: s.token_budget > 0 ? s.token_budget - tokensUsed : null,
  };
}

// ---------- endpoints ----------

export const api = {
  health: (signal?: AbortSignal) => request<Health>("/health", { signal }),

  listDocuments: (signal?: AbortSignal) => request<DocumentInfo[]>("/documents", { signal }),

  importFromEdgar: (ticker: string, form: string) =>
    request<DocumentInfo>("/documents/edgar", json({ ticker, form })),

  deleteDocument: (id: string) => request<void>(`/documents/${encodeURIComponent(id)}`, { method: "DELETE" }),

  /** XHR instead of fetch because fetch has no upload-progress events. */
  uploadDocument(file: File, onProgress: (fraction: number) => void): Promise<DocumentInfo> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_URL}/documents`);
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
      xhr.onerror = () => reject(new ApiError(0, "Upload failed: cannot reach the API."));
      xhr.onload = () => {
        let body: { detail?: string } | DocumentInfo | null = null;
        try {
          body = JSON.parse(xhr.responseText);
        } catch {}
        if (xhr.status >= 200 && xhr.status < 300) resolve(body as DocumentInfo);
        else reject(new ApiError(xhr.status, (body as { detail?: string })?.detail ?? "Upload failed."));
      };
      const form = new FormData();
      form.append("file", file);
      xhr.send(form);
    });
  },

  validateSettings: (s: AppSettings) =>
    request<{ ok: boolean; message: string; model?: string }>("/settings/validate", json({ settings: toRequestSettings(s, 0) })),

  validateSearch: () => request<{ ok: boolean; message: string }>("/settings/validate-search", { method: "POST" }),

  insights: (signal?: AbortSignal) => request<Insights>("/insights", { signal }),

  // ---- chat sessions (scoped to this browser's X-Client-Id) ----
  listSessions: (q = "", signal?: AbortSignal) =>
    request<SessionInfo[]>(`/sessions${q ? `?q=${encodeURIComponent(q)}` : ""}`, { signal }),
  createSession: () => request<SessionInfo>("/sessions", { method: "POST" }),
  getSession: (id: string, signal?: AbortSignal) =>
    request<SessionInfo & { messages: StoredMessage[] }>(`/sessions/${encodeURIComponent(id)}`, { signal }),
  renameSession: (id: string, title: string) =>
    request<{ ok: boolean }>(`/sessions/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  deleteSession: (id: string) => request<void>(`/sessions/${encodeURIComponent(id)}`, { method: "DELETE" }),
  deleteAllSessions: () => request<{ deleted: number }>("/sessions", { method: "DELETE" }),

  // ---- cross-chat memory ----
  listMemories: () => request<MemoryItem[]>("/memories"),
  deleteMemory: (id: number) => request<void>(`/memories/${id}`, { method: "DELETE" }),
  clearMemories: () => request<{ deleted: number }>("/memories", { method: "DELETE" }),

  /** POST /chat and yield typed SSE events as they arrive. */
  async *chat(
    body: {
      question: string;
      session_id: string | null;
      deep: boolean;
      doc_ids: string[] | null; // null = search every ready document
      settings: ReturnType<typeof toRequestSettings>;
    },
    signal?: AbortSignal,
  ): AsyncGenerator<ChatEvent> {
    const res = await send("/chat", { ...json(body), signal });
    if (!res.body) throw new ApiError(0, "The response had no body to stream.");
    yield* readSSE(res.body);
  },
};
