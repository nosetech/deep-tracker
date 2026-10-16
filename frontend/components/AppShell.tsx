"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api/client";
import { ThemeToggle } from "./ThemeToggle";
import { ToastProvider } from "./Toast";

export const SHELL_REFRESH_EVENT = "dt:shell-refresh";

type NavKey = "summary" | "articles" | "feeds";

const NAV: { key: NavKey; href: string; label: string; mobileLabel: string }[] =
  [
    { key: "summary", href: "/", label: "サマリ", mobileLabel: "サマリ" },
    {
      key: "articles",
      href: "/articles",
      label: "記事一覧",
      mobileLabel: "記事",
    },
    {
      key: "feeds",
      href: "/feeds",
      label: "購読フィード",
      mobileLabel: "フィード",
    },
  ];

const ICONS: Record<NavKey, (size: number) => ReactNode> = {
  summary: (s) => (
    <svg
      width={s}
      height={s}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M6 3h9l4 4v14H6z" />
      <path d="M9.5 11h6M9.5 15h6M9.5 7h3" />
    </svg>
  ),
  articles: (s) => (
    <svg
      width={s}
      height={s}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M4 6h16M4 12h16M4 18h10" />
    </svg>
  ),
  feeds: (s) => (
    <svg
      width={s}
      height={s}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <circle cx="6" cy="18" r="1.6" />
      <path d="M5 11a8 8 0 0 1 8 8M5 4.5A14.5 14.5 0 0 1 19.5 19" />
    </svg>
  ),
};

function activeKey(pathname: string): NavKey {
  if (pathname.startsWith("/articles")) return "articles";
  if (pathname.startsWith("/feeds")) return "feeds";
  return "summary";
}

function screenTitle(pathname: string): string {
  if (/^\/articles\/.+/.test(pathname)) return "記事";
  return NAV.find((n) => n.key === activeKey(pathname))!.label;
}

function formatLastFetch(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const active = activeKey(pathname);
  const [unread, setUnread] = useState(0);
  const [errorCount, setErrorCount] = useState(0);
  const [lastFetch, setLastFetch] = useState<string | null>(null);

  const [refreshTick, setRefreshTick] = useState(0);

  // フィード操作などで未読数・エラー表示が変わったとき、画面側から再取得を依頼する
  useEffect(() => {
    const onRefresh = () => setRefreshTick((n) => n + 1);
    window.addEventListener(SHELL_REFRESH_EVENT, onRefresh);
    return () => window.removeEventListener(SHELL_REFRESH_EVENT, onRefresh);
  }, []);

  // 画面遷移のたびに再取得し、バッジ・エラー表示を最新に保つ
  useEffect(() => {
    let cancelled = false;
    Promise.all([api.getUnreadCounts(), api.listFeeds()])
      .then(([counts, feeds]) => {
        if (cancelled) return;
        setUnread(counts.total);
        const enabled = feeds.filter((f) => f.enabled);
        setErrorCount(enabled.filter((f) => f.last_fetch_ok === false).length);
        const times = enabled
          .map((f) => f.last_fetched_at)
          .filter((t): t is string => t !== null)
          .sort();
        setLastFetch(times.length ? times[times.length - 1] : null);
      })
      .catch(() => {
        // バックエンド未接続時もレイアウトは表示する
      });
    return () => {
      cancelled = true;
    };
  }, [pathname, refreshTick]);

  const hasUnread = unread > 0;
  const hasError = errorCount > 0;

  return (
    <ToastProvider>
      <div className="app">
        <nav className="sidebar" aria-label="メインナビゲーション">
          <div className="brand">
            <div className="brand-mark">DT</div>
            <div className="brand-name">Deep Tracker</div>
          </div>
          <div className="nav-list">
            {NAV.map((n) => (
              <Link
                key={n.key}
                href={n.href}
                className={`nav-item${active === n.key ? " is-active" : ""}`}
                aria-current={active === n.key ? "page" : undefined}
              >
                {ICONS[n.key](18)}
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
        </nav>

        <div className="main-col">
          <header className="mobile-header">
            <div className="mobile-title">{screenTitle(pathname)}</div>
            <ThemeToggle className="theme-toggle-mobile" />
          </header>
          <div className="desktop-header">
            <ThemeToggle />
          </div>
          <main className="main">{children}</main>

          <nav className="bottom-nav" aria-label="メインナビゲーション">
            {NAV.map((n) => (
              <Link
                key={n.key}
                href={n.href}
                className={`bottom-item${active === n.key ? " is-active" : ""}`}
                aria-current={active === n.key ? "page" : undefined}
              >
                {ICONS[n.key](22)}
                {n.mobileLabel}
                {n.key === "articles" && hasUnread && (
                  <span className="badge-m">{unread}</span>
                )}
                {n.key === "feeds" && hasError && (
                  <span className="err-dot-m" />
                )}
              </Link>
            ))}
          </nav>
        </div>
      </div>
    </ToastProvider>
  );
}
