"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api/client";
import { useTabUnreadIndicator, useUnreadCount } from "./useUnreadCount";
import { ThemeToggle } from "./ThemeToggle";
import { NAV, ICONS, type NavKey } from "./nav";
import { Sidebar } from "./Sidebar";
import { ToastProvider } from "./Toast";

// サマリの元記事プレビューを、main の右隣に差し込む場所
export const PREVIEW_SLOT_ID = "preview-slot";

// 記事詳細のモバイルヘッダーに、詳細画面側が「戻る」ボタンを差し込む場所
export const MOBILE_BACK_SLOT_ID = "mobile-back-slot";

export const SHELL_REFRESH_EVENT = "dt:shell-refresh";

function activeKey(pathname: string): NavKey {
  if (pathname.startsWith("/articles")) return "articles";
  if (pathname.startsWith("/feeds")) return "feeds";
  return "summary";
}

function screenTitle(pathname: string): string {
  if (/^\/articles\/.+/.test(pathname)) return "記事";
  return NAV.find((n) => n.key === activeKey(pathname))!.label;
}

function BrandMark({ className }: { className: string }) {
  return (
    <svg className={className} viewBox="0 0 64 64" aria-hidden="true">
      <rect width="64" height="64" rx="14" fill="var(--tx)" />
      <path
        d="M15 14H28A18 18 0 0 1 28 50H15Z"
        fill="none"
        stroke="var(--bg)"
        strokeWidth="5.5"
        strokeLinejoin="round"
      />
      <path
        d="M24 25H32M24 39H30"
        stroke="var(--bg)"
        strokeWidth="4"
        strokeLinecap="round"
      />
      <path
        d="M24 32H37"
        stroke="#f2c14e"
        strokeWidth="4"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const active = activeKey(pathname);
  const [errorCount, setErrorCount] = useState(0);
  const [lastFetch, setLastFetch] = useState<string | null>(null);
  const [version, setVersion] = useState<string | null>(null);

  const [refreshTick, setRefreshTick] = useState(0);
  const unread = useUnreadCount(`${pathname}:${refreshTick}`);
  useTabUnreadIndicator(unread);

  // フィード操作などで未読数・エラー表示が変わったとき、画面側から再取得を依頼する
  useEffect(() => {
    const onRefresh = () => setRefreshTick((n) => n + 1);
    window.addEventListener(SHELL_REFRESH_EVENT, onRefresh);
    return () => window.removeEventListener(SHELL_REFRESH_EVENT, onRefresh);
  }, []);

  // バージョンは起動中に変わらないので1回だけ取得する。取得できなければ表示しない
  useEffect(() => {
    api
      .getConfig()
      .then((c) => setVersion(c.version === "unknown" ? null : c.version))
      .catch(() => {});
  }, []);

  // 画面遷移のたびに再取得し、バッジ・エラー表示を最新に保つ
  useEffect(() => {
    let cancelled = false;
    api
      .listFeeds()
      .then((feeds) => {
        if (cancelled) return;
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

  const isDetail = /^\/articles\/.+/.test(pathname);
  const hasUnread = unread > 0;
  const hasError = errorCount > 0;

  return (
    <ToastProvider>
      <div className="app">
        <header className="pc-header">
          <BrandMark className="brand-mark" />
          <div className="brand-text">
            <div className="brand-name">Deep Tracker</div>
            {version && (
              <div className="brand-version">v{version.replace(/^v/, "")}</div>
            )}
          </div>
          <div className="pc-header-spacer" />
          <ThemeToggle />
        </header>
        <div className="app-body">
          <Sidebar
            active={active}
            unread={unread}
            errorCount={errorCount}
            lastFetch={lastFetch}
          />

          <div className="main-col">
            <header
              className={`mobile-header${isDetail ? " mobile-header-detail" : ""}`}
            >
              <div className="mobile-left">
                <div id={MOBILE_BACK_SLOT_ID} className="mobile-back-slot" />
                <div className="mobile-brand">
                  <BrandMark className="mobile-brand-mark" />
                  <div className="mobile-brand-text">
                    <div className="mobile-brand-name">Deep Tracker</div>
                    {version && (
                      <div className="mobile-brand-version">
                        v{version.replace(/^v/, "")}
                      </div>
                    )}
                  </div>
                </div>
              </div>
              <div className="mobile-title">{screenTitle(pathname)}</div>
              <ThemeToggle className="theme-toggle-mobile" />
            </header>
            <div className="main-row">
              <main className="main">{children}</main>
              <div id={PREVIEW_SLOT_ID} className="pv-slot" />
            </div>

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
      </div>
    </ToastProvider>
  );
}
