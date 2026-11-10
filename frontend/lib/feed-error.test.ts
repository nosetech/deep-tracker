import assert from "node:assert/strict";
import { test } from "node:test";

import { describeFeedError } from "./feed-error.ts";

const fetchFailed = (reason: string, httpStatus: number | null) => ({
  code: "fetch_failed",
  message: "HTTPエラー: " + httpStatus,
  reason,
  httpStatus,
});

test("429・403: 取得エラーで、配信元の制限と別URLを案内する", () => {
  for (const s of [429, 403]) {
    const v = describeFeedError(fetchFailed("http_status", s));
    assert.ok(v);
    assert.ok(v.message.startsWith("フィードを取得できませんでした。"));
    assert.ok(!v.message.includes("解析できませんでした"));
    assert.ok(
      v.message.includes("配信元がアクセスを制限している可能性があります"),
    );
    assert.ok(v.message.includes("別のフィード URL を試してください"));
    assert.equal(v.code, `fetch_failed · ${s}`);
  }
});

test("404: URLの確認を案内する", () => {
  const v = describeFeedError(fetchFailed("http_status", 404));
  assert.ok(
    v?.message.includes("URL が見つかりません。URL を確認してください。"),
  );
  assert.equal(v?.code, "fetch_failed · 404");
});

test("5xx: 時間をおくよう案内する", () => {
  const v = describeFeedError(fetchFailed("http_status", 503));
  assert.ok(v?.message.includes("配信元でエラーが発生しています"));
});

test("その他のHTTPステータス: 補足なし", () => {
  const v = describeFeedError(fetchFailed("http_status", 410));
  assert.equal(v?.message, "フィードを取得できませんでした。HTTPエラー: 410。");
});

test("タイムアウト・接続失敗: ネットワークの確認を案内する", () => {
  for (const reason of ["timeout", "connect"]) {
    const v = describeFeedError({
      code: "fetch_failed",
      message: "タイムアウトしました",
      reason,
      httpStatus: null,
    });
    assert.ok(
      v?.message.includes(
        "接続できませんでした。URL とネットワークを確認してください。",
      ),
    );
    assert.equal(v?.code, `fetch_failed · ${reason}`);
  }
});

test("not_a_feed: 従来どおりの文言で、コード行は付けない", () => {
  const v = describeFeedError({
    code: "not_a_feed",
    message: "フィードを解析できません: x",
  });
  assert.deepEqual(v, {
    message:
      "RSS / Atom として解析できませんでした。フィードを解析できません: x",
  });
});

test("対象外のコードは null", () => {
  assert.equal(describeFeedError({ code: "invalid_url", message: "x" }), null);
  assert.equal(describeFeedError({ message: "x" }), null);
});
