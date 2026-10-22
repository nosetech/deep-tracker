import type { ReactNode } from "react";

const SKELETON_WIDTHS = ["78%", "64%", "86%", "58%", "72%"];

/** 読み込み中のスケルトン。`list` は一覧部分のみ（見出しなし）。 */
export function LoadingSkeleton({ list = false }: { list?: boolean }) {
  return (
    <div className="skel" aria-busy="true">
      {!list && (
        <>
          <div className="skel-head">
            <span className="skel-spin" aria-hidden="true" />
            <span>読み込み中…</span>
          </div>
          <div className="skel-bar skel-title" />
          <div className="skel-bar skel-sub" />
          <div className="skel-rule" />
        </>
      )}
      {SKELETON_WIDTHS.map((w, i) => (
        <div key={i} className="skel-row">
          <div className="skel-bar skel-row-title" style={{ width: w }} />
          <div className="skel-bar skel-row-meta" />
          <div className="skel-bar skel-row-body" />
        </div>
      ))}
    </div>
  );
}

/** API接続エラー・AI処理の失敗などのエラー表示（再試行ボタン付き）。 */
export function ErrorPanel({
  title,
  message,
  detail,
  onRetry,
  retryLabel = "再試行",
  retrying = false,
  compact = false,
  children,
}: {
  title: string;
  message: ReactNode;
  detail?: string;
  onRetry?: () => void;
  retryLabel?: string;
  retrying?: boolean;
  compact?: boolean;
  children?: ReactNode;
}) {
  return (
    <div
      role="alert"
      className={compact ? "err-panel err-panel-compact" : "err-panel"}
    >
      <div className="err-panel-title">
        <svg
          width={compact ? 16 : 18}
          height={compact ? 16 : 18}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7.5v5.5M12 16.5v.01" />
        </svg>
        {title}
      </div>
      <p>{message}</p>
      {detail && <div className="err-panel-detail">{detail}</div>}
      {(onRetry || children) && (
        <div className="err-panel-actions">
          {onRetry && (
            <button
              type="button"
              className="err-panel-retry"
              disabled={retrying}
              onClick={onRetry}
            >
              {retrying ? "接続を確認中…" : retryLabel}
            </button>
          )}
          {children}
        </div>
      )}
    </div>
  );
}

/** API接続エラー用。エラーの種類と時刻を詳細行に出す。 */
export function ApiErrorPanel({
  onRetry,
  retrying,
  error,
}: {
  onRetry: () => void;
  retrying?: boolean;
  error?: unknown;
}) {
  const status = (error as { status?: number } | undefined)?.status;
  const time = new Date().toLocaleTimeString("ja-JP", { hour12: false });
  return (
    <ErrorPanel
      title="APIサーバーに接続できません"
      message="APIサーバーから応答がありません。サーバーが起動しているか、Mac がスリープしていないかを確認してください。"
      detail={`${status ? `HTTP ${status}` : "接続失敗"} · ${time}`}
      onRetry={onRetry}
      retrying={retrying}
    />
  );
}
