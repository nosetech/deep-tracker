"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { SHELL_REFRESH_EVENT } from "@/components/AppShell";
import { useToast } from "@/components/Toast";
import { ApiErrorPanel, LoadingSkeleton } from "@/components/states";
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
  const [reloadKey, setReloadKey] = useState(0);
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
  }, [id, reloadKey]);

  const content = article?.content;
  const html = useMemo(() => (content ? sanitizeHtml(content) : ""), [content]);

  // サマリの元記事から開いた場合は、戻り先をサマリにする
  const fromSummary = useSearchParams().get("from") === "summary";
  const backLabel = fromSummary ? "サマリに戻る" : "記事一覧に戻る";

  // 新旧記事への移動は履歴を積まず、戻る先を一覧(サマリ)のままにする
  const goAdjacent = (targetId: number) =>
    router.replace(
      `/articles/${targetId}${fromSummary ? "?from=summary" : ""}`,
    );

  const goBack = () => {
    if (window.history.length > 1) router.back();
    else router.push(fromSummary ? "/" : "/articles");
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

  if (error === "failed") {
    return (
      <div className="art-detail">
        <ApiErrorPanel onRetry={() => setReloadKey((k) => k + 1)} />
      </div>
    );
  }
  if (error) {
    return (
      <div className="art-detail">
        <div className="art-empty">
          <div className="art-empty-title">記事が見つかりません</div>
          <p>削除されたか、存在しない記事です。</p>
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
  if (!article)
    return (
      <div className="art-detail">
        <LoadingSkeleton />
      </div>
    );

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
        {backLabel}
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
              onClick={() => goAdjacent(article.newer!.id)}
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
              onClick={() => goAdjacent(article.older!.id)}
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
