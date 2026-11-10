// 記事詳細の前後記事の対象（未読のみ／すべて）の保存・復元。
// 端末（ブラウザ）単位の設定値として localStorage に保持する（画面状態の sessionStorage とは分ける）。
// React / DOM に依存しない純粋なロジックとして切り出し、node:test で検証する。

export const NAV_SCOPE_STORAGE_KEY = "deep-tracker.article-nav";

// 保存値（JSON文字列）を検証して unreadOnly を返す。未保存・壊れた値・型違いは既定（未読のみ = true）
export function parseUnreadOnly(raw: string | null | undefined): boolean {
  if (typeof raw !== "string") return true;
  try {
    const v: unknown = JSON.parse(raw);
    if (typeof v === "object" && v !== null && !Array.isArray(v)) {
      return (v as { unreadOnly?: unknown }).unreadOnly !== false;
    }
  } catch {
    // 壊れたJSONは既定に戻す
  }
  return true;
}

export function serializeUnreadOnly(unreadOnly: boolean): string {
  return JSON.stringify({ unreadOnly });
}
