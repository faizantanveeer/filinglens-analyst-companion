"use client";

import { LogIn, LogOut, ShieldCheck, Sparkles } from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";

/** Sidebar foot: trial credits + sign-up for guests, account + log-out for members. */
export function AccountBox() {
  const { me, openAuth, logout } = useAuth();
  if (!me) return <Skeleton className="mx-3 mb-3 h-16" />;
  const { used, limit, remaining, period } = me.credits;
  const admin = me.role === "admin";

  return (
    <div className="space-y-2.5 border-t p-3">
      {me.is_guest ? (
        <>
          <div className="space-y-1.5 px-1">
            <p className="flex items-center justify-between text-xs">
              <span className="font-medium">Free trial</span>
              <span className="text-muted-foreground tabular-nums">
                {remaining} of {limit} questions left
              </span>
            </p>
            <Progress value={(used / limit) * 100} className="h-1.5" aria-label="Free questions used" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Button size="sm" onClick={() => openAuth("signup")}>
              <Sparkles aria-hidden /> Sign up
            </Button>
            <Button size="sm" variant="outline" onClick={() => openAuth("login")}>
              <LogIn aria-hidden /> Log in
            </Button>
          </div>
        </>
      ) : (
        <div className="flex items-center gap-2 px-1">
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-1 truncate text-sm font-medium" title={me.email ?? ""}>
              {admin && <ShieldCheck className="size-3.5 shrink-0 text-primary" aria-label="Admin" />}
              <span className="truncate">{me.email}</span>
            </p>
            <p className="text-xs text-muted-foreground tabular-nums">
              {admin ? "Admin · unlimited" : `${remaining} of ${limit} questions left this ${period}`}
            </p>
          </div>
          <Button variant="ghost" size="icon" onClick={() => void logout()} aria-label="Log out" title="Log out">
            <LogOut aria-hidden />
          </Button>
        </div>
      )}
    </div>
  );
}
