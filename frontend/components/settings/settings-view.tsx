"use client";

import { useEffect, useId, useState } from "react";
import { Eye, EyeOff, Globe, Loader2, PlugZap, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { MemorySettings } from "@/components/settings/memory-settings";
import { api, ApiError } from "@/lib/api";
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
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

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
  const { settings, update, tokensUsed } = useSettings();
  const [key, setKey] = useState("");
  const [fallbackKey, setFbKey] = useState("");
  const [testing, setTesting] = useState(false);
  const [searchKey, setSKey] = useState("");
  const [testingSearch, setTestingSearch] = useState(false);
  const isAzure = settings.provider === "azure";

  // Keys come from sessionStorage after mount (not available during server render).
  useEffect(() => {
    setKey(getApiKey() ?? "");
    setFbKey(getFallbackKey() ?? "");
    setSKey(getSearchKey() ?? "");
  }, []);

  const changeProvider = (p: Provider) => {
    const preset = PROVIDERS.find((x) => x.value === p)!;
    update({ provider: p, small_model: preset.small, large_model: preset.large });
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
      if (res.ok) toast.success(res.message);
      else toast.error(res.message);
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
              <Input id="small-model" value={settings.small_model} onChange={(e) => update({ small_model: e.target.value })} />
            </Field>
            <Field
              id="large-model"
              label={isAzure ? "Large model deployment" : "Large model"}
              hint={isAzure ? "Deployment name. Used for complex answers" : "Complex answers"}
            >
              <Input id="large-model" value={settings.large_model} onChange={(e) => update({ large_model: e.target.value })} />
            </Field>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={test} disabled={testing}>
              {testing ? <Loader2 className="animate-spin" aria-hidden /> : <PlugZap aria-hidden />}
              Test connection
            </Button>
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
          <CardDescription>Used if the primary model errors. Use a full name like openai/gpt-5-mini or ollama/llama3.1.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-6 sm:grid-cols-2">
          <Field id="fallback-model" label="Fallback model">
            <Input
              id="fallback-model"
              value={settings.fallback_model}
              placeholder="e.g. ollama/llama3.1"
              onChange={(e) => update({ fallback_model: e.target.value })}
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
