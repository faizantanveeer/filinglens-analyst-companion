"use client";

/** The sidebar's list of chat sessions: search, refresh, rename, delete. Data lives on the server. */

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { api, ApiError, AUTH_EVENT, type SessionInfo } from "@/lib/api";

type SessionsContextValue = {
  sessions: SessionInfo[] | null; // null while the first load is in flight
  query: string;
  setQuery: (q: string) => void;
  refresh: () => Promise<void>;
  rename: (id: string, title: string) => Promise<boolean>;
  remove: (id: string) => Promise<boolean>;
  removeAll: () => Promise<boolean>;
};

const SessionsContext = createContext<SessionsContextValue | null>(null);

export function SessionsProvider({ children }: { children: React.ReactNode }) {
  const [sessions, setSessions] = useState<SessionInfo[] | null>(null);
  const [query, setQuery] = useState("");
  const queryRef = useRef("");
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async (q: string) => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const list = await api.listSessions(q, ctrl.signal);
      if (!ctrl.signal.aborted) setSessions(list);
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      setSessions((s) => s ?? []);
      // The API-status badge already reports an offline backend; don't toast on every keystroke.
      if (err instanceof ApiError && err.status !== 0) toast.error(err.message);
    }
  }, []);

  // Debounced search; empty query lists everything.
  useEffect(() => {
    queryRef.current = query;
    const t = setTimeout(() => void load(query), query ? 250 : 0);
    return () => clearTimeout(t);
  }, [query, load]);

  const refresh = useCallback(() => load(queryRef.current), [load]);

  useEffect(() => {
    const onAuth = () => {
      setSessions(null);
      void load(queryRef.current);
    };
    window.addEventListener(AUTH_EVENT, onAuth);
    return () => window.removeEventListener(AUTH_EVENT, onAuth);
  }, [load]);

  const rename = useCallback(
    async (id: string, title: string) => {
      const t = title.trim();
      if (!t) return false;
      setSessions((s) => s?.map((x) => (x.id === id ? { ...x, title: t } : x)) ?? s); // optimistic
      try {
        await api.renameSession(id, t);
        return true;
      } catch (err) {
        toast.error(err instanceof ApiError ? err.message : "Rename failed.");
        void refresh();
        return false;
      }
    },
    [refresh],
  );

  const remove = useCallback(async (id: string) => {
    try {
      await api.deleteSession(id);
      setSessions((s) => s?.filter((x) => x.id !== id) ?? s);
      return true;
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Delete failed.");
      return false;
    }
  }, []);

  const removeAll = useCallback(async () => {
    try {
      const { deleted } = await api.deleteAllSessions();
      setSessions([]);
      toast.success(`Deleted ${deleted} chat${deleted === 1 ? "" : "s"}.`);
      return true;
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Delete failed.");
      return false;
    }
  }, []);

  return (
    <SessionsContext.Provider value={{ sessions, query, setQuery, refresh, rename, remove, removeAll }}>{children}</SessionsContext.Provider>
  );
}

export function useSessions() {
  const ctx = useContext(SessionsContext);
  if (!ctx) throw new Error("useSessions must be used inside SessionsProvider");
  return ctx;
}
