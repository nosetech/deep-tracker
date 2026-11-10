import assert from "node:assert/strict";
import { test } from "node:test";

import {
  SIDEBAR_STORAGE_KEY,
  parseCollapsed,
  serializeCollapsed,
  sidebarInitScript,
} from "./sidebar-state.ts";

test("保存した値を読み戻せる", () => {
  assert.equal(parseCollapsed(serializeCollapsed(true)), true);
  assert.equal(parseCollapsed(serializeCollapsed(false)), false);
});

test("未保存・壊れた値・型違いは既定（展開）に戻す", () => {
  assert.equal(parseCollapsed(null), false);
  assert.equal(parseCollapsed(undefined), false);
  assert.equal(parseCollapsed(""), false);
  assert.equal(parseCollapsed("{broken"), false);
  assert.equal(parseCollapsed("true"), false);
  assert.equal(parseCollapsed("[true]"), false);
  assert.equal(parseCollapsed("null"), false);
  assert.equal(parseCollapsed('{"collapsed":"true"}'), false);
  assert.equal(parseCollapsed('{"collapsed":1}'), false);
  assert.equal(parseCollapsed("{}"), false);
});

test("hydration前スクリプトは保存値が折りたたみのときだけ属性を付ける", () => {
  function run(stored: string | null): string | undefined {
    const dataset: Record<string, string> = {};
    const localStorage = { getItem: () => stored };
    new Function("localStorage", "document", sidebarInitScript)(localStorage, {
      documentElement: { dataset },
    });
    return dataset.sidebar;
  }
  assert.equal(run(serializeCollapsed(true)), "collapsed");
  assert.equal(run(serializeCollapsed(false)), undefined);
  assert.equal(run(null), undefined);
  assert.equal(run("{broken"), undefined);
  assert.equal(run('{"collapsed":"true"}'), undefined);
  assert.ok(sidebarInitScript.includes(SIDEBAR_STORAGE_KEY));
});
