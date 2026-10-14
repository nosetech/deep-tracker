import type { Feed, UnreadCounts } from "./types";

// ブラウザは常に Next.js 経由（/api/* → backend へ中継）でアクセスする
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    throw new ApiError(res.status, `API error: ${res.status} ${path}`);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export const api = {
  listFeeds: () => request<Feed[]>("/feeds"),
  getUnreadCounts: () => request<UnreadCounts>("/articles/unread-counts"),
};
