import type { NextConfig } from "next";

// The browser only talks to this Next.js origin; /api/* is proxied to FastAPI.
// Same-origin means the session cookie is first-party and no CORS is needed.
const API_ORIGIN = process.env.API_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // E2E builds into a separate folder so they never disturb a running `next dev` (.next).
  distDir: process.env.NEXT_DIST_DIR || ".next",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
};

export default nextConfig;
