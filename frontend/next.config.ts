import type { NextConfig } from "next";

// ブラウザは常に Next.js 経由で /api/* にアクセスし、バックエンドへ中継する（CORS不要）
const backendUrl = process.env.BACKEND_URL ?? "http://127.0.0.1:8700";

// next dev は allowedDevOrigins 以外のホスト（LAN内の別端末など）からの /_next/* を拒否し、画面が描画されなくなる
const allowedDevOrigins = (process.env.ALLOWED_DEV_ORIGINS ?? "")
  .split(",")
  .map((h) => h.trim())
  .filter(Boolean);

// 動作確認用インスタンス（scripts/dev-instance.sh）は、運用のビルド成果物を壊さないよう別ディレクトリを使う
const nextConfig: NextConfig = {
  allowedDevOrigins,
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
};

export default nextConfig;
