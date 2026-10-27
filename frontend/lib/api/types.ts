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

export type ArticleListItem = {
  id: number;
  feed_id: number;
  feed_name: string;
  title: string;
  url: string | null;
  excerpt: string | null;
  published_at: string | null;
  is_read: boolean;
};

export type ArticleNeighbor = {
  id: number;
  title: string;
};

export type ArticleDetail = {
  id: number;
  feed_id: number;
  feed_name: string;
  title: string;
  url: string | null;
  content: string | null;
  published_at: string | null;
  fetched_at: string;
  is_read: boolean;
  read_at: string | null;
  newer: ArticleNeighbor | null;
  older: ArticleNeighbor | null;
};

export type ArticleList = {
  items: ArticleListItem[];
  total: number;
  page: number;
  per_page: number;
};

export type ReadState = {
  id: number;
  is_read: boolean;
  read_at: string | null;
};

export type ArticleQuery = {
  unread_only?: boolean;
  feed_id?: number;
  since?: string;
  q?: string;
  page?: number;
  per_page?: number;
};

export type SummaryListItem = {
  id: number;
  kind: string;
  period_start: string;
  period_end: string;
  created_at: string;
  article_count: number;
  topic_count: number;
};

export type SummarySource = {
  id: number;
  title: string;
  url: string | null;
  feed_name: string;
  published_at: string | null;
  is_read: boolean;
};

export type SummaryTopic = {
  title: string;
  summary: string;
  sources: SummarySource[];
};

export type SummaryDetail = SummaryListItem & {
  overview: string;
  topics: SummaryTopic[];
  new_since: { count: number; unread_count: number };
  is_latest: boolean;
};

export type GenerationState = {
  state: "idle" | "running" | "failed";
  job_id: number | null;
  step: number;
  period_start: string | null;
  article_count: number | null;
  error: string | null;
  rate_limited: boolean;
  reset_text: string | null;
};

export type SummaryConfig = {
  interval: "daily" | "weekly" | "monthly";
  next_run_at: string;
};
