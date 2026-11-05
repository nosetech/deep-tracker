"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ErrorPanel } from "@/components/states";
import { api } from "@/lib/api/client";
import type { ArticleDetail } from "@/lib/api/types";
import { formatFull } from "@/lib/format";
import { sanitizeHtml } from "@/lib/sanitize";

const SKELETON_WIDTHS = ["92%", "78%", "86%", "64%", "88%"];

const ExternalIcon = () => (
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
);

/** サマリの元記事を、画面遷移せずに表示するパネル。 */
export function ArticlePreview({
  id,
  onClose,
  onLoaded,
}: {
  id: number;
  onClose: () => void;
  /** 取得に成功したとき（既読化はここで行う） */
  onLoaded: (article: ArticleDetail) => void;
}) {
  const [article, setArticle] = useState<ArticleDetail | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "missing">(
    "loading",
  );
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStatus("loading");
    setArticle(null);
    api
      .getArticle(id)
      .then((a) => {
        if (cancelled) return;
        setArticle(a);
        onLoaded(a);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setStatus(
          (e as { status?: number }).status === 404 ? "missing" : "error",
        );
      });
    return () => {
      cancelled = true;
    };
    // onLoaded は親の再描画で変わるため依存に含めない
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, reloadKey]);

  const content = article?.content;
  const html = useMemo(() => (content ? sanitizeHtml(content) : ""), [content]);
  const url = article?.url ?? null;

  return (
    <aside className="pv" aria-label="元記事プレビュー">
      <div className="pv-head">
        <div className="pv-head-title">元記事</div>
        <button
          type="button"
          className="pv-close"
          aria-label="プレビューを閉じる"
          title="閉じる"
          onClick={onClose}
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>
      <div className="pv-body">
        {article ? (
          <div>
            <div className="pv-meta">
              <span className="pv-feed">{article.feed_name}</span>
              <span className="pv-date">
                {formatFull(article.published_at ?? article.fetched_at)}
              </span>
            </div>
            <h2 className="pv-title">{article.title}</h2>
            <div className="pv-content">
              {html ? (
                <div
                  className="det-body"
                  dangerouslySetInnerHTML={{ __html: html }}
                />
              ) : (
                <p className="det-nobody">本文はフィードに含まれていません。</p>
              )}
            </div>
            <div className="pv-actions">
              {url && (
                <a
                  className="det-open"
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  外部サイトで開く
                  <ExternalIcon />
                </a>
              )}
              <Link
                className="pv-detail"
                href={`/articles/${article.id}?from=summary`}
              >
                記事画面で開く
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
                  <path d="M9 6l6 6-6 6" />
                </svg>
              </Link>
            </div>
          </div>
        ) : status === "loading" ? (
          <div className="pv-skel" aria-busy="true">
            <div className="skel-head">
              <span className="skel-spin" aria-hidden="true" />
              <span>元記事を読み込み中…</span>
            </div>
            <div className="skel-bar pv-skel-meta" />
            <div className="skel-bar pv-skel-title" />
            <div className="skel-bar pv-skel-title pv-skel-title-s" />
            <div className="skel-rule" />
            {SKELETON_WIDTHS.map((w, i) => (
              <div
                key={i}
                className="skel-bar pv-skel-line"
                style={{ width: w }}
              />
            ))}
          </div>
        ) : status === "error" ? (
          <ErrorPanel
            compact
            title="元記事を取得できませんでした"
            message="記事の本文を読み込めませんでした。APIサーバーとの通信状況を確認して、もう一度お試しください。"
            onRetry={() => setReloadKey((k) => k + 1)}
          />
        ) : (
          <div className="pv-missing">
            <div className="pv-missing-title">記事が見つかりません</div>
            <p>この記事は削除されたか、保持期間を過ぎたため表示できません。</p>
          </div>
        )}
      </div>
    </aside>
  );
}
