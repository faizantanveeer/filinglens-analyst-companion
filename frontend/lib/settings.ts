/**
 * Client settings.
 *
 * - API keys live ONLY in sessionStorage: gone when the tab closes, never in localStorage
 *   or cookies, never logged. They are sent per request as X-LLM-Key / X-LLM-Fallback-Key.
 * - Non-secret preferences (provider, models, endpoint, toggles) belong to whoever is using the app:
 *   a signed-in account keeps them in localStorage under its own id; a guest keeps them in
 *   sessionStorage, so every new guest, tab or window starts from clean defaults.
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
  alert_tokens: number; // warn once usage passes this many tokens, 0 = off
  alert_cost: number; // warn once estimated spend passes this many USD, 0 = off
  use_cache: boolean;
  use_guardrails: boolean;
  use_judge: boolean;
  use_web_search: boolean; // auto: only when the documents can't answer
  use_memory: boolean; // cross-chat memory, opt-in
  explain_terms: boolean; // plain-English key terms under answers
};

export type ModelOption = { id: string; note: string };

/**
 * Suggested models per provider (checked against each provider's docs, October 2026). Users can also
 * type any name, or load the exact list their key can use (Settings → "Load from your account").
 * `small` / `large` are the defaults for the two tiers.
 */
export const PROVIDERS: { value: Provider; label: string; small: string; large: string; models: ModelOption[] }[] = [
  {
    value: "openai",
    label: "OpenAI",
    small: "gpt-5.6-luna",
    large: "gpt-5.6-terra",
    models: [
      { id: "gpt-5.6-sol", note: "Flagship, most capable" },
      { id: "gpt-5.6-terra", note: "Balanced (mini tier)" },
      { id: "gpt-5.6-luna", note: "Fastest, cheapest (nano tier)" },
      { id: "gpt-6-luna", note: "GPT-6, efficient" },
      { id: "gpt-5.5", note: "Previous flagship" },
      { id: "gpt-5.4-mini", note: "Previous mini" },
      { id: "gpt-5.4-nano", note: "Previous nano" },
    ],
  },
  {
    value: "azure",
    label: "Azure OpenAI",
    // Azure: "models" are your deployment names; these are the usual names for these models.
    small: "gpt-5.6-luna",
    large: "gpt-5.6-terra",
    models: [
      { id: "gpt-5.6-sol", note: "Flagship (fewer regions)" },
      { id: "gpt-5.6-terra", note: "Balanced" },
      { id: "gpt-5.6-luna", note: "Fastest, cheapest" },
      { id: "gpt-5.5", note: "Previous flagship" },
    ],
  },
  {
    value: "anthropic",
    label: "Anthropic",
    small: "claude-haiku-4-5",
    large: "claude-sonnet-5-5",
    models: [
      { id: "claude-fable-5-1", note: "Most capable, priciest" },
      { id: "claude-opus-5-5", note: "Opus, most capable everyday" },
      { id: "claude-opus-5", note: "Previous Opus" },
      { id: "claude-opus-4-8", note: "Older Opus" },
      { id: "claude-sonnet-5-5", note: "Sonnet, fast and capable" },
      { id: "claude-sonnet-5", note: "Previous Sonnet" },
      { id: "claude-sonnet-4-6", note: "Older Sonnet" },
      { id: "claude-haiku-5-5", note: "Haiku, fastest, cheapest" },
      { id: "claude-haiku-4-5", note: "Previous Haiku" },
    ],
  },
  {
    value: "gemini",
    label: "Google Gemini",
    small: "gemini-3.1-flash-lite",
    large: "gemini-3.8-flash",
    models: [
      { id: "gemini-3.8-flash", note: "Newest Flash, most capable stable" },
      { id: "gemini-3.6-flash", note: "Previous Flash" },
      { id: "gemini-3.1-pro-preview", note: "Pro (preview)" },
      { id: "gemini-3.1-flash-lite", note: "Fastest, cheapest" },
    ],
  },
  {
    value: "groq",
    label: "Groq",
    small: "openai/gpt-oss-20b",
    large: "openai/gpt-oss-120b",
    models: [
      { id: "openai/gpt-oss-120b", note: "Most capable" },
      { id: "openai/gpt-oss-20b", note: "Fastest" },
      { id: "qwen/qwen3.8-27b", note: "Qwen (preview)" },
    ],
  },
  {
    value: "ollama",
    label: "Ollama (local)",
    small: "llama3.1",
    large: "llama3.1",
    models: [
      { id: "llama3.1", note: "8B, the most-pulled model" },
      { id: "llama3.2", note: "3B, small and quick" },
      { id: "qwen3.6", note: "27B, strong general and coding" },
      { id: "gpt-oss:20b", note: "OpenAI open weights" },
      { id: "gemma4", note: "Google, with thinking" },
      { id: "gemma3", note: "Google, small sizes" },
      { id: "deepseek-r1", note: "Reasoning" },
    ],
  },
];

// Earlier default pairs, now retired or about to be. Settings still on one of these exact pairs move
// to the current defaults; anything the user picked themselves is left alone.
const OLD_DEFAULTS: Partial<Record<Provider, [string, string][]>> = {
  openai: [["gpt-5-mini", "gpt-5"]],
  azure: [["gpt-4o-mini", "gpt-4o"]],
  gemini: [["gemini-2.5-flash", "gemini-2.5-pro"]],
  groq: [["llama-3.1-8b-instant", "llama-3.3-70b-versatile"]],
};

function upgradeDefaults(s: AppSettings): AppSettings {
  const preset = PROVIDERS.find((p) => p.value === s.provider);
  const old = OLD_DEFAULTS[s.provider]?.some(([small, large]) => s.small_model === small && s.large_model === large);
  return preset && old ? { ...s, small_model: preset.small, large_model: preset.large } : s;
}

export const DEFAULT_SETTINGS: AppSettings = {
  provider: "openai",
  small_model: PROVIDERS[0].small,
  large_model: PROVIDERS[0].large,
  fallback_model: "",
  azure_endpoint: "",
  azure_api_version: "2024-10-21",
  top_k: 5,
  token_budget: 50000,
  alert_tokens: 25000,
  alert_cost: 0.5,
  use_cache: true,
  use_guardrails: true,
  use_judge: false,
  use_web_search: true,
  use_memory: false,
  explain_terms: true,
};

const PREFS = "fincite.settings"; // guest: sessionStorage; account: localStorage + ".<user id>"
const API_KEY = "fincite.llmKey";
const FALLBACK_KEY = "fincite.llmFallbackKey";
const SEARCH_KEY = "fincite.searchKey";
const TOKENS_USED = "fincite.tokensUsed";
const COST_USED = "fincite.costUsed";

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

// Whose settings are active. Until /auth/me answers, treat the visitor as a guest.
let accountId: string | null = null;
const prefsLocation = (): ["local" | "session", string] => (accountId ? ["local", `${PREFS}.${accountId}`] : ["session", PREFS]);

// Older versions kept one shared copy in localStorage, which leaked one visitor's provider and
// endpoint to the next. Drop it.
if (typeof window !== "undefined") {
  try {
    window.localStorage.removeItem(PREFS);
  } catch {}
}

/** Switch settings to this account (or to the tab's guest settings when null). A guest who signs up
 *  or logs in into an account with nothing saved yet keeps the choices made during the trial. */
export function setSettingsAccount(id: string | null) {
  if (id === accountId) return;
  if (id && !read("local", `${PREFS}.${id}`)) {
    const guest = read("session", PREFS);
    if (guest) write("local", `${PREFS}.${id}`, guest);
  }
  accountId = id;
  notify();
}

/** Forget the guest's settings in this tab (on log-out, so the next guest starts clean). */
export const clearGuestSettings = () => write("session", PREFS, null);

let cachedRaw: string | null | undefined;
let cachedSettings: AppSettings = DEFAULT_SETTINGS;
export function getSettings(): AppSettings {
  const raw = read(...prefsLocation());
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    try {
      cachedSettings = upgradeDefaults({ ...DEFAULT_SETTINGS, ...(raw ? JSON.parse(raw) : {}) });
    } catch {
      cachedSettings = DEFAULT_SETTINGS;
    }
  }
  return cachedSettings;
}

export function saveSettings(next: AppSettings) {
  write(...prefsLocation(), JSON.stringify(next));
}

export const getApiKey = () => read("session", API_KEY);
export const setApiKey = (key: string | null) => write("session", API_KEY, key);
export const getFallbackKey = () => read("session", FALLBACK_KEY);
export const setFallbackKey = (key: string | null) => write("session", FALLBACK_KEY, key);

export const getSearchKey = () => read("session", SEARCH_KEY);
export const setSearchKey = (key: string | null) => write("session", SEARCH_KEY, key);

export const getTokensUsed = () => Number(read("session", TOKENS_USED) ?? 0) || 0;
export const addTokensUsed = (n: number) => write("session", TOKENS_USED, String(getTokensUsed() + n));
export const getCostUsed = () => Number(read("session", COST_USED) ?? 0) || 0;
export const resetTokensUsed = () => {
  write("session", COST_USED, null);
  write("session", TOKENS_USED, null);
};

/** Add one answer's usage; returns the alerts it just crossed (each fires once until usage is reset). */
export function recordUsage(tokens: number, cost: number): string[] {
  const s = getSettings();
  const t0 = getTokensUsed(), c0 = getCostUsed();
  const t1 = t0 + tokens, c1 = c0 + cost;
  write("session", COST_USED, String(c1));
  addTokensUsed(tokens);
  const alerts: string[] = [];
  if (s.alert_tokens > 0 && t0 < s.alert_tokens && t1 >= s.alert_tokens)
    alerts.push(`You've used ${t1.toLocaleString()} tokens this session (alert at ${s.alert_tokens.toLocaleString()}).`);
  if (s.alert_cost > 0 && c0 < s.alert_cost && c1 >= s.alert_cost)
    alerts.push(`Estimated spend this session is $${c1.toFixed(2)} (alert at $${s.alert_cost.toFixed(2)}).`);
  if (s.token_budget > 0 && t0 < s.token_budget * 0.8 && t1 >= s.token_budget * 0.8 && t1 < s.token_budget)
    alerts.push(`80% of your session token budget is used (${t1.toLocaleString()} of ${s.token_budget.toLocaleString()}).`);
  return alerts;
}

/** React hook: settings + whether a key is present + session token usage. */
export function useSettings() {
  const settings = useSyncExternalStore(subscribe, getSettings, () => DEFAULT_SETTINGS);
  const hasKey = useSyncExternalStore(subscribe, () => Boolean(getApiKey()), () => false);
  const tokensUsed = useSyncExternalStore(subscribe, getTokensUsed, () => 0);
  const costUsed = useSyncExternalStore(subscribe, getCostUsed, () => 0);
  const hasSearchKey = useSyncExternalStore(subscribe, () => Boolean(getSearchKey()), () => false);
  const update = useCallback((patch: Partial<AppSettings>) => saveSettings({ ...getSettings(), ...patch }), []);
  const ready = hasKey || settings.provider === "ollama";
  const webSearch = settings.use_web_search && hasSearchKey;
  return { settings, update, hasKey, ready, tokensUsed, costUsed, hasSearchKey, webSearch };
}
