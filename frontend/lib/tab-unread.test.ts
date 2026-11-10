import assert from "node:assert/strict";
import { mock, test } from "node:test";

import {
  applyUnreadToTitle,
  createUnreadPoller,
  faviconDataUrl,
  faviconSvg,
  unreadPrefix,
} from "./tab-unread.ts";

test("件数の書式: 0件/1件/99件/100件以上/不正値", () => {
  assert.equal(unreadPrefix(0), "");
  assert.equal(unreadPrefix(1), "(1) ");
  assert.equal(unreadPrefix(99), "(99) ");
  assert.equal(unreadPrefix(100), "(99+) ");
  assert.equal(unreadPrefix(5000), "(99+) ");
  assert.equal(unreadPrefix(NaN), "");
  assert.equal(unreadPrefix(-3), "");
});

test("タイトルの付け替え: 重複せず、0件で外れる", () => {
  assert.equal(applyUnreadToTitle("Deep Tracker", 3), "(3) Deep Tracker");
  assert.equal(applyUnreadToTitle("(3) Deep Tracker", 5), "(5) Deep Tracker");
  assert.equal(applyUnreadToTitle("(99+) Deep Tracker", 0), "Deep Tracker");
  assert.equal(applyUnreadToTitle("", 2), "(2) Deep Tracker");
});

test("ファビコン: 未読ありのときだけドットが入る", () => {
  assert.ok(!faviconSvg(false).includes("<circle"));
  assert.ok(faviconSvg(true).includes("<circle"));
  assert.ok(faviconDataUrl(true).startsWith("data:image/svg+xml,"));
});

test("ポーリング: 開始時に取得し、間隔ごとに再取得、失敗時は維持", async () => {
  mock.timers.enable({ apis: ["setInterval"] });
  try {
    let n = 0;
    let fail = false;
    let visible = false;
    const seen: number[] = [];
    const poller = createUnreadPoller({
      fetchTotal: async () => {
        if (fail) throw new Error("down");
        return ++n;
      },
      onChange: (t) => seen.push(t),
      intervalMs: 60_000,
      isVisible: () => visible,
    });
    poller.start();
    await Promise.resolve();
    await Promise.resolve();
    assert.deepEqual(seen, [1]);

    mock.timers.tick(60_000);
    await Promise.resolve();
    await Promise.resolve();
    assert.deepEqual(seen, [1, 2]);

    fail = true;
    mock.timers.tick(60_000);
    await Promise.resolve();
    await Promise.resolve();
    assert.deepEqual(seen, [1, 2]); // 失敗では通知しない

    fail = false;
    poller.onVisibilityChange(); // hidden のままでは取得しない
    await Promise.resolve();
    await Promise.resolve();
    assert.deepEqual(seen, [1, 2]);
    visible = true;
    poller.onVisibilityChange();
    await Promise.resolve();
    await Promise.resolve();
    assert.equal(seen.length, 3);

    poller.stop();
    mock.timers.tick(120_000);
    await Promise.resolve();
    assert.equal(seen.length, 3);
  } finally {
    mock.timers.reset();
  }
});
