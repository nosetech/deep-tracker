// タブ単位で保持する画面状態の保存・復元（sessionStorage）。
// 保存値は壊れている可能性があるため、読み込み側で検証する。

export function loadSessionState<T>(
  key: string,
  parse: (raw: unknown) => T | null,
): T | null {
  if (typeof window === "undefined") return null;
  try {
    const text = window.sessionStorage.getItem(key);
    return text === null ? null : parse(JSON.parse(text));
  } catch {
    return null;
  }
}

export function saveSessionState(key: string, value: unknown): void {
  try {
    window.sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // 保存できなくても画面の動作には影響させない
  }
}
