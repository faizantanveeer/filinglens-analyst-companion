/**
 * The one typed client for the FastAPI backend. Every request goes through `headers()`,
 * which attaches the session API keys when present. Keys are never logged.
 */

import { getApiKey, getFallbackKey, getSearchKey, type AppSettings } from "./settings";
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
  const token = getToken();
  if (token) h.set("Authorization", `Bearer ${token}`);
  return h;
}

async function errorFrom(res: Response): Promise<ApiError> {
  // FastAPI errors look like {"detail": "..."} (or a list for validation errors).
  const body = await res.json().catch(() => null);
  const detail = body?.detail;
  const message = typeof detail === "string" ? detail : Array.isArray(detail) ? detail[0]?.msg : res.statusText;
  return new ApiError(res.status, message || `Request failed (${res.status})`);
}

// ---------- session token ----------
// Every visitor has a server-issued session: a guest one is created automatically on first use,
// and signing up / logging in replaces it. Kept in localStorage so it survives reloads and tabs.

const TOKEN_KEY = "filinglens.session";
export const AUTH_EVENT = "filinglens:auth"; // token changed (login, logout, new guest)
export const CREDITS_EVENT = "filinglens:credits"; // a 402: trial or allowance used up

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

/** notify=false for silent session plumbing (first guest session, expiry recovery): only real
 *  identity changes (log in / log out) should reset what's on screen. */
export function setToken(token: string | null, notify = true) {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {}
  if (notify) window.dispatchEvent(new Event(AUTH_EVENT));
}

let guestStarting: Promise<void> | null = null;

/** Make sure a session exists, starting a guest one if needed (shared by concurrent callers). */
export async function ensureSession(): Promise<void> {
  if (getToken()) return;
  guestStarting ??= (async () => {
    let res: Response;
    try {
      res = await fetch(`${API_URL}/auth/guest`, { method: "POST" });
    } catch {
      throw new ApiError(0, "Cannot reach the FilingLens API. Is the backend running?");
    }
    if (!res.ok) throw await errorFrom(res);
    setToken((await res.json()).token, false);
  })().finally(() => {
    guestStarting = null;
  });
  await guestStarting;
}

async function send(path: string, init: RequestInit = {}, retried = false): Promise<Response> {
  const isAuth = path.startsWith("/auth/") || path === "/health";
  if (!isAuth) await ensureSession();
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers: headers(init.headers) });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, "Cannot reach the FilingLens API. Is the backend running?");
  }
  if (res.status === 401 && !isAuth && !retried) {
    setToken(null, false); // expired or revoked: start a fresh guest session once and retry
    return send(path, init, true);
  }
  if (!res.ok) {
    const err = await errorFrom(res);
    if (res.status === 402) window.dispatchEvent(new CustomEvent(CREDITS_EVENT, { detail: err.message }));
    throw err;
  }
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
  owner_id?: string | null;
};

export const ACCEPTED_TYPES = [".pdf", ".html", ".htm", ".txt", ".md", ".epub"];

/** A rendered page with the cited passage highlighted, as a local object URL. Fetched with the
 *  session token (an <img src> can't send one), so other users can't load your pages. */
export async function fetchPageImage(docId: string, page: number, highlight = ""): Promise<string> {
  const q = highlight ? `?highlight=${encodeURIComponent(highlight.slice(0, 1500))}` : "";
  const res = await send(`/documents/${encodeURIComponent(docId)}/pages/${page}.png${q}`);
  return URL.createObjectURL(await res.blob());
}

export type Me = {
  id: string;
  email: string | null;
  role: "guest" | "user" | "admin";
  is_guest: boolean;
  credits: { used: number; limit: number; remaining: number; period: "trial" | "month" };
  limits: { questions: number; documents: number; upload_mb: number };
  documents: number;
};

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

  /**
   * Chunked upload: start → PUT pieces (≤ 4 MB each) → complete. Small pieces keep every request
   * under serverless body limits (Vercel: 4.5 MB). "complete" returns once the server has stored the
   * file; on serverless it also indexes inside that request, so it can take a minute or two.
   */
  async uploadDocument(
    file: File,
    onProgress: (fraction: number) => void,
    onStage?: (stage: "uploading" | "indexing") => void,
  ): Promise<DocumentInfo> {
    const start = await request<{ upload_id: string; chunk_size: number }>(
      "/uploads",
      json({ filename: file.name, size: file.size }),
    );
    const size = start.chunk_size;
    const pieces = Math.max(1, Math.ceil(file.size / size));
    for (let i = 0; i < pieces; i++) {
      await send(`/uploads/${start.upload_id}/${i}`, {
        method: "PUT",
        headers: { "Content-Type": "application/octet-stream" },
        body: file.slice(i * size, (i + 1) * size),
      });
      onProgress((i + 1) / pieces);
    }
    onStage?.("indexing");
    return request<DocumentInfo>(`/uploads/${start.upload_id}/complete`, json({ filename: file.name }));
  },

  validateSettings: (s: AppSettings) =>
    request<{ ok: boolean; message: string; model?: string }>("/settings/validate", json({ settings: toRequestSettings(s, 0) })),

  validateSearch: () => request<{ ok: boolean; message: string }>("/settings/validate-search", { method: "POST" }),

  insights: (signal?: AbortSignal) => request<Insights>("/insights", { signal }),

  // ---- auth ----
  me: () => request<Me>("/auth/me"),
  signup: (email: string, password: string) => request<{ token: string; user: Me }>("/auth/signup", json({ email, password })),
  login: (email: string, password: string) => request<{ token: string; user: Me }>("/auth/login", json({ email, password })),
  logout: () => request<void>("/auth/logout", { method: "POST" }),

  // ---- chat sessions (scoped to the signed-in user or guest) ----
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
