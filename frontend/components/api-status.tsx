"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { api } from "@/lib/api";

const RETRY_OFFLINE_MS = 3000; // the API can take ~15 s to boot, so keep checking until it answers
const RECHECK_ONLINE_MS = 30000; // and notice if it goes away later

/** Badge shown only while the backend doesn't answer /health; nothing is shown when it's online. */
export function ApiStatus() {
  const [state, setState] = useState<"loading" | "online" | "offline">("loading");
  const [since, setSince] = useState<number | null>(null); // when the current outage started

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let ctrl: AbortController;
    let warned = false;

    const check = async () => {
      ctrl = new AbortController();
      try {
        await api.health(ctrl.signal);
        setState("online");
        setSince(null);
        warned = false;
        timer = setTimeout(check, RECHECK_ONLINE_MS);
      } catch {
        if (ctrl.signal.aborted) return;
        setState("offline");
        setSince((s) => s ?? Date.now());
        if (!warned) {
          // The hosted backend runs on a free tier that sleeps when idle; say so instead of just "error".
          toast.info("Connecting to the FilingLens API… If it was asleep, it can take a minute or two to wake up.", { duration: 8000 });
          warned = true; // one toast per outage, not one per retry
        }
        timer = setTimeout(check, RETRY_OFFLINE_MS);
      }
    };
    void check();
    return () => {
      clearTimeout(timer);
      ctrl?.abort();
    };
  }, []);

  if (state !== "offline") return null;

  return (
    <span
      role="status"
      className="inline-flex items-center gap-2 rounded-full border px-2.5 py-0.5 text-xs text-muted-foreground"
    >
      <span
        aria-hidden
        className="size-2 rounded-full bg-destructive"
      />
      {since && Date.now() - since < 180_000 ? "Waking API…" : "API offline"}
    </span>
  );
}
