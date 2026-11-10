// フィード登録・URL変更時のエラーを、画面に出す文言とコード行に変換する。
// 取得の失敗（fetch_failed）と解析の失敗（not_a_feed）を区別し、原因を誤解させないようにする。

export type FeedErrorView = {
  message: string;
  // 本文の下に等幅で出す「fetch_failed · 429」形式の行。解析エラーには付けない
  code?: string;
};

export type FeedErrorInput = {
  code?: string;
  message: string;
  reason?: string;
  httpStatus?: number | null;
};

const FETCH_FAILED = "フィードを取得できませんでした。";
const NOT_A_FEED = "RSS / Atom として解析できませんでした。";

// 配信元がボット対策などで自動アクセスを拒否している場合。User-Agent の偽装などでの回避はせず、
// 別のURLを案内するだけにする
const RESTRICTED =
  "配信元がアクセスを制限している可能性があります。別のフィード URL を試してください。";
const NOT_FOUND = "URL が見つかりません。URL を確認してください。";
const SERVER_ERROR =
  "配信元でエラーが発生しています。時間をおいて再度お試しください。";
const UNREACHABLE =
  "接続できませんでした。URL とネットワークを確認してください。";

function hint(reason?: string, status?: number | null): string {
  if (reason === "http_status" && status != null) {
    if (status === 429 || status === 403) return RESTRICTED;
    if (status === 404) return NOT_FOUND;
    if (status >= 500) return SERVER_ERROR;
    return "";
  }
  if (reason === "timeout" || reason === "connect") return UNREACHABLE;
  return "";
}

/** 登録・URL変更の 422（invalid_url 以外）を画面用の文言にする。対象外のコードは null */
export function describeFeedError(err: FeedErrorInput): FeedErrorView | null {
  if (err.code === "fetch_failed") {
    const extra = hint(err.reason, err.httpStatus);
    const code =
      err.reason === "http_status" && err.httpStatus != null
        ? `fetch_failed · ${err.httpStatus}`
        : `fetch_failed · ${err.reason ?? "unknown"}`;
    return { message: `${FETCH_FAILED}${err.message}。${extra}`, code };
  }
  if (err.code === "not_a_feed") {
    return { message: `${NOT_A_FEED}${err.message}` };
  }
  return null;
}
