"use client";

import { useEffect, useId, useState } from "react";
import { Eye, EyeOff, Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError, setToken } from "@/lib/api";

type Mode = "signup" | "login";

export function AuthDialog({
  open,
  mode,
  reason,
  isGuest,
  onModeChange,
  onOpenChange,
}: {
  open: boolean;
  mode: Mode;
  reason?: string;
  isGuest: boolean;
  onModeChange: (m: Mode) => void;
  onOpenChange: (open: boolean) => void;
}) {
  const id = useId();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (open) {
      setError("");
      setPassword("");
    }
  }, [open, mode]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = mode === "signup" ? await api.signup(email, password) : await api.login(email, password);
      setToken(r.token); // AuthProvider, chats and documents refresh on this event
      toast.success(mode === "signup" ? "Account created. Your trial chats and documents are saved to it." : `Welcome back, ${r.user.email}.`);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const signup = mode === "signup";
  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="size-4 text-primary" aria-hidden />
            {signup ? "Create your free account" : "Log in"}
          </DialogTitle>
          <DialogDescription>
            {reason ??
              (signup
                ? "Keep your documents and chats, and get a monthly allowance of questions."
                : "Pick up where you left off.")}
            {isGuest && " Anything from your trial carries over."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-4" noValidate>
          <div className="space-y-2">
            <Label htmlFor={`${id}-email`}>Email</Label>
            <Input
              id={`${id}-email`}
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              maxLength={254}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${id}-password`}>Password</Label>
            <div className="flex gap-2">
              <Input
                id={`${id}-password`}
                type={show ? "text" : "password"}
                autoComplete={signup ? "new-password" : "current-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                maxLength={128}
                aria-describedby={signup ? `${id}-pw-hint` : undefined}
              />
              <Button type="button" variant="outline" size="icon" onClick={() => setShow((s) => !s)} aria-label={show ? "Hide password" : "Show password"}>
                {show ? <EyeOff aria-hidden /> : <Eye aria-hidden />}
              </Button>
            </div>
            {signup && (
              <p id={`${id}-pw-hint`} className="text-xs text-muted-foreground">
                At least 10 characters, with an uppercase letter and a digit.
              </p>
            )}
          </div>
          {error && (
            <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={busy || !email || !password}>
            {busy && <Loader2 className="animate-spin" aria-hidden />}
            {signup ? "Create account" : "Log in"}
          </Button>
          <p className="text-center text-sm text-muted-foreground">
            {signup ? "Already have an account? " : "New here? "}
            <button type="button" className="font-medium text-primary underline-offset-4 hover:underline" onClick={() => onModeChange(signup ? "login" : "signup")}>
              {signup ? "Log in" : "Create an account"}
            </button>
          </p>
        </form>
      </DialogContent>
    </Dialog>
  );
}
