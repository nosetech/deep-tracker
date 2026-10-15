import type { BulkReadResult, Feed, FetchResult, UnreadCounts } from "./types";

// ブラウザは常に Next.js 経由（/api/* → backend へ中継）でアクセスする
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly code?: string,
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
    let code: string | undefined;
    let message = `API error: ${res.status} ${path}`;
    try {
      const body = await res.json();
      if (body?.detail?.code) code = body.detail.code;
      if (typeof body?.detail?.message === "string")
        message = body.detail.message;
    } catch {
      // 本文なし・JSON以外はステータスのみで扱う
    }
    throw new ApiError(res.status, message, code);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export const api = {
  listFeeds: () => request<Feed[]>("/feeds"),
  createFeed: (url: string) =>
    request<Feed>("/feeds", { method: "POST", body: JSON.stringify({ url }) }),
  updateFeed: (
    id: number,
    body: {
      name?: string;
      fetch_interval_minutes?: number | null;
      enabled?: boolean;
    },
  ) =>
    request<Feed>(`/feeds/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteFeed: (id: number) =>
    request<void>(`/feeds/${id}`, { method: "DELETE" }),
  fetchFeed: (id: number) =>
    request<FetchResult>(`/feeds/${id}/fetch`, { method: "POST" }),
  markFeedRead: (id: number) =>
    request<BulkReadResult>(`/feeds/${id}/mark-read`, { method: "POST" }),
  markUnread: (articleIds: number[]) =>
    request<BulkReadResult>("/articles/mark-unread", {
      method: "POST",
      body: JSON.stringify({ article_ids: articleIds }),
    }),
  getUnreadCounts: () => request<UnreadCounts>("/articles/unread-counts"),
};
