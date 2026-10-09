"use client";

import Link from "next/link";
import { ChevronsUpDown, LogIn, LogOut, Settings, ShieldCheck, Sparkles, UserRound } from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

function Avatar({ className }: { className?: string }) {
  return (
    <span className={cn("grid size-8 shrink-0 place-items-center rounded-full bg-primary/10 text-primary", className)} aria-hidden>
      <UserRound className="size-4" />
    </span>
  );
}

/** Profile icon that opens the account menu (email, Settings, Log out). `compact` = icon only, for the rail. */
export function ProfileMenu({ compact = false }: { compact?: boolean }) {
  const { me, logout } = useAuth();
  if (!me || me.is_guest) return null;
  const admin = me.role === "admin";
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Profile"
          title="Profile"
          className={cn(
            "flex items-center gap-2 rounded-md text-sm outline-none transition-colors hover:bg-muted focus-visible:ring-[3px] focus-visible:ring-ring/50 data-[state=open]:bg-muted",
            compact ? "size-10 justify-center" : "w-full px-2 py-1.5",
          )}
        >
          <Avatar />
          {!compact && (
            <>
              <span className="flex-1 text-left font-medium">Profile</span>
              <ChevronsUpDown className="size-3.5 text-muted-foreground" aria-hidden />
            </>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side={compact ? "right" : "top"} align={compact ? "end" : "start"} className="w-60">
        <DropdownMenuLabel className="flex items-center gap-2">
          <Avatar />
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium" title={me.email ?? ""}>
              {me.email}
            </span>
            <span className="flex items-center gap-1 text-xs font-normal text-muted-foreground">
              {admin && <ShieldCheck className="size-3 text-primary" aria-hidden />}
              {admin ? "Admin" : "Free account"}
            </span>
          </span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/settings">
            <Settings aria-hidden /> Settings
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem variant="destructive" onSelect={() => void logout()}>
          <LogOut aria-hidden /> Log out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Sidebar foot: trial credits + sign-up for guests, the profile menu for members. */
export function AccountBox() {
  const { me, openAuth } = useAuth();
  if (!me) return <Skeleton className="mx-3 mb-3 h-12" />;

  if (!me.is_guest) {
    return (
      <div className="border-t p-2">
        <ProfileMenu />
      </div>
    );
  }

  const { used, limit, remaining } = me.credits;
  return (
    <div className="space-y-2.5 border-t p-3">
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
    </div>
  );
}
