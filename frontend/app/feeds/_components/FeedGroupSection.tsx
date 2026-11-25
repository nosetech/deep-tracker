"use client";

import type { ReactNode, RefObject } from "react";
import type { Feed, FeedGroup } from "@/lib/api/types";
import { MoreIcon } from "./FeedRow";

type Props = {
  /** null は「未分類」 */
  group: FeedGroup | null;
  feeds: Feed[];
  expanded: boolean;
  menuOpen: boolean;
  menuRef: RefObject<HTMLDivElement | null>;
  onToggleExpanded: () => void;
  onToggleMenu: () => void;
  onRename: () => void;
  onSetEnabled: (enabled: boolean) => void;
  onReadAll: () => void;
  onDelete: () => void;
  children: ReactNode;
};

/** 購読フィード画面のグループ見出しと、その配下のフィード行 */
export function FeedGroupSection({
  group,
  feeds,
  expanded,
  menuOpen,
  menuRef,
  onToggleExpanded,
  onToggleMenu,
  onRename,
  onSetEnabled,
  onReadAll,
  onDelete,
  children,
}: Props) {
  const name = group?.name ?? "未分類";
  const isUncat = group === null;
  const enabled = feeds.filter((f) => f.enabled).length;
  const errors = feeds.filter(
    (f) => f.enabled && f.last_fetch_ok === false,
  ).length;
  const unread = feeds.reduce((n, f) => n + f.unread_count, 0);
  const empty = feeds.length === 0;
  return (
    <section aria-label={name} className="feed-group">
      <div className="feed-group-head" ref={menuOpen ? menuRef : undefined}>
        <button
          type="button"
          className="feed-group-toggle"
          aria-expanded={expanded}
          onClick={onToggleExpanded}
        >
          <span className="feed-group-title">
            <svg
              aria-hidden="true"
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="var(--tx2)"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="feed-group-chev"
              style={{ transform: `rotate(${expanded ? 0 : -90}deg)` }}
            >
              <path d="M6 9l6 6 6-6" />
            </svg>
            <span
              className="feed-group-name"
              style={{ color: isUncat ? "var(--tx2)" : "var(--tx)" }}
            >
              {name}
            </span>
          </span>
          <span className="feed-group-count">
            {feeds.length}件 · 有効 {enabled}件
            {errors > 0 && (
              <>
                {" · "}
                <span style={{ color: "var(--err)" }}>エラー {errors}件</span>
              </>
            )}
          </span>
        </button>
        <span className="feed-group-unread">
          未読{" "}
          <strong style={{ color: unread ? "var(--ac)" : "var(--tx2)" }}>
            {unread}
          </strong>
        </span>
        <button
          type="button"
          className="btn-outline btn-icon"
          aria-label={`${name} の操作`}
          aria-expanded={menuOpen}
          onClick={onToggleMenu}
        >
          <MoreIcon />
        </button>
        {menuOpen && (
          <div role="menu" className="feed-menu feed-group-menu">
            {!isUncat && (
              <button type="button" role="menuitem" onClick={onRename}>
                グループ名を変更
              </button>
            )}
            <button
              type="button"
              role="menuitem"
              disabled={empty}
              onClick={() => onSetEnabled(true)}
            >
              {isUncat ? "すべて有効にする" : "グループ内をすべて有効にする"}
            </button>
            <button
              type="button"
              role="menuitem"
              disabled={empty}
              onClick={() => onSetEnabled(false)}
            >
              {isUncat ? "すべて無効にする" : "グループ内をすべて無効にする"}
            </button>
            <button
              type="button"
              role="menuitem"
              disabled={empty}
              onClick={onReadAll}
            >
              {isUncat ? "すべて既読にする" : "グループ内をすべて既読にする"}
            </button>
            {!isUncat && (
              <>
                <div className="feed-menu-sep" />
                <button
                  type="button"
                  role="menuitem"
                  className="is-danger"
                  onClick={onDelete}
                >
                  グループを削除…
                </button>
              </>
            )}
          </div>
        )}
      </div>
      {expanded && (
        <>
          {empty && (
            <div className="feed-group-empty">
              このグループにはフィードがありません
            </div>
          )}
          {children}
        </>
      )}
    </section>
  );
}
