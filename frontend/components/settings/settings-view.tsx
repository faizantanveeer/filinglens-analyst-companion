"use client";

import { useEffect, useId, useState } from "react";
import { Eye, EyeOff, Globe, ListRestart, Loader2, PlugZap, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { MemorySettings } from "@/components/settings/memory-settings";
import { ModelPicker } from "@/components/settings/model-picker";
import { api, ApiError, AUTH_EVENT } from "@/lib/api";
import {
  getApiKey,
  getFallbackKey,
  getSearchKey,
  PROVIDERS,
  resetTokensUsed,
  setApiKey,
  setFallbackKey,
  setSearchKey,
  useSettings,
  type Provider,
} from "@/lib/settings";

function SecretInput({
  label,
  value,
  onChange,
  placeholder,
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  hint?: string;
}) {
  const id = useId();
  const [shown, setShown] = useState(false);
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex gap-2">
        <Input
          id={id}
          type={shown ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          autoComplete="off"
          spellCheck={false}
          aria-describedby={hint ? `${id}-hint` : undefined}
        />
        <Button type="button" variant="outline" size="icon" onClick={() => setShown((s) => !s)} aria-label={shown ? `Hide ${label}` : `Show ${label}`}>
          {shown ? <EyeOff aria-hidden /> : <Eye aria-hidden />}
        </Button>
      </div>
      {hint && (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
    </div>
  );
}

function Field({ label, hint, children, id }: { label: string; hint?: string; children: React.ReactNode; id: string }) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {hint && (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
    </div>
  );
}

// Fallback suggestions: every provider's models, written with their provider prefix (Azure needs its own endpoint, so it's left out).
const FALLBACK_SUGGESTIONS = PROVIDERS.filter((p) => p.value !== "azure").flatMap((p) =>
  p.models.map((m) => ({ id: `${p.value}/${m.id}`, note: `${p.label} · ${m.note}` })),
);

function Toggle({ id, label, hint, checked, onChange }: { id: string; label: string; hint: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-start justify-between gap-6">
      <div className="space-y-1">
        <Label htmlFor={id}>{label}</Label>
        <p className="text-xs text-muted-foreground">{hint}</p>
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onChange} />
    </div>
  );
}

export function SettingsView() {
  const { settings, update, tokensUsed, costUsed } = useSettings();
  const [key, setKey] = useState("");
  const [fallbackKey, setFbKey] = useState("");
  const [testing, setTesting] = useState(false);
  const [searchKey, setSKey] = useState("");
  const [testingSearch, setTestingSearch] = useState(false);
  const [available, setAvailable] = useState<string[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const isAzure = settings.provider === "azure";
  const preset = PROVIDERS.find((p) => p.value === settings.provider)!;

  // Keys come from sessionStorage after mount (not available during server render).
  // Re-read after log-in / log-out too: logging out clears the keys, and the form must not keep showing them.
  useEffect(() => {
    const load = () => {
      setKey(getApiKey() ?? "");
      setFbKey(getFallbackKey() ?? "");
      setSKey(getSearchKey() ?? "");
    };
    load();
    window.addEventListener(AUTH_EVENT, load);
    return () => window.removeEventListener(AUTH_EVENT, load);
  }, []);

  const changeProvider = (p: Provider) => {
    const next = PROVIDERS.find((x) => x.value === p)!;
    update({ provider: p, small_model: next.small, large_model: next.large });
    setAvailable([]); // the loaded list belonged to the previous provider
  };

  /** Ask the provider which chat models this key can use. quiet: no toast on success (after a connection test). */
  const loadModels = async (quiet = false) => {
    setLoadingModels(true);
    try {
      const res = await api.listModels(settings);
      setAvailable(res.models);
      if (res.message) toast.error(res.message);
      else if (!quiet) toast.success(`${res.models.length} models available to your key. Pick one from the model lists.`);
    } catch (err) {
      if (!quiet) toast.error(err instanceof ApiError ? err.message : "Couldn't load the model list.");
    } finally {
      setLoadingModels(false);
    }
  };

  const testSearch = async () => {
    setTestingSearch(true);
    try {
      const res = await api.validateSearch();
      if (res.ok) toast.success(res.message);
      else toast.error(res.message);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Web search test failed.");
    } finally {
      setTestingSearch(false);
    }
  };

  const test = async () => {
    setTesting(true);
    try {
      if (isAzure && !settings.azure_endpoint.trim()) {
        toast.error("Add your Azure endpoint first.");
        return;
      }
      const res = await api.validateSettings(settings);
      if (res.ok) {
        toast.success(res.message);
        if (!isAzure) void loadModels(true);
      } else toast.error(res.message);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Connection test failed.");
    } finally {
      setTesting(false);
    }
  };

  const num = (v: string, min: number, max: number) => Math.min(max, Math.max(min, Number.parseInt(v, 10) || min));

  return (
    <section aria-labelledby="page-title" className="space-y-8">
      <header className="space-y-2">
        <h1 id="page-title" className="text-2xl font-semibold tracking-tight">
          Settings
        </h1>
        <p className="text-muted-foreground">Changes save automatically.</p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Model provider</CardTitle>
          <CardDescription className="flex items-start gap-2">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
            Your key stays in this browser tab only (sessionStorage) and is sent with each request. The server never stores or logs it.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <Field id="provider" label="Provider">
            <Select value={settings.provider} onValueChange={(v) => changeProvider(v as Provider)}>
              <SelectTrigger id="provider" className="w-full sm:w-64">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PROVIDERS.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <SecretInput
            label="API key"
            value={key}
            onChange={(v) => {
              setKey(v);
              setApiKey(v.trim() || null);
            }}
            placeholder={settings.provider === "ollama" ? "Not needed for local Ollama" : "Paste your key"}
          />

          {isAzure && (
            <div className="grid gap-6 sm:grid-cols-[2fr_1fr]">
              <Field id="azure-endpoint" label="Azure endpoint" hint="Azure portal → your OpenAI resource → Keys and Endpoint">
                <Input
                  id="azure-endpoint"
                  type="url"
                  value={settings.azure_endpoint}
                  placeholder="https://<resource>.openai.azure.com"
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(e) => update({ azure_endpoint: e.target.value })}
                />
              </Field>
              <Field id="azure-version" label="API version">
                <Input
                  id="azure-version"
                  value={settings.azure_api_version}
                  spellCheck={false}
                  onChange={(e) => update({ azure_api_version: e.target.value })}
                />
              </Field>
            </div>
          )}

          <div className="grid gap-6 sm:grid-cols-2">
            <Field
              id="small-model"
              label={isAzure ? "Small model deployment" : "Small model"}
              hint={isAzure ? "Deployment name from Azure AI Foundry. Used for routing, rewriting, judging" : "Routing, rewriting, calculation prep, judging"}
            >
              <ModelPicker
                id="small-model"
                value={settings.small_model}
                onChange={(v) => update({ small_model: v })}
                suggested={preset.models}
                available={available}
                describedBy="small-model-hint"
              />
            </Field>
            <Field
              id="large-model"
              label={isAzure ? "Large model deployment" : "Large model"}
              hint={isAzure ? "Deployment name. Used for complex answers" : "Complex answers"}
            >
              <ModelPicker
                id="large-model"
                value={settings.large_model}
                onChange={(v) => update({ large_model: v })}
                suggested={preset.models}
                available={available}
                describedBy="large-model-hint"
              />
            </Field>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={test} disabled={testing}>
              {testing ? <Loader2 className="animate-spin" aria-hidden /> : <PlugZap aria-hidden />}
              Test connection
            </Button>
            {!isAzure && (
              <Button variant="outline" onClick={() => loadModels()} disabled={loadingModels || (!key && settings.provider !== "ollama")}>
                {loadingModels ? <Loader2 className="animate-spin" aria-hidden /> : <ListRestart aria-hidden />}
                Load from your account
              </Button>
            )}
            {key && (
              <Button
                variant="ghost"
                onClick={() => {
                  setKey("");
                  setApiKey(null);
                }}
              >
                Clear key
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Globe className="size-4 text-primary" aria-hidden /> Web search
          </CardTitle>
          <CardDescription>
            Runs automatically only when your documents can&apos;t answer. Answers from the web are labelled and link to their sources.
            Uses Tavily (free tier: 1,000 searches/month at tavily.com).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <Toggle
            id="web-search"
            label="Web search (auto)"
            hint={searchKey ? "On: used as a fallback, never for facts your documents contain." : "Add a Tavily key below to enable."}
            checked={settings.use_web_search}
            onChange={(v) => update({ use_web_search: v })}
          />
          <SecretInput
            label="Tavily API key"
            value={searchKey}
            onChange={(v) => {
              setSKey(v);
              setSearchKey(v.trim() || null);
            }}
            placeholder="tvly-…"
            hint="Kept only in this browser tab, like your model key."
          />
          <Button variant="outline" onClick={testSearch} disabled={testingSearch || !searchKey}>
            {testingSearch ? <Loader2 className="animate-spin" aria-hidden /> : <PlugZap aria-hidden />}
            Test web search
          </Button>
        </CardContent>
      </Card>

      <MemorySettings />

      <Card>
        <CardHeader>
          <CardTitle>Fallback (optional)</CardTitle>
          <CardDescription>
            Used if the primary model errors. Use a full name with its provider, like anthropic/claude-haiku-4-5 or ollama/llama3.1.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-6 sm:grid-cols-2">
          <Field id="fallback-model" label="Fallback model">
            <ModelPicker
              id="fallback-model"
              value={settings.fallback_model}
              placeholder="e.g. ollama/llama3.1"
              onChange={(v) => update({ fallback_model: v })}
              suggested={FALLBACK_SUGGESTIONS}
            />
          </Field>
          <SecretInput
            label="Fallback API key"
            value={fallbackKey}
            onChange={(v) => {
              setFbKey(v);
              setFallbackKey(v.trim() || null);
            }}
            placeholder="Only for a different provider"
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Retrieval & limits</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid gap-6 sm:grid-cols-2">
            <Field id="top-k" label="Chunks per answer (top_k)" hint="1–10. More context finds more, but costs more tokens.">
              <Input
                id="top-k"
                type="number"
                min={1}
                max={10}
                value={settings.top_k}
                onChange={(e) => update({ top_k: num(e.target.value, 1, 10) })}
              />
            </Field>
            <Field id="budget" label="Session token budget" hint={`0 = unlimited. Used so far: ${tokensUsed.toLocaleString()}.`}>
              <div className="flex gap-2">
                <Input
                  id="budget"
                  type="number"
                  min={0}
                  step={1000}
                  value={settings.token_budget}
                  onChange={(e) => update({ token_budget: num(e.target.value, 0, 10_000_000) })}
                />
                <Button variant="outline" onClick={resetTokensUsed} disabled={tokensUsed === 0}>
                  Reset
                </Button>
              </div>
            </Field>
            <Field id="alert-tokens" label="Alert after tokens" hint="Get a notification when this session's usage passes this. 0 = off.">
              <Input
                id="alert-tokens"
                type="number"
                min={0}
                step={1000}
                value={settings.alert_tokens}
                onChange={(e) => update({ alert_tokens: num(e.target.value, 0, 10_000_000) })}
              />
            </Field>
            <Field id="alert-cost" label="Alert after spend (USD)" hint={`Estimated from list prices. Spent so far: $${costUsed.toFixed(4)}. 0 = off.`}>
              <Input
                id="alert-cost"
                type="number"
                min={0}
                step={0.1}
                value={settings.alert_cost}
                onChange={(e) => update({ alert_cost: Math.max(0, Math.min(10_000, Number(e.target.value) || 0)) })}
              />
            </Field>
          </div>
          <div className="space-y-5 border-t pt-6">
            <Toggle
              id="cache"
              label="Semantic cache"
              hint="Reuse answers to near-identical questions over the same documents (0 tokens)."
              checked={settings.use_cache}
              onChange={(v) => update({ use_cache: v })}
            />
            <Toggle
              id="guardrails"
              label="Input guardrails"
              hint="Block prompt-injection attempts and redact emails, phone and card numbers before the LLM sees them."
              checked={settings.use_guardrails}
              onChange={(v) => update({ use_guardrails: v })}
            />
            <Toggle
              id="key-terms"
              label="Explain key terms"
              hint="Adds plain-English definitions of jargon (float, GAAP, underwriting…) under answers, labelled as general knowledge."
              checked={settings.explain_terms}
              onChange={(v) => update({ explain_terms: v })}
            />
            <Toggle
              id="judge"
              label="Faithfulness judge"
              hint="Small model double-checks complex answers. Costs extra tokens."
              checked={settings.use_judge}
              onChange={(v) => update({ use_judge: v })}
            />
          </div>
        </CardContent>
      </Card>
    </section>
  );
}
