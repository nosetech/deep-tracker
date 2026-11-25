import assert from "node:assert/strict";
import { test } from "node:test";

import {
  feedFilterQuery,
  groupFeeds,
  parseCollapsedGroups,
  parseFeedFilter,
  sectionKey,
  serializeCollapsedGroups,
} from "./feed-groups.ts";

const groups = [
  { id: 2, name: "空のグループ" },
  { id: 3, name: "ブログ" },
  { id: 1, name: "AWS障害情報" },
];

test("グループは名前順、未分類は最後。フィード0件のグループも返す", () => {
  const feeds = [
    { id: 10, group_id: 1 },
    { id: 11, group_id: null },
    { id: 12, group_id: 3 },
    { id: 13, group_id: 1 },
  ];
  const sections = groupFeeds(groups, feeds);
  assert.deepEqual(
    sections.map((s) => [s.group?.id ?? null, s.feeds.map((f) => f.id)]),
    [
      [1, [10, 13]],
      [3, [12]],
      [2, []],
      [null, [11]],
    ],
  );
});

test("未分類のフィードがなければ未分類のセクションは出さない", () => {
  const sections = groupFeeds(groups, [{ id: 10, group_id: 1 }]);
  assert.equal(
    sections.some((s) => s.group === null),
    false,
  );
});

test("存在しないグループを指すフィードは未分類に入れる", () => {
  const sections = groupFeeds([], [{ id: 10, group_id: 99 }]);
  assert.deepEqual(sections, [
    { group: null, feeds: [{ id: 10, group_id: 99 }] },
  ]);
});

test("折りたたみ状態を保存・復元できる", () => {
  const keys = new Set([sectionKey(3), sectionKey(null)]);
  assert.deepEqual(
    parseCollapsedGroups(serializeCollapsedGroups(keys)),
    new Set(["3", "none"]),
  );
});

test("折りたたみ状態の壊れた値は空に戻す", () => {
  assert.deepEqual(parseCollapsedGroups(null), new Set());
  assert.deepEqual(parseCollapsedGroups("{broken"), new Set());
  assert.deepEqual(parseCollapsedGroups('{"a":1}'), new Set());
  assert.deepEqual(
    parseCollapsedGroups('["1", 2, "x", "none"]'),
    new Set(["1", "none"]),
  );
});

test("記事一覧の絞り込み値を解釈する", () => {
  assert.deepEqual(parseFeedFilter("all"), { kind: "all" });
  assert.deepEqual(parseFeedFilter("12"), { kind: "feed", id: 12 });
  assert.deepEqual(parseFeedFilter("g:3"), { kind: "group", id: 3 });
  assert.equal(parseFeedFilter("g:"), null);
  assert.equal(parseFeedFilter("x"), null);
  assert.deepEqual(feedFilterQuery("all"), {});
  assert.deepEqual(feedFilterQuery("12"), { feed_id: 12 });
  assert.deepEqual(feedFilterQuery("g:3"), { group_id: 3 });
});
