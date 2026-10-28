import { proxyToBackend } from "@/lib/backend-proxy";

// BACKEND_URL をビルド時ではなく実行時に読むため、常に動的に評価する
export const dynamic = "force-dynamic";

export {
  proxyToBackend as GET,
  proxyToBackend as POST,
  proxyToBackend as PATCH,
  proxyToBackend as PUT,
  proxyToBackend as DELETE,
};
