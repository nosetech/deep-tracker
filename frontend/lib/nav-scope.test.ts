import assert from "node:assert/strict";
import { test } from "node:test";

import { parseUnreadOnly, serializeUnreadOnly } from "./nav-scope.ts";

test("保存した値を読み戻せる", () => {
  assert.equal(parseUnreadOnly(serializeUnreadOnly(true)), true);
  assert.equal(parseUnreadOnly(serializeUnreadOnly(false)), false);
});

test("未保存・壊れた値・型違いは既定（未読のみ）に戻す", () => {
  assert.equal(parseUnreadOnly(null), true);
  assert.equal(parseUnreadOnly(undefined), true);
  assert.equal(parseUnreadOnly(""), true);
  assert.equal(parseUnreadOnly("{broken"), true);
  assert.equal(parseUnreadOnly("false"), true);
  assert.equal(parseUnreadOnly("[false]"), true);
  assert.equal(parseUnreadOnly("{}"), true);
  assert.equal(parseUnreadOnly('{"unreadOnly":"false"}'), true);
});
