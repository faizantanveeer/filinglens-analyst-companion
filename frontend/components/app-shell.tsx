"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { BarChart3, FileText, MessageSquare, PanelLeft, ScanSearch, Settings, X } from "lucide-react";

import { ApiStatus } from "@/components/api-status";
import { useChat } from "@/components/chat/chat-provider";
import { SessionList } from "@/components/sessions/session-list";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const SIDEBAR_KEY = "filinglens.sidebarOpen";
const focusRing = "outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50";

function Brand() {
  return (
    <Link href="/" aria-label="FilingLens home" className={cn("flex items-center gap-2 rounded-md font-semibold tracking-tight", focusRing)}>
      <ScanSearch className="size-5 text-primary" aria-hidden />
      <span>FilingLens</span>
    </Link>
  );
}

function Nav({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  const { sessionId } = useChat();
  // "Chat" returns to the open conversation rather than starting a new one.
  const items = [
    { href: sessionId ? `/c/${sessionId}` : "/", label: "Chat", icon: MessageSquare, active: pathname === "/" || pathname.startsWith("/c/") },
    { href: "/documents", label: "Documents", icon: FileText, active: pathname.startsWith("/documents") },
    { href: "/settings", label: "Settings", icon: Settings, active: pathname.startsWith("/settings") },
    { href: "/insights", label: "Insights", icon: BarChart3, active: pathname.startsWith("/insights") },
  ];
  return (
    <nav aria-label="Main" className="flex flex-col gap-0.5 p-3">
      {items.map(({ href, label, icon: Icon, active }) => (
        <Link
          key={label}
          href={href}
          onClick={onNavigate}
          aria-current={active ? "page" : undefined}
          className={cn(
            "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
            focusRing,
            active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
          )}
        >
          <Icon className="size-4 shrink-0" aria-hidden />
          {label}
        </Link>
      ))}
    </nav>
  );
}

/**
 * App layout. Desktop (md+): a sidebar (navigation + chat history) that can be closed completely
 * and reopened from the header or with Ctrl/⌘+B; the choice is remembered. Mobile: an overlay drawer.
 * Ctrl/⌘+K starts a new chat from anywhere.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { newChat } = useChat();
  const [desktopOpen, setDesktopOpen] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    try {
      if (localStorage.getItem(SIDEBAR_KEY) === "0") setDesktopOpen(false);
    } catch {}
  }, []);

  const toggle = useCallback(() => {
    if (window.matchMedia("(min-width: 768px)").matches) {
      setDesktopOpen((open) => {
        try {
          localStorage.setItem(SIDEBAR_KEY, open ? "0" : "1");
        } catch {}
        return !open;
      });
    } else {
      setMobileOpen((o) => !o);
    }
  }, []);

  useEffect(() => setMobileOpen(false), [pathname]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false);
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "b") {
        e.preventDefault();
        toggle();
      }
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        newChat();
        router.push("/");
        setTimeout(() => document.getElementById("question")?.focus(), 50);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle, newChat, router]);

  useEffect(() => {
    document.body.style.overflow = mobileOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [mobileOpen]);

  const toggleLabel = "Toggle sidebar (Ctrl+B)";

  return (
    <div className="flex min-h-dvh">
      {/* Desktop sidebar: fully closable */}
      <aside
        aria-label="Sidebar"
        className={cn(
          "sticky top-0 hidden h-dvh shrink-0 flex-col overflow-hidden border-r bg-sidebar transition-[width,border-color] duration-200 md:flex",
          desktopOpen ? "w-64" : "w-0 border-transparent",
        )}
        inert={!desktopOpen}
      >
        <div className="flex h-14 w-64 shrink-0 items-center justify-between border-b px-4">
          <Brand />
          <Button variant="ghost" size="icon" onClick={toggle} aria-label="Close sidebar (Ctrl+B)" title="Close sidebar (Ctrl+B)">
            <PanelLeft aria-hidden />
          </Button>
        </div>
        <div className="flex min-h-0 w-64 flex-1 flex-col">
          <Nav pathname={pathname} />
          <SessionList />
        </div>
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMobileOpen(false)} aria-hidden />
          <aside
            id="mobile-nav"
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col border-r bg-sidebar"
          >
            <div className="flex h-14 shrink-0 items-center justify-between border-b px-4">
              <Brand />
              <Button variant="ghost" size="icon" onClick={() => setMobileOpen(false)} aria-label="Close navigation">
                <X aria-hidden />
              </Button>
            </div>
            <Nav pathname={pathname} onNavigate={() => setMobileOpen(false)} />
            <SessionList onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b bg-background/95 px-4 backdrop-blur supports-backdrop-filter:bg-background/90 md:px-8">
          <Button
            variant="ghost"
            size="icon"
            onClick={toggle}
            aria-label={toggleLabel}
            title={toggleLabel}
            aria-controls="mobile-nav"
            aria-expanded={mobileOpen}
            className={cn("-ml-2", desktopOpen && "md:hidden")}
          >
            <PanelLeft aria-hidden />
          </Button>
          <div className={cn(desktopOpen && "md:hidden")}>
            <Brand />
          </div>
          <div className="ml-auto flex items-center gap-2">
            <ApiStatus />
            <ThemeToggle />
          </div>
        </header>
        <main className="mx-auto w-full max-w-4xl min-w-0 flex-1 px-4 pt-6 pb-12 md:px-8 md:pt-10">{children}</main>
      </div>
    </div>
  );
}
