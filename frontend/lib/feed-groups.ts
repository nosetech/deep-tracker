// フィードのグループ分け・折りたたみ状態の保存・記事一覧の絞り込み値。
// React / DOM に依存しない純粋なロジックとして切り出し、node:test で検証する。

type GroupLike = { id: number; name: string };
type FeedLike = { id: number; group_id: number | null };

export type FeedSection<G extends GroupLike, F extends FeedLike> = {
  /** null は「未分類」 */
  group: G | null;
  feeds: F[];
};

/**
 * フィードをグループごとのセクションに分ける。グループは名前順（日本語の照合順）、「未分類」は常に最後。
 * フィードが0件のグループも返す。未分類のセクションはフィードがあるときだけ返す。
 * 存在しないグループを指すフィードは未分類に入れる。
 */
export function groupFeeds<G extends GroupLike, F extends FeedLike>(
  groups: G[],
  feeds: F[],
): FeedSection<G, F>[] {
  const sorted = [...groups].sort(
    (a, b) => a.name.localeCompare(b.name, "ja") || a.id - b.id,
  );
  const ids = new Set(sorted.map((g) => g.id));
  const sections: FeedSection<G, F>[] = sorted.map((g) => ({
    group: g,
    feeds: feeds.filter((f) => f.group_id === g.id),
  }));
  const ungrouped = feeds.filter(
    (f) => f.group_id === null || !ids.has(f.group_id),
  );
  if (ungrouped.length > 0) sections.push({ group: null, feeds: ungrouped });
  return sections;
}

export const COLLAPSED_GROUPS_STORAGE_KEY =
  "deep-tracker:feed-groups-collapsed";

/** セクションの折りたたみ状態のキー。未分類は "none" */
export function sectionKey(groupId: number | null): string {
  return groupId === null ? "none" : String(groupId);
}

// 保存値（JSON文字列）を検証して、折りたたみ中のセクションのキーを返す。壊れた値は空（すべて展開）
export function parseCollapsedGroups(
  raw: string | null | undefined,
): Set<string> {
  if (typeof raw !== "string") return new Set();
  try {
    const v: unknown = JSON.parse(raw);
    if (Array.isArray(v)) {
      return new Set(
        v.filter(
          (x): x is string => typeof x === "string" && /^(none|\d+)$/.test(x),
        ),
      );
    }
  } catch {
    // 壊れたJSONは既定に戻す
  }
  return new Set();
}

export function serializeCollapsedGroups(keys: Set<string>): string {
  return JSON.stringify([...keys].sort());
}

/**
 * 記事一覧のフィード絞り込みの値。"all"、フィードID（"12"）、グループ（"g:3"）のいずれか。
 * 不正な値は null。
 */
export type FeedFilterValue =
  | { kind: "all" }
  | { kind: "feed"; id: number }
  | { kind: "group"; id: number };

export function parseFeedFilter(value: string): FeedFilterValue | null {
  if (value === "all") return { kind: "all" };
  if (/^\d+$/.test(value)) return { kind: "feed", id: Number(value) };
  const m = /^g:(\d+)$/.exec(value);
  if (m) return { kind: "group", id: Number(m[1]) };
  return null;
}

export function groupFilterValue(groupId: number): string {
  return `g:${groupId}`;
}

/** 絞り込みの値を記事一覧APIのクエリに変換する */
export function feedFilterQuery(value: string): {
  feed_id?: number;
  group_id?: number;
} {
  const v = parseFeedFilter(value);
  if (v?.kind === "feed") return { feed_id: v.id };
  if (v?.kind === "group") return { group_id: v.id };
  return {};
}
