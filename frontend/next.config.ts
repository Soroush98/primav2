import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle (.next/standalone) for a small container image.
  output: "standalone",
};

export default nextConfig;
