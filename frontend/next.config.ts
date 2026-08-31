import type { NextConfig } from "next";

const backendUrl =
  process.env.BACKEND_INTERNAL_URL ||
  process.env.BACKEND_API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8000/api/v1";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  async rewrites() {
    if (!backendUrl.startsWith("http://") && !backendUrl.startsWith("https://")) {
      return [];
    }
    const cleanUrl = backendUrl.replace(/\/+$/, "");
    const destination = cleanUrl.endsWith("/api/v1")
      ? `${cleanUrl}/:path*`
      : `${cleanUrl}/api/v1/:path*`;
    return [
      {
        source: "/api/v1/:path*",
        destination,
      },
    ];
  },
};

export default nextConfig;
