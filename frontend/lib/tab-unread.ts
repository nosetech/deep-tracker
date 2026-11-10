// ブラウザのタブ（タイトル・ファビコン）への未読表示と、未読件数のポーリング制御。
// React / DOM に依存しない純粋なロジックとして切り出し、node:test で検証する。

export const APP_TITLE = "Deep Tracker";

// 未読件数を再取得する間隔（ミリ秒）。設定ファイルには出さない
export const UNREAD_POLL_INTERVAL_MS = 60_000;

const MAX_DISPLAY_COUNT = 99;

// 先頭に付ける `(N) ` / `(99+) `。0件・不正値は付けない
export function unreadPrefix(count: number): string {
  if (!Number.isFinite(count) || count <= 0) return "";
  return count > MAX_DISPLAY_COUNT
    ? `(${MAX_DISPLAY_COUNT}+) `
    : `(${Math.floor(count)}) `;
}

const PREFIX_RE = /^\(\d+\+?\) /;

export function stripUnreadPrefix(title: string): string {
  return title.replace(PREFIX_RE, "");
}

// 既存の件数表示を付け替えたタイトルを返す
export function applyUnreadToTitle(title: string, count: number): string {
  return unreadPrefix(count) + stripUnreadPrefix(title || APP_TITLE);
}

// app/icon.svg と同じ図形。未読があるときは右上にドットを重ねる
export function faviconSvg(hasUnread: boolean): string {
  const dot = hasUnread
    ? `<circle cx="49" cy="15" r="13" fill="#f2c14e" stroke="#f6f6f4" stroke-width="4"/>`
    : "";
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">` +
    `<rect width="64" height="64" rx="14" fill="#2b2d33"/>` +
    `<path d="M15 14H28A18 18 0 0 1 28 50H15Z" fill="none" stroke="#f6f6f4" stroke-width="5.5" stroke-linejoin="round"/>` +
    `<path d="M24 25H32M24 39H30" stroke="#f6f6f4" stroke-width="4" stroke-linecap="round"/>` +
    `<path d="M24 32H37" stroke="#f2c14e" stroke-width="4" stroke-linecap="round"/>` +
    dot +
    `</svg>`
  );
}

export function faviconDataUrl(hasUnread: boolean): string {
  return `data:image/svg+xml,${encodeURIComponent(faviconSvg(hasUnread))}`;
}

type PollerDeps = {
  fetchTotal: () => Promise<number>;
  onChange: (total: number) => void;
  intervalMs?: number;
  isVisible: () => boolean;
};

// 定期取得。失敗時は onChange を呼ばず、前回の件数を維持する
export function createUnreadPoller(deps: PollerDeps) {
  const { fetchTotal, onChange, isVisible } = deps;
  const intervalMs = deps.intervalMs ?? UNREAD_POLL_INTERVAL_MS;
  let timer: ReturnType<typeof setInterval> | null = null;
  let stopped = false;

  const refresh = async () => {
    try {
      const total = await fetchTotal();
      if (!stopped && Number.isFinite(total)) onChange(total);
    } catch {
      // 前回の件数を維持する
    }
  };

  return {
    start() {
      stopped = false;
      void refresh();
      timer = setInterval(() => void refresh(), intervalMs);
    },
    // タブが visible に戻ったときに呼ぶ
    onVisibilityChange() {
      if (isVisible()) void refresh();
    },
    refresh,
    stop() {
      stopped = true;
      if (timer) clearInterval(timer);
      timer = null;
    },
  };
}
