import type { ArticleDetail, TranslationJob } from "./api/types";

/**
 * 記事の翻訳状態。
 * - ja: 日本語の記事（翻訳不要）
 * - done / partial: 翻訳済み（partial は本文の先頭のみ翻訳）
 * - pending: 未翻訳（「日本語に翻訳」を出す）
 * - running: 翻訳ジョブが待機中・実行中
 * - failed / limit: 直近の翻訳ジョブが失敗・利用制限
 */
export type TranslationState =
  "ja" | "done" | "partial" | "pending" | "running" | "failed" | "limit";

type TranslationFields = Pick<
  ArticleDetail,
  "language" | "translated_at" | "translation_truncated"
> & { translation_job: TranslationJob | null };

export function translationState(a: TranslationFields): TranslationState {
  if (a.translated_at) return a.translation_truncated ? "partial" : "done";
  if (a.language === "ja") return "ja";
  const job = a.translation_job;
  if (!job || job.status === "succeeded") return "pending";
  if (job.status === "pending" || job.status === "running") return "running";
  return job.rate_limited ? "limit" : "failed";
}

export function isTranslated(state: TranslationState): boolean {
  return state === "done" || state === "partial";
}

/** 利用制限の失敗理由から解除予定時刻（「（解除予定: …）」）を取り出す。無ければ null */
export function rateLimitResetText(error: string | null): string | null {
  const m = /（解除予定: ([^）]+)）/.exec(error ?? "");
  return m ? m[1] : null;
}

/** 失敗・利用制限の表示文言 */
export function translationErrorView(
  state: "failed" | "limit",
  error: string | null,
): { title: string; text: string; code: string } {
  if (state === "limit") {
    const reset = rateLimitResetText(error);
    return {
      title: "AIの利用制限に達しました",
      text: `時間をおいて再試行してください。${reset ? `解除予定: ${reset}` : ""}`,
      code: "rate_limited",
    };
  }
  return {
    title: "翻訳できませんでした",
    text: "原文のまま表示しています。時間をおいて、もう一度お試しください。",
    // 失敗理由の全文は ai_jobs に残る。画面はデザインどおり種別のみ示す
    code: "translate_failed",
  };
}
