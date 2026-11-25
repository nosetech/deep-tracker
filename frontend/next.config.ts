import type { NextConfig } from "next";

// ブラウザは常に Next.js 経由で /api/* にアクセスする。バックエンドへの中継は
// app/api/[...path]/route.ts が実行時の BACKEND_URL で行う（CORS不要）

// next dev は allowedDevOrigins 以外のホスト（LAN内の別端末など）からの /_next/* を拒否し、画面が描画されなくなる
const allowedDevOrigins = (process.env.ALLOWED_DEV_ORIGINS ?? "")
  .split(",")
  .map((h) => h.trim())
  .filter(Boolean);

// 動作確認用インスタンス（scripts/dev-instance.sh）は、運用のビルド成果物を壊さないよう別ディレクトリを使う
// 配布物は standalone 出力（node server.js で起動。利用者側で npm / ビルドは不要）。
// リリースのビルド（release.yml）だけ NEXT_OUTPUT=standalone で有効にする。通常のビルドで有効にすると、
// ソースのチェックアウトを起動する next start が「standalone では動かない」と警告するため
const nextConfig: NextConfig = {
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  allowedDevOrigins,
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
};

export default nextConfig;
