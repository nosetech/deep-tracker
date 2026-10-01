import type { NextConfig } from "next";

// ブラウザは常に Next.js 経由で /api/* にアクセスし、バックエンドへ中継する（CORS不要）
const backendUrl = process.env.BACKEND_URL ?? "http://127.0.0.1:8700";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
};

export default nextConfig;
