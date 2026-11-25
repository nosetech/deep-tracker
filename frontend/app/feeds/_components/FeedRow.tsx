"use client";

import type { RefObject } from "react";
import type { Feed } from "@/lib/api/types";

export function formatInterval(m: number): string {
  return m < 60 ? `${m}分` : `${m / 60}時間`;
}

function formatShort(iso: string): string {
  const d = new Date(iso);
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const now = new Date();
  const dayKey = (x: Date) =>
    x.getFullYear() * 10000 + x.getMonth() * 100 + x.getDate();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (dayKey(d) === dayKey(now)) return `今日 ${hm}`;
  if (dayKey(d) === dayKey(yesterday)) return `昨日 ${hm}`;
  return `${d.getMonth() + 1}/${d.getDate()} ${hm}`;
}

function formatAgo(iso: string): string {
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "たった今";
  if (m < 60) return `${m}分前`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}時間前`;
  return `${Math.round(h / 24)}日前`;
}

export function MoreIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
    >
      <circle cx="5" cy="12" r="1.7" />
      <circle cx="12" cy="12" r="1.7" />
      <circle cx="19" cy="12" r="1.7" />
    </svg>
  );
}

type Props = {
  feed: Feed;
  busy: boolean;
  menuOpen: boolean;
  menuRef: RefObject<HTMLDivElement | null>;
  onToggleEnabled: () => void;
  onFetch: () => void;
  onToggleMenu: () => void;
  onEdit: () => void;
  onReadAll: () => void;
  onDelete: () => void;
};

/** 購読フィードの1行（グループの有無にかかわらず同じ見た目） */
export function FeedRow({
  feed: f,
  busy,
  menuOpen,
  menuRef,
  onToggleEnabled,
  onFetch,
  onToggleMenu,
  onEdit,
  onReadAll,
  onDelete,
}: Props) {
  const hasError = f.enabled && f.last_fetch_ok === false && !busy;
  const stColor = busy
    ? "var(--ac)"
    : !f.enabled
      ? "var(--tx3)"
      : f.last_fetch_ok === false
        ? "var(--err)"
        : f.last_fetch_ok
          ? "var(--ok)"
          : "var(--tx3)";
  const status = busy
    ? "取得中…"
    : !f.enabled
      ? "無効"
      : f.last_fetch_ok === false
        ? "エラー"
        : f.last_fetch_ok
          ? "正常"
          : "未取得";
  return (
    <div className="feed-row" style={{ opacity: f.enabled ? 1 : 0.62 }}>
      <div className="feed-main">
        <div className="feed-name">{f.name}</div>
        <div className="feed-url" title={f.url}>
          {f.url}
        </div>
        {hasError && f.last_fetch_error && (
          <div className="feed-error">{f.last_fetch_error}</div>
        )}
      </div>
      <div className="feed-status">
        <span className="feed-status-label" style={{ color: stColor }}>
          <span className="feed-status-dot" style={{ background: stColor }} />
          {status}
        </span>
        <span className="feed-sub">
          最終取得{" "}
          {f.last_fetched_at
            ? `${formatShort(f.last_fetched_at)}（${formatAgo(f.last_fetched_at)}）`
            : "—"}
        </span>
      </div>
      <div className="feed-counts">
        <span>
          記事 {f.article_count.toLocaleString("ja-JP")}件 · 未読{" "}
          <strong
            style={{
              color: f.unread_count ? "var(--ac)" : "var(--tx2)",
              fontWeight: 600,
            }}
          >
            {f.unread_count}
          </strong>
        </span>
        <span className="feed-sub">
          取得間隔 {formatInterval(f.effective_fetch_interval_minutes)}
        </span>
      </div>
      <div className="feed-actions" ref={menuOpen ? menuRef : undefined}>
        <button
          type="button"
          role="switch"
          aria-checked={f.enabled}
          aria-label="有効/無効"
          title={
            f.enabled ? "有効（クリックで無効化）" : "無効（クリックで有効化）"
          }
          className="switch"
          style={{ background: f.enabled ? "var(--ok)" : "var(--off)" }}
          onClick={onToggleEnabled}
        >
          <span className="switch-knob" style={{ left: f.enabled ? 19 : 3 }} />
        </button>
        <button
          type="button"
          className="btn-outline btn-sm"
          disabled={busy || !f.enabled}
          onClick={onFetch}
        >
          {busy ? "取得中…" : "今すぐ取得"}
        </button>
        <button
          type="button"
          className="btn-outline btn-icon"
          aria-label="その他の操作"
          aria-expanded={menuOpen}
          onClick={onToggleMenu}
        >
          <MoreIcon />
        </button>
        {menuOpen && (
          <div role="menu" className="feed-menu">
            <button type="button" role="menuitem" onClick={onEdit}>
              編集…
            </button>
            <button type="button" role="menuitem" onClick={onReadAll}>
              このフィードをすべて既読にする
            </button>
            <div className="feed-menu-sep" />
            <button
              type="button"
              role="menuitem"
              className="is-danger"
              onClick={onDelete}
            >
              削除…
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
