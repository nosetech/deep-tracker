"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  MOBILE_BACK_SLOT_ID,
  SHELL_REFRESH_EVENT,
} from "@/components/AppShell";
import { useToast } from "@/components/Toast";
import { ApiErrorPanel, LoadingSkeleton } from "@/components/states";
import { api } from "@/lib/api/client";
import { formatFull } from "@/lib/format";
import {
  NAV_SCOPE_STORAGE_KEY,
  parseUnreadOnly,
  serializeUnreadOnly,
} from "@/lib/nav-scope";
import { sanitizeHtml } from "@/lib/sanitize";
import type { ArticleDetail } from "@/lib/api/types";

function refreshShell() {
  window.dispatchEvent(new Event(SHELL_REFRESH_EVENT));
}

// 「未読のみ」で前後に未読の記事がないときの表示
function NavEmpty({
  align,
  onShowAll,
}: {
  align: "left" | "right";
  onShowAll: () => void;
}) {
  return (
    <div className={`det-nav-empty is-${align}`}>
      <span className="det-nav-label">未読の記事はありません</span>
      <button type="button" className="det-nav-showall" onClick={onShowAll}>
        すべての記事を表示
      </button>
    </div>
  );
}

export default function ArticleDetailPage() {
  const router = useRouter();
  const toast = useToast();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const [article, setArticle] = useState<ArticleDetail | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [error, setError] = useState<"notfound" | "failed" | null>(null);

  // 前後記事の対象（未読のみ／すべて）。端末単位で localStorage に保持する
  const [unreadOnly, setUnreadOnly] = useState(() => {
    if (typeof window === "undefined") return true;
    try {
      return parseUnreadOnly(localStorage.getItem(NAV_SCOPE_STORAGE_KEY));
    } catch {
      return true;
    }
  });
  const unreadOnlyRef = useRef(unreadOnly);
  useEffect(() => {
    unreadOnlyRef.current = unreadOnly;
  }, [unreadOnly]);

  const changeScope = (next: boolean) => {
    setUnreadOnly(next);
    try {
      localStorage.setItem(NAV_SCOPE_STORAGE_KEY, serializeUnreadOnly(next));
    } catch {
      // 保存できなくても、この画面内では切り替えられる
    }
  };

  // 切り替え時は前後記事だけ取り直す（本文の再読み込みも既読化の再実行もしない）
  const mounted = useRef(false);
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    if (!Number.isInteger(id)) return;
    let cancelled = false;
    api
      .getArticle(id, { unreadOnly })
      .then((a) => {
        if (cancelled) return;
        setArticle((cur) =>
          cur && cur.id === a.id
            ? { ...cur, newer: a.newer, older: a.older }
            : cur,
        );
      })
      .catch(() => {
        // 取得に失敗したら、直前の前後記事の表示を維持する
      });
    return () => {
      cancelled = true;
    };
  }, [unreadOnly, id]);

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
      .getArticle(id, { unreadOnly: unreadOnlyRef.current })
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

  // モバイルのヘッダー左に「戻る」を出すため、シェル側の差し込み先を取得する
  const [backSlot, setBackSlot] = useState<HTMLElement | null>(null);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setBackSlot(document.getElementById(MOBILE_BACK_SLOT_ID));
  }, []);

  const content = article?.content;
  const html = useMemo(() => (content ? sanitizeHtml(content) : ""), [content]);

  // サマリの元記事から開いた場合は、戻り先をサマリにする
  const fromSummary = useSearchParams().get("from") === "summary";
  const backLabel = fromSummary ? "サマリに戻る" : "記事一覧に戻る";

  // 新旧記事へ移動した回数。URLの depth に持ち、「戻る」で一覧まで一度に戻る
  const searchParams = useSearchParams();
  const depth = Number(searchParams.get("depth")) || 0;

  // 新旧記事への移動は履歴を積む(ブラウザの戻るで直前の記事に戻れる)
  const goAdjacent = (targetId: number) => {
    const q = new URLSearchParams({ depth: String(depth + 1) });
    if (fromSummary) q.set("from", "summary");
    router.push(`/articles/${targetId}?${q}`);
  };

  const goBack = () => {
    if (window.history.length > depth + 1) window.history.go(-(depth + 1));
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
      {backSlot &&
        createPortal(
          <button
            type="button"
            className="mobile-back"
            aria-label={backLabel}
            onClick={goBack}
          >
            <svg
              width="20"
              height="20"
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
          </button>,
          backSlot,
        )}
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
      <div className="det-navwrap">
        <div className="det-nav-head">
          <span className="det-nav-scope">前後の記事</span>
          <div
            className="det-nav-seg"
            role="tablist"
            aria-label="前後の記事の対象"
          >
            {(
              [
                [true, "未読のみ"],
                [false, "すべて"],
              ] as const
            ).map(([v, label]) => (
              <button
                key={label}
                type="button"
                role="tab"
                aria-selected={unreadOnly === v}
                className={unreadOnly === v ? "is-on" : ""}
                onClick={() => changeScope(v)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="det-nav">
          <div>
            {article.newer ? (
              <button
                type="button"
                className="det-nav-btn"
                onClick={() => goAdjacent(article.newer!.id)}
              >
                <span className="det-nav-label">← 新しい記事</span>
                <span className="det-nav-title">{article.newer.title}</span>
              </button>
            ) : (
              unreadOnly && (
                <NavEmpty align="left" onShowAll={() => changeScope(false)} />
              )
            )}
          </div>
          <div>
            {article.older ? (
              <button
                type="button"
                className="det-nav-btn det-nav-older"
                onClick={() => goAdjacent(article.older!.id)}
              >
                <span className="det-nav-label">古い記事 →</span>
                <span className="det-nav-title">{article.older.title}</span>
              </button>
            ) : (
              unreadOnly && (
                <NavEmpty align="right" onShowAll={() => changeScope(false)} />
              )
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
