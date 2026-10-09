"use client";

import { useCallback, useEffect, useState } from "react";
import { Brain, History, Loader2, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { useChat } from "@/components/chat/chat-provider";
import { useSessions } from "@/components/sessions/sessions-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { api, ApiError, type MemoryItem } from "@/lib/api";
import { useSettings } from "@/lib/settings";

/** A destructive button that asks for a second click within 4 s instead of opening a dialog. */
function ConfirmButton({ label, confirmLabel, onConfirm, disabled }: { label: string; confirmLabel: string; onConfirm: () => Promise<void>; disabled?: boolean }) {
  const [armed, setArmed] = useState(false);
  const [working, setWorking] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(false), 4000);
    return () => clearTimeout(t);
  }, [armed]);
  return (
    <Button
      variant={armed ? "destructive" : "outline"}
      size="sm"
      disabled={disabled || working}
      onClick={async () => {
        if (!armed) return setArmed(true);
        setWorking(true);
        await onConfirm();
        setWorking(false);
        setArmed(false);
      }}
    >
      {working ? <Loader2 className="animate-spin" aria-hidden /> : <Trash2 aria-hidden />}
      {armed ? confirmLabel : label}
    </Button>
  );
}

export function MemorySettings() {
  const { settings, update } = useSettings();
  const { removeAll, sessions } = useSessions();
  const { newChat } = useChat();
  const [items, setItems] = useState<MemoryItem[] | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await api.listMemories());
    } catch (err) {
      setItems([]);
      if (err instanceof ApiError && err.status !== 0) toast.error(err.message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, settings.use_memory]);

  const remove = async (id: number) => {
    setItems((xs) => xs?.filter((m) => m.id !== id) ?? xs);
    try {
      await api.deleteMemory(id);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Delete failed.");
      void load();
    }
  };

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Brain className="size-4 text-primary" aria-hidden /> Memory
          </CardTitle>
          <CardDescription>
            Each chat only sees its own history. With cross-chat memory on, FilingLens also remembers lasting preferences you mention
            (units, depth, companies you follow) and uses them to shape answers in other chats, never as a source of facts.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="flex items-start justify-between gap-6">
            <div className="space-y-1">
              <Label htmlFor="memory">Cross-chat memory</Label>
              <p className="text-xs text-muted-foreground">Off by default. Turning it off stops both saving and using memories.</p>
            </div>
            <Switch id="memory" checked={settings.use_memory} onCheckedChange={(v) => update({ use_memory: v })} />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium">Saved memories {items && items.length > 0 && <span className="text-muted-foreground">({items.length})</span>}</p>
              <ConfirmButton
                label="Clear all"
                confirmLabel="Click to confirm"
                disabled={!items?.length}
                onConfirm={async () => {
                  try {
                    const { deleted } = await api.clearMemories();
                    setItems([]);
                    toast.success(`Cleared ${deleted} memor${deleted === 1 ? "y" : "ies"}.`);
                  } catch (err) {
                    toast.error(err instanceof ApiError ? err.message : "Clear failed.");
                  }
                }}
              />
            </div>
            {items === null ? (
              <Skeleton className="h-16 w-full" />
            ) : items.length === 0 ? (
              <p className="rounded-lg border border-dashed px-4 py-5 text-center text-sm text-muted-foreground">
                {settings.use_memory ? "Nothing remembered yet. Mention a preference in any chat." : "No memories saved."}
              </p>
            ) : (
              <ul className="divide-y rounded-lg border">
                {items.map((m) => (
                  <li key={m.id} className="flex items-start gap-3 px-3 py-2.5">
                    <p className="min-w-0 flex-1 text-sm wrap-break-word">{m.content}</p>
                    <span className="shrink-0 pt-0.5 text-xs text-muted-foreground">{new Date(m.created_at).toLocaleDateString()}</span>
                    <button
                      type="button"
                      onClick={() => void remove(m.id)}
                      aria-label={`Forget: ${m.content}`}
                      className="shrink-0 rounded p-1 text-muted-foreground outline-none hover:bg-muted hover:text-destructive focus-visible:ring-2 focus-visible:ring-ring/50"
                    >
                      <Trash2 className="size-3.5" aria-hidden />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <History className="size-4 text-primary" aria-hidden /> Chat history
          </CardTitle>
          <CardDescription>
            Chats are saved on the FilingLens server for this browser only. Long chats stay fast: the last 4 exchanges are kept word
            for word and older ones are condensed into a short running summary, so follow-ups keep their context without resending the
            whole conversation.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ConfirmButton
            label={`Delete all chats${sessions?.length ? ` (${sessions.length})` : ""}`}
            confirmLabel="Click again to delete every chat"
            disabled={!sessions?.length}
            onConfirm={async () => {
              if (await removeAll()) newChat();
            }}
          />
        </CardContent>
      </Card>
    </>
  );
}
