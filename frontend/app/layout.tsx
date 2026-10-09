import type { Metadata } from "next";
import { Inter } from "next/font/google";

import { AppShell } from "@/components/app-shell";
import { AuthProvider } from "@/components/auth/auth-provider";
import { ChatProvider } from "@/components/chat/chat-provider";
import { SessionsProvider } from "@/components/sessions/sessions-provider";
import { THEME_SCRIPT, ThemeProvider } from "@/components/theme";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "FilingLens",
  description: "Grounded Q&A over company annual reports",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning: THEME_SCRIPT may add the `dark` class before React hydrates.
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="font-sans">
        <ThemeProvider>
          <TooltipProvider>
            <AuthProvider>
              <SessionsProvider>
                <ChatProvider>
                  <AppShell>{children}</AppShell>
                </ChatProvider>
              </SessionsProvider>
            </AuthProvider>
          </TooltipProvider>
          <Toaster position="bottom-right" />
        </ThemeProvider>
      </body>
    </html>
  );
}
