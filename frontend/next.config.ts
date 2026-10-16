import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Overridable so a verification build never overwrites the output a running `next start` is serving.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
