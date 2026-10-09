"use client";

/**
 * The open conversation. Each chat is a server-side session: turns are saved by the API, history
 * for follow-ups is loaded server-side (bounded by a rolling summary), and opening /c/<id>
 * restores the session. Kept above the routes so switching pages doesn't drop a streaming answer.
 */

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useRef, useState } from "react";
import { toast } from "sonner";

import { useSessions } from "@/components/sessions/sessions-provider";
import { api, ApiError, toRequestSettings, type StoredMessage } from "@/lib/api";
import { addTokensUsed, getSettings, getTokensUsed } from "@/lib/settings";
import type { AnswerType, ChartData, Citation, DoneEvent } from "@/lib/sse";

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: "streaming" | "done" | "error";
  deep?: boolean;
  step?: string;
  steps?: string[];
  citations?: Citation[];
  chart?: ChartData;
  suggestions?: string[];
  answerType?: AnswerType;
  meta?: DoneEvent;
  error?: string;
};

type ChatContextValue = {
  sessionId: string | null;
  messages: Message[];
  loading: boolean;
  busy: boolean;
  deep: boolean;
  setDeep: (v: boolean) => void;
  docScope: string[] | null; // documents this chat searches; null = all
  setDocScope: (ids: string[] | null) => void;
  send: (question: string, opts?: { deep?: boolean }) => Promise<void>;
  stop: () => void;
  newChat: () => void;
  openSession: (id: string) => Promise<void>;
};

const ChatContext = createContext<ChatContextValue | null>(null);

const uid = () => Math.random().toString(36).slice(2, 10);

function fromStored(m: StoredMessage): Message {
  const p = m.payload ?? {};
  return {
    id: String(m.id),
    role: m.role,
    content: m.content,
    status: "done",
    deep: p.deep,
    steps: p.steps,
    citations: p.citations,
    chart: p.chart,
    suggestions: p.suggestions,
    answerType: p.answer_type,
    meta: p.meta,
  };
}

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { refresh } = useSessions();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [deep, setDeep] = useState(false);
  const [docScope, setDocScope] = useState<string[] | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const loadRef = useRef<AbortController | null>(null);

  const patch = useCallback((id: string, fn: (m: Message) => Message) => {
    setMessages((ms) => ms.map((m) => (m.id === id ? fn(m) : m)));
  }, []);

  const newChat = useCallback(() => {
    abortRef.current?.abort();
    loadRef.current?.abort();
    setSessionId(null);
    setMessages([]);
    setLoading(false);
  }, []);

  const openSession = useCallback(
    async (id: string) => {
      abortRef.current?.abort();
      loadRef.current?.abort();
      const ctrl = new AbortController();
      loadRef.current = ctrl;
      setSessionId(id);
      setMessages([]);
      setLoading(true);
      try {
        const s = await api.getSession(id, ctrl.signal);
        if (!ctrl.signal.aborted) setMessages(s.messages.map(fromStored));
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        toast.error(err instanceof ApiError && err.status === 404 ? "That chat no longer exists." : "Couldn't open that chat.");
        setSessionId(null);
        router.replace("/");
      } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    },
    [router],
  );

  const send = useCallback(
    async (question: string, opts?: { deep?: boolean }) => {
      const q = question.trim();
      if (!q || busy) return;
      const useDeep = opts?.deep ?? deep;
      const botId = uid();
      setMessages((ms) => [
        ...ms,
        { id: uid(), role: "user", content: q, status: "done", deep: useDeep },
        { id: botId, role: "assistant", content: "", status: "streaming", step: "Starting…", steps: [], deep: useDeep },
      ]);
      setBusy(true);
      const ctrl = new AbortController();
      abortRef.current = ctrl;

      try {
        // First question of a new chat: create the session, then move the URL to it.
        let sid = sessionId;
        if (!sid) {
          sid = (await api.createSession()).id;
          setSessionId(sid);
          router.replace(`/c/${sid}`);
        }
        const body = {
          question: q,
          session_id: sid,
          deep: useDeep,
          doc_ids: docScope?.length ? docScope : null,
          settings: toRequestSettings(getSettings(), getTokensUsed()),
        };
        for await (const ev of api.chat(body, ctrl.signal)) {
          switch (ev.event) {
            case "step":
              patch(botId, (m) => ({ ...m, step: ev.data.label, steps: [...(m.steps ?? []), ev.data.label] }));
              break;
            case "token":
              patch(botId, (m) => ({ ...m, content: m.content + ev.data.text, step: undefined }));
              break;
            case "chart":
              patch(botId, (m) => ({ ...m, chart: ev.data.chart }));
              break;
            case "citations":
              patch(botId, (m) => ({ ...m, citations: ev.data.citations }));
              break;
            case "suggestions":
              patch(botId, (m) => ({ ...m, suggestions: ev.data.suggestions }));
              break;
            case "done":
              addTokensUsed(ev.data.usage.input_tokens + ev.data.usage.output_tokens);
              patch(botId, (m) => ({ ...m, status: "done", step: undefined, answerType: ev.data.answer_type, meta: ev.data }));
              if (ev.data.web_error) toast.warning(ev.data.web_error);
              break;
            case "error":
              patch(botId, (m) => ({ ...m, status: "error", step: undefined, error: ev.data.message }));
              toast.error(ev.data.message);
              break;
          }
        }
        patch(botId, (m) =>
          m.status === "streaming" ? { ...m, status: "error", step: undefined, error: "The answer stream ended unexpectedly." } : m,
        );
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          patch(botId, (m) => ({ ...m, status: "error", step: undefined, error: "Stopped." }));
        } else {
          const message = err instanceof ApiError ? err.message : "Something went wrong.";
          patch(botId, (m) => ({ ...m, status: "error", step: undefined, error: message }));
          toast.error(message);
        }
      } finally {
        setBusy(false);
        abortRef.current = null;
        void refresh(); // new title / updated order in the sidebar
      }
    },
    [busy, deep, docScope, patch, refresh, router, sessionId],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  return (
    <ChatContext.Provider value={{ sessionId, messages, loading, busy, deep, setDeep, docScope, setDocScope, send, stop, newChat, openSession }}>
      {children}
    </ChatContext.Provider>
  );
}

export function useChat() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChat must be used inside ChatProvider");
  return ctx;
}
