import { networkInterfaces } from "node:os";
import type { NextConfig } from "next";

// Set only in the single-container image (Dockerfile.space): the browser calls /api/*
// on the same origin and Next.js forwards it to FastAPI.
const backend = process.env.BACKEND_INTERNAL_URL;

// Opening the dev server via this machine's LAN address (the "Network:" URL) is a different
// origin than localhost, and Next blocks its dev resources (HMR) for other origins. Allow only
// this machine's own IPv4 addresses, plus any extra hosts in ALLOWED_DEV_ORIGINS (comma-separated).
const ownAddresses = Object.values(networkInterfaces())
  .flat()
  .filter((a) => a && a.family === "IPv4" && !a.internal)
  .map((a) => a!.address);
const extraDevOrigins = (process.env.ALLOWED_DEV_ORIGINS ?? "").split(",").map((s) => s.trim()).filter(Boolean);

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  output: "standalone",
  // gzip can buffer the proxied SSE stream; the Space image streams chat through this proxy.
  compress: !backend,
  // A stray package-lock.json in the home folder made Next guess the wrong workspace root.
  // `next dev` / `next build` always run from frontend/, so pin the root there.
  turbopack: { root: process.cwd() },
  allowedDevOrigins: [...ownAddresses, ...extraDevOrigins],
  // Don't let `next dev` write AGENTS.md into the project.
  agentRules: false,
  async rewrites() {
    return backend ? [{ source: "/api/:path*", destination: `${backend}/:path*` }] : [];
  },
};

export default nextConfig;
