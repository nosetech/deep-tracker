"use client";

import { useEffect, useSyncExternalStore } from "react";
import { THEME_STORAGE_KEY, type Theme } from "./theme";

function readTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

// 保存値（手動設定）があればそれを、なければ OS 設定を使う（themeInitScript と同じ判定）
function initialTheme(): Theme {
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    if (saved === "light" || saved === "dark") return saved;
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  } catch {
    return "light";
  }
}

// <html data-theme> を外部ストアとして購読する（SSR時は不明 = null。アイコンはCSSで出し分ける）
function subscribe(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
  return () => observer.disconnect();
}

export function ThemeToggle({ className }: { className?: string }) {
  const theme = useSyncExternalStore<Theme | null>(
    subscribe,
    readTheme,
    () => null,
  );

  useEffect(() => {
    // 属性が付かなかった・消えた（スクリプト未実行など）場合の保険として、保存値または OS 設定から設定し直す
    if (!document.documentElement.dataset.theme) {
      document.documentElement.dataset.theme = initialTheme();
    }
  }, []);

  useEffect(() => {
    // 手動設定がない間は OS のテーマ変更に追従する
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (localStorage.getItem(THEME_STORAGE_KEY)) return;
      document.documentElement.dataset.theme = mq.matches ? "dark" : "light";
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const toggle = () => {
    const next: Theme = readTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // localStorage が使えなくてもテーマ自体は切り替える
    }
  };

  const label =
    theme === "dark" ? "ライトモードに切り替え" : "ダークモードに切り替え";

  return (
    <button
      type="button"
      className={`theme-toggle ${className ?? ""}`}
      onClick={toggle}
      aria-label={label}
      title={label}
    >
      <svg
        className="theme-icon-sun"
        width="15"
        height="15"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4" />
      </svg>
      <svg
        className="theme-icon-moon"
        width="15"
        height="15"
        viewBox="0 0 24 24"
        fill="currentColor"
        aria-hidden="true"
      >
        <path d="M20.5 14.6A8.5 8.5 0 0 1 9.4 3.5a8.5 8.5 0 1 0 11.1 11.1z" />
      </svg>
    </button>
  );
}
