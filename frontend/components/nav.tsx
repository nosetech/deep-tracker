import type { ReactNode } from "react";

export type NavKey = "summary" | "articles" | "feeds";

export const NAV: {
  key: NavKey;
  href: string;
  label: string;
  mobileLabel: string;
}[] = [
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

export const ICONS: Record<NavKey, (size: number) => ReactNode> = {
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
