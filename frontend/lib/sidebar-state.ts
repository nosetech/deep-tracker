// サイドバーの折りたたみ状態の保存・復元。
// React / DOM に依存しない純粋なロジックとして切り出し、node:test で検証する。

export const SIDEBAR_STORAGE_KEY = "deep-tracker.sidebar";

// 折りたたみ中のホバー／フォーカスで一時展開（peek）するまでと、戻るまでの遅延（ミリ秒）
export const PEEK_OPEN_DELAY_MS = 140;
export const PEEK_CLOSE_DELAY_MS = 220;

// 保存値（JSON文字列）を検証して collapsed を返す。壊れた値・型違いは既定（展開 = false）
export function parseCollapsed(raw: string | null | undefined): boolean {
  if (typeof raw !== "string") return false;
  try {
    const v: unknown = JSON.parse(raw);
    if (typeof v === "object" && v !== null && !Array.isArray(v)) {
      return (v as { collapsed?: unknown }).collapsed === true;
    }
  } catch {
    // 壊れたJSONは既定に戻す
  }
  return false;
}

export function serializeCollapsed(collapsed: boolean): string {
  return JSON.stringify({ collapsed });
}

// FOUC防止: hydration前に <html data-sidebar> を確定させるインラインスクリプト（layout.tsx で埋め込む）。
// 検証ロジックは parseCollapsed と同じ（JSON.parse の結果が { collapsed: true } のときだけ折りたたみ）
export const sidebarInitScript = `(function(){try{var v=JSON.parse(localStorage.getItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)}));if(v&&typeof v==="object"&&v.collapsed===true){document.documentElement.dataset.sidebar="collapsed"}}catch(e){}})();`;
