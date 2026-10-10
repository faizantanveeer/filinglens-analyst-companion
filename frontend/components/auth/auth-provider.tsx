"use client";

/**
 * Who is using the app: a guest on the free trial, or a signed-in account. Holds the server's view of
 * the user (role, credits) and the sign-up / log-in dialog. A 402 from any API call opens the dialog.
 */

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { toast } from "sonner";

import { AuthDialog } from "@/components/auth/auth-dialog";
import { api, ApiError, AUTH_EVENT, CREDITS_EVENT, ensureSession, setToken, type Me } from "@/lib/api";
import { clearGuestSettings, resetTokensUsed, setApiKey, setFallbackKey, setSearchKey, setSettingsAccount } from "@/lib/settings";

type Mode = "signup" | "login";

type AuthContextValue = {
  me: Me | null;
  refresh: () => Promise<void>;
  openAuth: (mode?: Mode, reason?: string) => void;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [dialog, setDialog] = useState<{ open: boolean; mode: Mode; reason?: string }>({ open: false, mode: "signup" });

  const refresh = useCallback(async () => {
    try {
      await ensureSession();
      const next = await api.me();
      setSettingsAccount(next.is_guest ? null : next.id); // each account has its own settings; guests get fresh ones per tab
      setMe(next);
    } catch (err) {
      if (err instanceof ApiError && err.status !== 0) toast.error(err.message);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const onCredits = (e: Event) => {
      const reason = (e as CustomEvent<string>).detail;
      setDialog({ open: true, mode: "signup", reason });
      void refresh();
    };
    window.addEventListener(AUTH_EVENT, refresh);
    window.addEventListener(CREDITS_EVENT, onCredits);
    return () => {
      window.removeEventListener(AUTH_EVENT, refresh);
      window.removeEventListener(CREDITS_EVENT, onCredits);
    };
  }, [refresh]);

  const openAuth = useCallback((mode: Mode = "signup", reason?: string) => setDialog({ open: true, mode, reason }), []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {}
    setApiKey(null); // on a shared computer, don't leave keys behind in this tab
    setFallbackKey(null);
    setSearchKey(null);
    resetTokensUsed();
    setSettingsAccount(null);
    clearGuestSettings(); // the next guest in this tab starts from defaults
    setToken(null); // a fresh guest session starts on the next request
    toast.success("Logged out.");
  }, []);

  return (
    <AuthContext.Provider value={{ me, refresh, openAuth, logout }}>
      {children}
      <AuthDialog
        open={dialog.open}
        mode={dialog.mode}
        reason={dialog.reason}
        isGuest={me?.is_guest ?? true}
        onModeChange={(mode) => setDialog((d) => ({ ...d, mode }))}
        onOpenChange={(open) => setDialog((d) => ({ ...d, open }))}
      />
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
