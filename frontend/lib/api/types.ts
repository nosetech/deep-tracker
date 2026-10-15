// backend (FastAPI) のレスポンスに対応する型。backend/deep_tracker/api/ の pydantic モデルと揃える。

export type Feed = {
  id: number;
  name: string;
  url: string;
  enabled: boolean;
  fetch_interval_minutes: number | null;
  effective_fetch_interval_minutes: number;
  article_count: number;
  unread_count: number;
  created_at: string;
  last_fetched_at: string | null;
  last_fetch_ok: boolean | null;
  last_fetch_error: string | null;
};

export type FeedUnreadCount = {
  feed_id: number;
  unread: number;
};

export type UnreadCounts = {
  total: number;
  feeds: FeedUnreadCount[];
};

export type FetchResult = {
  added: number;
  feed: Feed;
};

export type BulkReadResult = {
  count: number;
  article_ids: number[];
};
