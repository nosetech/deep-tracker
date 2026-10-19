"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { SHELL_REFRESH_EVENT } from "@/components/AppShell";
import { useToast } from "@/components/Toast";
import { ApiErrorPanel, LoadingSkeleton } from "@/components/states";
import { api } from "@/lib/api/client";
import type { ArticleListItem, Feed } from "@/lib/api/types";

const PER_PAGE = 20;
const MORE_PER_PAGE = 100;

type Period = "all" | "1" | "3" | "7" | "30";

type Filter = {
  unreadOnly: boolean;
  feed: string;
  period: Period;
  q: string;
};

const INITIAL_FILTER: Filter = {
  unreadOnly: true,
  feed: "all",
  period: "all",
  q: "",
};

function dayKey(d: Date): number {
  return d.getFullYear() * 10000 + d.getMonth() * 100 + d.getDate();
}

function dayLabel(d: Date): string {
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (dayKey(d) === dayKey(now)) return "今日";
  if (dayKey(d) === dayKey(yesterday)) return "昨日";
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

function formatTime(d: Date): string {
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

// フィード本文由来の HTML タグ・実体参照を除いて抜粋用のテキストにする
function toPlainText(html: string): string {
  const doc = new DOMParser().parseFromString(html, "text/html");
  return (doc.body.textContent ?? "").replace(/\s+/g, " ").trim();
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

// 期間は取得のたびに現在時刻から算出する
function buildQuery(f: Filter) {
  return {
    feed_id: f.feed === "all" ? undefined : Number(f.feed),
    since:
      f.period === "all"
        ? undefined
        : new Date(Date.now() - Number(f.period) * 86400000).toISOString(),
    q: f.q || undefined,
    unread_only: f.unreadOnly,
  };
}

function refreshShell() {
  window.dispatchEvent(new Event(SHELL_REFRESH_EVENT));
}

type Group = { label: string; items: ArticleListItem[] };

function groupByDay(items: ArticleListItem[]): Group[] {
  const groups: Group[] = [];
  for (const a of items) {
    const label = a.published_at
      ? dayLabel(new Date(a.published_at))
      : "日付なし";
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.items.push(a);
    else groups.push({ label, items: [a] });
  }
  return groups;
}

export default function ArticlesPage() {
  const router = useRouter();
  const toast = useToast();
  const [feeds, setFeeds] = useState<Feed[] | null>(null);
  const [filter, setFilter] = useState<Filter>(INITIAL_FILTER);
  const [qInput, setQInput] = useState("");
  const [items, setItems] = useState<ArticleListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [unreadTotal, setUnreadTotal] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  // 絞り込み変更・再取得で古いレスポンスを捨てるための世代
  const generation = useRef(0);

  // 検索語はデバウンスして絞り込みに反映
  useEffect(() => {
    const t = setTimeout(() => {
      setFilter((f) =>
        f.q === qInput.trim() ? f : { ...f, q: qInput.trim() },
      );
    }, 300);
    return () => clearTimeout(t);
  }, [qInput]);

  useEffect(() => {
    api
      .listFeeds()
      .then(setFeeds)
      .catch(() => setFeeds([]));
  }, []);

  const load = useCallback(async () => {
    const gen = ++generation.current;
    const query = buildQuery(filter);
    setItems([]);
    setTotal(0);
    setLoaded(false);
    setLoadError(false);
    try {
      const [list, unread] = await Promise.all([
        api.listArticles({ ...query, per_page: PER_PAGE }),
        api.listArticles({ ...query, unread_only: true, per_page: 1 }),
      ]);
      if (gen !== generation.current) return;
      setItems(list.items);
      setTotal(list.total);
      setUnreadTotal(unread.total);
      setLoadError(false);
      setLoaded(true);
    } catch {
      if (gen !== generation.current) return;
      setLoadError(true);
      setLoaded(true);
    }
  }, [filter]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  // 未読のみ表示中は既読にした記事を一覧から外す
  const visible = useMemo(
    () => (filter.unreadOnly ? items.filter((a) => !a.is_read) : items),
    [items, filter.unreadOnly],
  );
  const groups = useMemo(() => groupByDay(visible), [visible]);
  const visibleUnread = useMemo(
    () => visible.filter((a) => !a.is_read),
    [visible],
  );
  const hasMore = items.length < total;
  const filterActive =
    filter.feed !== "all" || filter.period !== "all" || filter.q !== "";

  const loadMore = async () => {
    // 既読で外した分を除いた件数を、サーバー側の取得済み位置とみなす
    const gen = generation.current;
    const matched = filter.unreadOnly ? visible.length : items.length;
    // 既読で位置がずれても取りこぼさないよう、大きめの窓で取得して重複を除く
    const page = Math.floor(matched / MORE_PER_PAGE) + 1;
    setLoadingMore(true);
    try {
      const list = await api.listArticles({
        ...buildQuery(filter),
        page,
        per_page: MORE_PER_PAGE,
      });
      if (gen !== generation.current) return;
      setItems((cur) => {
        const seen = new Set(cur.map((a) => a.id));
        return [...cur, ...list.items.filter((a) => !seen.has(a.id))];
      });
      setTotal(
        list.total + (filter.unreadOnly ? items.length - visible.length : 0),
      );
    } catch {
      toast("記事の取得に失敗しました", "error");
    } finally {
      setLoadingMore(false);
    }
  };

  const applyRead = (ids: number[], isRead: boolean) => {
    const set = new Set(ids);
    setItems((cur) =>
      cur.map((a) => (set.has(a.id) ? { ...a, is_read: isRead } : a)),
    );
    setUnreadTotal((n) => Math.max(0, n + (isRead ? -ids.length : ids.length)));
  };

  const setOne = async (a: ArticleListItem, isRead: boolean) => {
    try {
      await api.setArticleRead(a.id, isRead);
    } catch {
      toast("既読状態の更新に失敗しました", "error");
      return false;
    }
    applyRead([a.id], isRead);
    refreshShell();
    return true;
  };

  const toggle = async (a: ArticleListItem) => {
    const next = !a.is_read;
    if (!(await setOne(a, next))) return;
    toast(next ? "既読にしました" : "未読に戻しました", "info", {
      label: "元に戻す",
      onClick: () => void setOne({ ...a, is_read: next }, a.is_read),
    });
  };

  const open = async (a: ArticleListItem) => {
    if (!a.is_read) void setOne(a, true);
    router.push(`/articles/${a.id}`);
  };

  const readAll = async () => {
    const ids = visibleUnread.map((a) => a.id);
    if (!ids.length) return;
    const results = await Promise.allSettled(
      ids.map((id) => api.setArticleRead(id, true)),
    );
    const done = ids.filter((_, i) => results[i].status === "fulfilled");
    if (done.length) {
      applyRead(done, true);
      refreshShell();
    }
    if (done.length < ids.length) {
      toast("一部の記事を既読にできませんでした", "error");
      if (!done.length) return;
    }
    toast(`${done.length}件を既読にしました`, "success", {
      label: "元に戻す",
      onClick: () =>
        void api
          .markUnread(done)
          .then(() => {
            applyRead(done, false);
            refreshShell();
            toast("既読を取り消しました");
          })
          .catch(() => toast("取り消しに失敗しました", "error")),
    });
  };

  const clearFilter = () => {
    setQInput("");
    setFilter((f) => ({ ...f, feed: "all", period: "all", q: "" }));
  };

  const noFeeds = feeds !== null && feeds.length === 0;
  const noArticles =
    feeds !== null && feeds.reduce((n, f) => n + f.article_count, 0) === 0;
  const hasFeeds = !noFeeds && !noArticles;

  let empty: {
    title: string;
    text: string;
    label: string;
    onClick: () => void;
  } | null = null;
  if (
    loaded &&
    !loadError &&
    visible.length === 0 &&
    !hasMore &&
    feeds !== null
  ) {
    if (noFeeds)
      empty = {
        title: "フィードが登録されていません",
        text: "購読したいサイトの RSS / Atom を登録すると、ここに新着記事が表示されます。",
        label: "フィードを登録する",
        onClick: () => router.push("/feeds"),
      };
    else if (noArticles)
      empty = {
        title: "まだ記事がありません",
        text: "次回の定期取得を待つか、購読フィード画面から「今すぐ取得」を実行してください。",
        label: "購読フィードを開く",
        onClick: () => router.push("/feeds"),
      };
    else if (filter.unreadOnly && !hasMore)
      empty = {
        title: "未読の記事はありません",
        text: filterActive
          ? "この条件の記事はすべて読みました。"
          : "すべての記事を読みました。今週のサマリで全体の流れを振り返れます。",
        label: "すべての記事を表示",
        onClick: () => setFilter((f) => ({ ...f, unreadOnly: false })),
      };
    else
      empty = {
        title: "条件に一致する記事はありません",
        text: "キーワードや期間、フィードの条件を変えてお試しください。",
        label: "条件をクリア",
        onClick: clearFilter,
      };
  }

  const shownCount = filter.unreadOnly
    ? total - (items.length - visible.length)
    : total;
  const resultLabel = `${shownCount}件${hasMore ? "中" : "を表示"}${
    hasMore ? ` ${visible.length}件を表示` : ""
  }${filter.unreadOnly ? "" : `（未読 ${unreadTotal}件）`}`;

  return (
    <div className="articles-page">
      <h1 className="page-title articles-title">記事一覧</h1>

      {loadError && <ApiErrorPanel onRetry={() => void load()} />}

      {!loaded && <LoadingSkeleton list />}

      {hasFeeds && !loadError && (
        <div className="art-filter">
          <div className="art-row">
            <div className="art-search">
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="var(--tx3)"
                strokeWidth="2"
                strokeLinecap="round"
              >
                <circle cx="11" cy="11" r="6.5" />
                <path d="M16 16l4 4" />
              </svg>
              <input
                type="search"
                value={qInput}
                onChange={(e) => setQInput(e.target.value)}
                placeholder="キーワードで検索（タイトル・本文）"
                aria-label="キーワード検索"
              />
            </div>
            <div className="art-seg" aria-label="表示切り替え">
              <button
                type="button"
                className={filter.unreadOnly ? "is-on" : ""}
                aria-pressed={filter.unreadOnly}
                onClick={() => setFilter((f) => ({ ...f, unreadOnly: true }))}
              >
                未読のみ（{unreadTotal}）
              </button>
              <button
                type="button"
                className={filter.unreadOnly ? "" : "is-on"}
                aria-pressed={!filter.unreadOnly}
                onClick={() => setFilter((f) => ({ ...f, unreadOnly: false }))}
              >
                すべて
              </button>
            </div>
          </div>
          <div className="art-row">
            <select
              className="art-select"
              value={filter.feed}
              onChange={(e) =>
                setFilter((f) => ({ ...f, feed: e.target.value }))
              }
              aria-label="フィードで絞り込み"
            >
              <option value="all">すべてのフィード</option>
              {(feeds ?? []).map((f) => (
                <option key={f.id} value={f.id}>
                  {truncate(f.name, 24)}
                </option>
              ))}
            </select>
            <select
              className="art-select art-select-period"
              value={filter.period}
              onChange={(e) =>
                setFilter((f) => ({ ...f, period: e.target.value as Period }))
              }
              aria-label="期間"
            >
              <option value="all">期間：すべて</option>
              <option value="1">過去24時間</option>
              <option value="3">過去3日</option>
              <option value="7">過去7日</option>
              <option value="30">過去30日</option>
            </select>
            <div className="art-spacer" />
            <button
              type="button"
              className="art-readall"
              disabled={visibleUnread.length === 0}
              onClick={() => void readAll()}
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M2 13l4 4 8-9M10 16l1 1 10-11" />
              </svg>
              表示中の{visibleUnread.length}件を既読にする
            </button>
          </div>
          <div className="art-result">
            <span>{resultLabel}</span>
            {filterActive && (
              <button type="button" className="art-link" onClick={clearFilter}>
                条件をクリア
              </button>
            )}
          </div>
        </div>
      )}

      {empty && (
        <div className="art-empty">
          <div className="art-empty-title">{empty.title}</div>
          <p>{empty.text}</p>
          <button
            type="button"
            className="art-empty-btn"
            onClick={empty.onClick}
          >
            {empty.label}
          </button>
        </div>
      )}

      {groups.map((g) => (
        <div key={g.label}>
          <div className="art-day">{g.label}</div>
          {g.items.map((a) => {
            const d = a.published_at ? new Date(a.published_at) : null;
            return (
              <div
                key={a.id}
                className={`art-item${a.is_read ? "" : " is-unread"}`}
              >
                <button
                  type="button"
                  className="art-open"
                  onClick={() => void open(a)}
                >
                  <span className="art-dot" aria-hidden="true" />
                  <span className="art-body">
                    <span className="art-title">{a.title}</span>
                    <span className="art-meta">
                      <span className="art-meta-feed">{a.feed_name}</span>
                      {d && (
                        <span className="art-meta-time">{formatTime(d)}</span>
                      )}
                    </span>
                    {a.excerpt && (
                      <span className="art-excerpt">
                        {toPlainText(a.excerpt)}
                      </span>
                    )}
                  </span>
                </button>
                <button
                  type="button"
                  className="art-toggle"
                  onClick={() => void toggle(a)}
                >
                  {a.is_read ? "未読に戻す" : "既読にする"}
                </button>
                <button
                  type="button"
                  className="art-toggle-m"
                  aria-label={a.is_read ? "未読に戻す" : "既読にする"}
                  onClick={() => void toggle(a)}
                >
                  <span className="art-check">
                    <svg
                      width="12"
                      height="12"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="3"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M5 12l5 5 9-10" />
                    </svg>
                  </span>
                </button>
              </div>
            );
          })}
        </div>
      ))}

      {hasMore && !loadError && (
        <div className="art-more">
          <button
            type="button"
            className="art-empty-btn"
            disabled={loadingMore}
            onClick={() => void loadMore()}
          >
            {loadingMore ? "読み込み中…" : "さらに表示"}
          </button>
        </div>
      )}
    </div>
  );
}
