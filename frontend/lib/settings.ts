/**
 * Client settings.
 *
 * - API keys live ONLY in sessionStorage: gone when the tab closes, never in localStorage
 *   or cookies, never logged. They are sent per request as X-LLM-Key / X-LLM-Fallback-Key.
 * - Non-secret preferences (provider, models, toggles) go to localStorage for convenience.
 */

"use client";

import { useCallback, useSyncExternalStore } from "react";

export type Provider = "openai" | "azure" | "anthropic" | "gemini" | "groq" | "ollama";

export type AppSettings = {
  provider: Provider;
  small_model: string;
  large_model: string;
  fallback_model: string;
  azure_endpoint: string; // Azure OpenAI only (not secret)
  azure_api_version: string;
  top_k: number;
  token_budget: number; // per browser session, 0 = unlimited
  use_cache: boolean;
  use_guardrails: boolean;
  use_judge: boolean;
  use_web_search: boolean; // auto: only when the documents can't answer
  use_memory: boolean; // cross-chat memory, opt-in
  explain_terms: boolean; // plain-English key terms under answers
};

export const PROVIDERS: { value: Provider; label: string; small: string; large: string }[] = [
  { value: "openai", label: "OpenAI", small: "gpt-5-mini", large: "gpt-5" },
  // Azure: "models" are your deployment names; these are just common defaults.
  { value: "azure", label: "Azure OpenAI", small: "gpt-4o-mini", large: "gpt-4o" },
  { value: "anthropic", label: "Anthropic", small: "claude-haiku-4-5", large: "claude-sonnet-5-5" },
  { value: "gemini", label: "Google Gemini", small: "gemini-2.5-flash", large: "gemini-2.5-pro" },
  { value: "groq", label: "Groq", small: "llama-3.1-8b-instant", large: "llama-3.3-70b-versatile" },
  { value: "ollama", label: "Ollama (local)", small: "llama3.1", large: "llama3.1" },
];

export const DEFAULT_SETTINGS: AppSettings = {
  provider: "openai",
  small_model: PROVIDERS[0].small,
  large_model: PROVIDERS[0].large,
  fallback_model: "",
  azure_endpoint: "",
  azure_api_version: "2024-10-21",
  top_k: 5,
  token_budget: 50000,
  use_cache: true,
  use_guardrails: true,
  use_judge: false,
  use_web_search: true,
  use_memory: false,
  explain_terms: true,
};

const PREFS = "filinglens.settings";
const API_KEY = "filinglens.llmKey";
const FALLBACK_KEY = "filinglens.llmFallbackKey";
const SEARCH_KEY = "filinglens.searchKey";
const TOKENS_USED = "filinglens.tokensUsed";

// ---- tiny external store so every component sees changes immediately ----
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

function read(storage: "local" | "session", key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return (storage === "local" ? window.localStorage : window.sessionStorage).getItem(key);
  } catch {
    return null;
  }
}

function write(storage: "local" | "session", key: string, value: string | null) {
  try {
    const s = storage === "local" ? window.localStorage : window.sessionStorage;
    if (value === null || value === "") s.removeItem(key);
    else s.setItem(key, value);
  } catch {}
  notify();
}

let cachedRaw: string | null | undefined;
let cachedSettings: AppSettings = DEFAULT_SETTINGS;
export function getSettings(): AppSettings {
  const raw = read("local", PREFS);
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    try {
      cachedSettings = { ...DEFAULT_SETTINGS, ...(raw ? JSON.parse(raw) : {}) };
    } catch {
      cachedSettings = DEFAULT_SETTINGS;
    }
  }
  return cachedSettings;
}

export function saveSettings(next: AppSettings) {
  write("local", PREFS, JSON.stringify(next));
}

export const getApiKey = () => read("session", API_KEY);
export const setApiKey = (key: string | null) => write("session", API_KEY, key);
export const getFallbackKey = () => read("session", FALLBACK_KEY);
export const setFallbackKey = (key: string | null) => write("session", FALLBACK_KEY, key);

export const getSearchKey = () => read("session", SEARCH_KEY);
export const setSearchKey = (key: string | null) => write("session", SEARCH_KEY, key);

export const getTokensUsed = () => Number(read("session", TOKENS_USED) ?? 0) || 0;
export const addTokensUsed = (n: number) => write("session", TOKENS_USED, String(getTokensUsed() + n));
export const resetTokensUsed = () => write("session", TOKENS_USED, null);

/** React hook: settings + whether a key is present + session token usage. */
export function useSettings() {
  const settings = useSyncExternalStore(subscribe, getSettings, () => DEFAULT_SETTINGS);
  const hasKey = useSyncExternalStore(subscribe, () => Boolean(getApiKey()), () => false);
  const tokensUsed = useSyncExternalStore(subscribe, getTokensUsed, () => 0);
  const hasSearchKey = useSyncExternalStore(subscribe, () => Boolean(getSearchKey()), () => false);
  const update = useCallback((patch: Partial<AppSettings>) => saveSettings({ ...getSettings(), ...patch }), []);
  const ready = hasKey || settings.provider === "ollama";
  const webSearch = settings.use_web_search && hasSearchKey;
  return { settings, update, hasKey, ready, tokensUsed, hasSearchKey, webSearch };
}
