"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { SHELL_REFRESH_EVENT } from "@/components/AppShell";
import { useToast } from "@/components/Toast";
import { api } from "@/lib/api/client";
import { sanitizeHtml } from "@/lib/sanitize";
import type { ArticleDetail } from "@/lib/api/types";

const WEEKDAYS = ["日", "月", "火", "水", "木", "金", "土"];

// デザインの fullD に合わせ、JST で「2026年10月19日（月）09:30」形式にする
function formatFull(iso: string): string {
  const d = new Date(new Date(iso).getTime() + 9 * 3600000);
  const p2 = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}年${d.getUTCMonth() + 1}月${d.getUTCDate()}日（${WEEKDAYS[d.getUTCDay()]}）${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}`;
}

function refreshShell() {
  window.dispatchEvent(new Event(SHELL_REFRESH_EVENT));
}

export default function ArticleDetailPage() {
  const router = useRouter();
  const toast = useToast();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const [article, setArticle] = useState<ArticleDetail | null>(null);
  const [error, setError] = useState<"notfound" | "failed" | null>(null);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setArticle(null);
    setError(null);
    if (!Number.isInteger(id)) {
      setError("notfound");
      return;
    }
    api
      .getArticle(id)
      .then(async (a) => {
        if (cancelled) return;
        setArticle(a);
        document.querySelector(".main")?.scrollTo(0, 0);
        // 開いた時点で自動的に既読にする
        if (!a.is_read) {
          try {
            await api.setArticleRead(a.id, true);
            if (cancelled) return;
            setArticle((cur) =>
              cur && cur.id === a.id ? { ...cur, is_read: true } : cur,
            );
            refreshShell();
          } catch {
            // 既読化に失敗しても本文は表示する
          }
        }
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(
          (e as { status?: number }).status === 404 ? "notfound" : "failed",
        );
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const content = article?.content;
  const html = useMemo(() => (content ? sanitizeHtml(content) : ""), [content]);

  const goBack = () => {
    if (window.history.length > 1) router.back();
    else router.push("/articles");
  };

  const toggle = async () => {
    if (!article) return;
    const next = !article.is_read;
    try {
      await api.setArticleRead(article.id, next);
    } catch {
      toast("既読状態の更新に失敗しました", "error");
      return;
    }
    setArticle({ ...article, is_read: next });
    refreshShell();
    toast(next ? "既読にしました" : "未読に戻しました");
  };

  if (error) {
    return (
      <div className="art-detail">
        <div className="art-empty">
          <div className="art-empty-title">
            {error === "notfound"
              ? "記事が見つかりません"
              : "記事を取得できませんでした"}
          </div>
          <p>
            {error === "notfound"
              ? "削除されたか、存在しない記事です。"
              : "バックエンドに接続できません。しばらくしてからもう一度お試しください。"}
          </p>
          <button
            type="button"
            className="art-empty-btn"
            onClick={() => router.push("/articles")}
          >
            記事一覧に戻る
          </button>
        </div>
      </div>
    );
  }
  if (!article) return <div className="art-detail" aria-busy="true" />;

  const when = article.published_at ?? article.fetched_at;

  return (
    <div className="art-detail">
      <button type="button" className="det-back" onClick={goBack}>
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M15 18l-6-6 6-6" />
        </svg>
        記事一覧に戻る
      </button>
      <div className="det-meta">
        <span className="det-feed">{article.feed_name}</span>
        <span className="det-date">{formatFull(when)}</span>
      </div>
      <h1 className="det-title">{article.title}</h1>
      <div className="det-actions">
        {article.url && (
          <a
            className="det-open"
            href={article.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            元記事を開く
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6" />
            </svg>
          </a>
        )}
        <button
          type="button"
          className="det-toggle"
          onClick={() => void toggle()}
        >
          <span
            className={`det-dot${article.is_read ? "" : " is-unread"}`}
            aria-hidden="true"
          />
          {article.is_read ? "未読に戻す" : "既読にする"}
        </button>
      </div>
      <div className="det-note">
        {article.is_read
          ? "開いた時点で既読になりました"
          : "未読として残しています"}
      </div>
      <div className="det-content">
        {html ? (
          <div
            className="det-body"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <p className="det-nobody">本文はフィードに含まれていません。</p>
        )}
      </div>
      <div className="det-nav">
        <div>
          {article.newer && (
            <button
              type="button"
              className="det-nav-btn"
              onClick={() => router.push(`/articles/${article.newer!.id}`)}
            >
              <span className="det-nav-label">← 新しい記事</span>
              <span className="det-nav-title">{article.newer.title}</span>
            </button>
          )}
        </div>
        <div>
          {article.older && (
            <button
              type="button"
              className="det-nav-btn det-nav-older"
              onClick={() => router.push(`/articles/${article.older!.id}`)}
            >
              <span className="det-nav-label">古い記事 →</span>
              <span className="det-nav-title">{article.older.title}</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
