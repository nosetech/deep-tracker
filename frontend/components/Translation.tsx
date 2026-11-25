"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import type { ArticleDetail } from "@/lib/api/types";
import {
  isTranslated,
  translationErrorView,
  translationState,
  type TranslationState,
} from "@/lib/translation";

// 翻訳ジョブの進捗を確認する間隔
const POLL_MS = 2000;

type TranslationPatch = Pick<
  ArticleDetail,
  | "language"
  | "title_ja"
  | "content_ja"
  | "translated_at"
  | "translation_truncated"
  | "translation_job"
>;

export type ArticleTranslation = {
  state: TranslationState;
  /** 原文を表示しているか（未翻訳・翻訳中・失敗の間も原文） */
  showingOriginal: boolean;
  title: string;
  content: string | null;
  /** 表示中のテキストの言語（lang 属性用） */
  lang: string | undefined;
  toggleOriginal: () => void;
  translate: () => void;
};

/** 記事の翻訳表示（翻訳済みは日本語を既定に、原文への切替・手動翻訳・進捗の確認）。 */
export function useArticleTranslation(
  article: ArticleDetail | null,
  onPatch: (id: number, patch: Partial<TranslationPatch>) => void,
): ArticleTranslation {
  const [original, setOriginal] = useState<{ id: number; on: boolean }>({
    id: 0,
    on: false,
  });
  const state = article ? translationState(article) : "ja";
  const translated = isTranslated(state);
  const showingOriginal =
    state !== "ja" &&
    (!translated || (original.id === article?.id && original.on));
  const id = article?.id;
  const jobId = article?.translation_job?.id;

  // 翻訳中はジョブの完了を待ち、成功したら翻訳結果を取り直す
  useEffect(() => {
    // id=0 は投入の応答待ち（まだジョブが無い）
    if (state !== "running" || id === undefined || !jobId) return;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const job = await api.getAiJob(jobId);
        if (cancelled) return;
        if (job.status === "succeeded") {
          const a = await api.getArticle(id);
          if (cancelled) return;
          onPatch(id, {
            language: a.language,
            title_ja: a.title_ja,
            content_ja: a.content_ja,
            translated_at: a.translated_at,
            translation_truncated: a.translation_truncated,
            translation_job: a.translation_job,
          });
        } else if (job.status === "failed") {
          onPatch(id, {
            translation_job: {
              id: job.id,
              status: job.status,
              error: job.error,
              rate_limited: job.rate_limited,
            },
          });
        }
      } catch (e: unknown) {
        // ジョブ・記事が消えた（404）場合は確認をやめて失敗として表示する。
        // それ以外の通信の失敗は次の確認で取り直す
        if (!cancelled && (e as { status?: number }).status === 404) {
          onPatch(id, {
            translation_job: {
              id: jobId,
              status: "failed",
              error: "翻訳ジョブが見つかりません",
              rate_limited: false,
            },
          });
        }
      }
    }, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // onPatch は親の再描画で変わるため依存に含めない
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, id, jobId]);

  const translate = useCallback(() => {
    if (id === undefined) return;
    setOriginal({ id, on: false });
    // 投入の応答を待たずに「翻訳中…」にする
    onPatch(id, {
      translation_job: {
        id: 0,
        status: "pending",
        error: null,
        rate_limited: false,
      },
    });
    api
      .translateArticle(id)
      .then(({ job_id }) =>
        onPatch(id, {
          translation_job: {
            id: job_id,
            status: "pending",
            error: null,
            rate_limited: false,
          },
        }),
      )
      .catch(async (e: unknown) => {
        // 409: 別の操作で翻訳済みになった
        if ((e as { status?: number }).status === 409) {
          try {
            const a = await api.getArticle(id);
            onPatch(id, {
              title_ja: a.title_ja,
              content_ja: a.content_ja,
              translated_at: a.translated_at,
              translation_truncated: a.translation_truncated,
              translation_job: a.translation_job,
            });
            return;
          } catch {
            // 下の失敗表示にする
          }
        }
        onPatch(id, {
          translation_job: {
            id: 0,
            status: "failed",
            error: "翻訳ジョブを登録できませんでした",
            rate_limited: false,
          },
        });
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const toggleOriginal = useCallback(() => {
    if (id === undefined) return;
    setOriginal((cur) => ({
      id,
      on: cur.id === id ? !cur.on : true,
    }));
  }, [id]);

  return {
    state,
    showingOriginal,
    title:
      !article || showingOriginal || !article.title_ja
        ? (article?.title ?? "")
        : article.title_ja,
    content:
      !article || showingOriginal || !translated
        ? (article?.content ?? null)
        : article.content_ja,
    // 原文の言語は判定していないため、日本語表示のときだけ明示する
    lang: showingOriginal ? undefined : "ja",
    toggleOriginal,
    translate,
  };
}

export const TranslateIcon = ({
  size,
  strokeWidth = 2,
}: {
  size: number;
  strokeWidth?: number;
}) => (
  <svg
    aria-hidden="true"
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={strokeWidth}
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M3 5h9M7.5 3v2M10 5c-.8 3.6-3 6.4-6 8M5.5 9c1.2 1.9 2.8 3.3 5 4" />
    <path d="M12.5 21l4.5-10 4.5 10M14.2 17.5h5.6" />
  </svg>
);

/** 記事一覧の行に付ける「翻訳」バッジ */
export function TranslatedBadge() {
  return (
    <span className="tr-badge" title="日本語に翻訳済み">
      <TranslateIcon size={11} strokeWidth={2.2} />
      翻訳
    </span>
  );
}

/** 「翻訳済み・原文を表示」の切替、「日本語に翻訳」ボタン、「翻訳中…」 */
export function TranslationActions({
  tr,
  compact = false,
}: {
  tr: ArticleTranslation;
  compact?: boolean;
}) {
  const c = compact ? " is-compact" : "";
  if (isTranslated(tr.state)) {
    return (
      <div className={`tr-tools${c}`}>
        <span className="tr-label">
          <TranslateIcon size={compact ? 12 : 13} />
          翻訳済み
        </span>
        <button type="button" className="tr-switch" onClick={tr.toggleOriginal}>
          {tr.showingOriginal ? "翻訳を表示" : "原文を表示"}
        </button>
      </div>
    );
  }
  if (tr.state === "pending") {
    return (
      <button type="button" className={`tr-btn${c}`} onClick={tr.translate}>
        <TranslateIcon size={compact ? 13 : 14} />
        日本語に翻訳
      </button>
    );
  }
  if (tr.state === "running") {
    return (
      <button
        type="button"
        className={`tr-btn is-running${c}`}
        disabled
        aria-busy="true"
      >
        <span className="skel-spin" aria-hidden="true" />
        翻訳中…
      </button>
    );
  }
  return null;
}

/** 翻訳の失敗・利用制限（本文の上に出す。原文はその下にそのまま表示する） */
export function TranslationError({
  tr,
  error,
  compact = false,
}: {
  tr: ArticleTranslation;
  error: string | null;
  compact?: boolean;
}) {
  if (tr.state !== "failed" && tr.state !== "limit") return null;
  const v = translationErrorView(tr.state, error);
  const retry = (
    <button type="button" className="tr-err-retry" onClick={tr.translate}>
      再試行
    </button>
  );
  return (
    <div
      role="alert"
      lang="ja"
      className={`tr-err${compact ? " is-compact" : ""}`}
    >
      <div className="tr-err-title">
        <svg
          aria-hidden="true"
          width={compact ? 15 : 16}
          height={compact ? 15 : 16}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        >
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7.5v5.5M12 16.5v.01" />
        </svg>
        {v.title}
      </div>
      <p>{v.text}</p>
      {compact ? (
        <div className="tr-err-foot">
          <span className="tr-err-code">{v.code}</span>
          {retry}
        </div>
      ) : (
        <>
          <div className="tr-err-code">{v.code}</div>
          <div className="tr-err-actions">{retry}</div>
        </>
      )}
    </div>
  );
}

/** 先頭のみ翻訳した記事の注記（日本語表示中のみ） */
export function PartialTranslationNote({
  tr,
  compact = false,
}: {
  tr: ArticleTranslation;
  compact?: boolean;
}) {
  if (tr.state !== "partial" || tr.showingOriginal) return null;
  return (
    <div className={`tr-partial${compact ? " is-compact" : ""}`}>
      本文が長いため、先頭のみ翻訳しています（続きは
      <button type="button" onClick={tr.toggleOriginal}>
        原文を表示
      </button>
      ）
    </div>
  );
}
