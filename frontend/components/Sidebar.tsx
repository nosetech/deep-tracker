"use client";

import Link from "next/link";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import {
  PEEK_CLOSE_DELAY_MS,
  PEEK_OPEN_DELAY_MS,
  SIDEBAR_STORAGE_KEY,
  parseCollapsed,
  serializeCollapsed,
} from "@/lib/sidebar-state";
import { ICONS, NAV, type NavKey } from "./nav";

function formatLastFetch(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

// 折りたたみ中はラベルが見えないので、ツールチップに未読・エラーの件数も含める
function navTitle(
  key: NavKey,
  label: string,
  unread: number,
  errorCount: number,
): string {
  if (key === "articles" && unread > 0) return `${label}（未読 ${unread}件）`;
  if (key === "feeds" && errorCount > 0) {
    return `${label}（取得エラー ${errorCount}件）`;
  }
  return label;
}

function CollapseIcon({ collapsed }: { collapsed: boolean }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M9 4v16" />
      <path d={collapsed ? "M14 10l2 2-2 2" : "M16 10l-2 2 2 2"} />
    </svg>
  );
}

// 折りたたみ状態の正は <html data-sidebar>（hydration 前スクリプトが保存値から設定する）。
// サーバー描画時は展開として扱い、CSS が属性で見た目を決めるので初回表示でちらつかない
const collapseListeners = new Set<() => void>();

function subscribeCollapsed(cb: () => void) {
  collapseListeners.add(cb);
  return () => {
    collapseListeners.delete(cb);
  };
}

function applyCollapsed(next: boolean) {
  if (next) document.documentElement.dataset.sidebar = "collapsed";
  else delete document.documentElement.dataset.sidebar;
  collapseListeners.forEach((cb) => cb());
}

function readCollapsed() {
  return document.documentElement.dataset.sidebar === "collapsed";
}

type Props = {
  active: NavKey;
  unread: number;
  errorCount: number;
  lastFetch: string | null;
};

// 折りたたみの見た目は <html data-sidebar="collapsed"> を起点に CSS で決める
// （hydration 前に sidebarInitScript が属性を付けるので、初回表示でちらつかない）。
// ここでは切り替え・保存と、折りたたみ中の一時展開（peek）だけを持つ
export function Sidebar({ active, unread, errorCount, lastFetch }: Props) {
  const collapsed = useSyncExternalStore(
    subscribeCollapsed,
    readCollapsed,
    () => false,
  );
  const [peek, setPeek] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const hasUnread = unread > 0;
  const hasError = errorCount > 0;

  useEffect(() => {
    // 属性が付かなかった（スクリプト未実行など）場合の保険として、保存値と合わせる
    if (
      parseCollapsed(localStorage.getItem(SIDEBAR_STORAGE_KEY)) !==
      readCollapsed()
    ) {
      applyCollapsed(parseCollapsed(localStorage.getItem(SIDEBAR_STORAGE_KEY)));
    }
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  function schedulePeek(open: boolean) {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(
      () => setPeek(open),
      open ? PEEK_OPEN_DELAY_MS : PEEK_CLOSE_DELAY_MS,
    );
  }

  function toggle() {
    const next = !collapsed;
    if (timer.current) clearTimeout(timer.current);
    // 折りたたむ直後はマウスがボタン上にあるので、一時展開させず一度閉じる
    setPeek(false);
    applyCollapsed(next);
    try {
      localStorage.setItem(SIDEBAR_STORAGE_KEY, serializeCollapsed(next));
    } catch {
      // 保存できなくても、このセッション中の切り替えは有効
    }
  }

  const label = collapsed ? "常に表示する" : "折りたたむ";

  return (
    <div className="sidebar-slot">
      <nav
        className={`sidebar${peek ? " is-peek" : ""}`}
        aria-label="メインナビゲーション"
        onMouseEnter={() => collapsed && schedulePeek(true)}
        onMouseLeave={() => collapsed && schedulePeek(false)}
        onFocus={() => collapsed && schedulePeek(true)}
        onBlur={(e) => {
          if (collapsed && !e.currentTarget.contains(e.relatedTarget)) {
            schedulePeek(false);
          }
        }}
      >
        <div className="nav-list">
          {NAV.map((n) => (
            <Link
              key={n.key}
              href={n.href}
              className={`nav-item${active === n.key ? " is-active" : ""}`}
              aria-current={active === n.key ? "page" : undefined}
              title={
                collapsed
                  ? navTitle(n.key, n.label, unread, errorCount)
                  : undefined
              }
            >
              <span className="nav-icon">
                {ICONS[n.key](18)}
                {n.key === "articles" && hasUnread && (
                  <span className="nav-dot" aria-hidden="true" />
                )}
                {n.key === "feeds" && hasError && (
                  <span className="nav-dot nav-dot-err" aria-hidden="true" />
                )}
              </span>
              <span className="nav-label">{n.label}</span>
              {n.key === "articles" && hasUnread && (
                <span className="badge" aria-label="未読件数">
                  {unread}
                </span>
              )}
              {n.key === "feeds" && hasError && (
                <span
                  className="err-dot"
                  title="取得エラーのあるフィードがあります"
                />
              )}
            </Link>
          ))}
        </div>
        <div className="sidebar-spacer" />
        <div className="sidebar-foot">
          <div>最終取得 {formatLastFetch(lastFetch)}</div>
          {hasError && (
            <Link href="/feeds" className="foot-err">
              {errorCount}件のフィードで取得エラー
            </Link>
          )}
        </div>
        <button
          type="button"
          className="collapse-btn"
          onClick={toggle}
          aria-expanded={!collapsed}
          aria-label={label}
          title={label}
        >
          <CollapseIcon collapsed={collapsed} />
          <span className="collapse-label">{label}</span>
        </button>
      </nav>
    </div>
  );
}
