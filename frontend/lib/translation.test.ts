import assert from "node:assert/strict";
import { test } from "node:test";

import {
  isTranslated,
  rateLimitResetText,
  translationErrorView,
  translationState,
} from "./translation.ts";

const base = {
  language: "other" as const,
  translated_at: null,
  translation_truncated: false,
  translation_job: null,
};
const job = (
  status: "pending" | "running" | "succeeded" | "failed",
  rate_limited = false,
) => ({
  id: 1,
  status,
  error: null,
  rate_limited,
});

test("翻訳済みは done、先頭のみなら partial", () => {
  assert.equal(
    translationState({ ...base, translated_at: "2026-01-01T00:00:00Z" }),
    "done",
  );
  assert.equal(
    translationState({
      ...base,
      translated_at: "2026-01-01T00:00:00Z",
      translation_truncated: true,
    }),
    "partial",
  );
  assert.equal(isTranslated("done"), true);
  assert.equal(isTranslated("pending"), false);
});

test("日本語の記事は ja", () => {
  assert.equal(translationState({ ...base, language: "ja" }), "ja");
});

test("未翻訳はジョブの状態で出し分ける", () => {
  assert.equal(translationState(base), "pending");
  assert.equal(
    translationState({ ...base, translation_job: job("pending") }),
    "running",
  );
  assert.equal(
    translationState({ ...base, translation_job: job("running") }),
    "running",
  );
  assert.equal(
    translationState({ ...base, translation_job: job("failed") }),
    "failed",
  );
  assert.equal(
    translationState({ ...base, translation_job: job("failed", true) }),
    "limit",
  );
  // 成功したのに未翻訳（記事の再取得前など）は、もう一度翻訳できる
  assert.equal(
    translationState({ ...base, translation_job: job("succeeded") }),
    "pending",
  );
});

test("利用制限の解除予定時刻を取り出す", () => {
  assert.equal(
    rateLimitResetText(
      "利用制限に達しました: limit（解除予定: 5pm (Asia/Tokyo)）",
    ),
    "5pm (Asia/Tokyo)",
  );
  assert.equal(rateLimitResetText("利用制限に達しました: limit"), null);
  assert.equal(rateLimitResetText(null), null);
});

test("失敗・利用制限の文言", () => {
  const limit = translationErrorView(
    "limit",
    "利用制限に達しました: x（解除予定: 13:00）",
  );
  assert.equal(limit.title, "AIの利用制限に達しました");
  assert.equal(limit.text, "時間をおいて再試行してください。解除予定: 13:00");
  assert.equal(
    translationErrorView("limit", null).text,
    "時間をおいて再試行してください。",
  );
  const failed = translationErrorView("failed", "翻訳の出力が不正です");
  assert.equal(failed.title, "翻訳できませんでした");
  assert.equal(failed.code, "translate_failed");
});
