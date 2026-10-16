"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { SHELL_REFRESH_EVENT } from "@/components/AppShell";
import { useToast } from "@/components/Toast";
import { ApiError, api } from "@/lib/api/client";
import type { Feed } from "@/lib/api/types";

const INTERVAL_OPTIONS = [15, 30, 60, 180, 360, 720, 1440];

function formatInterval(m: number): string {
  return m < 60 ? `${m}分` : `${m / 60}時間`;
}

function formatShort(iso: string): string {
  const d = new Date(iso);
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const now = new Date();
  const dayKey = (x: Date) =>
    x.getFullYear() * 10000 + x.getMonth() * 100 + x.getDate();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (dayKey(d) === dayKey(now)) return `今日 ${hm}`;
  if (dayKey(d) === dayKey(yesterday)) return `昨日 ${hm}`;
  return `${d.getMonth() + 1}/${d.getDate()} ${hm}`;
}

function formatAgo(iso: string): string {
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "たった今";
  if (m < 60) return `${m}分前`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}時間前`;
  return `${Math.round(h / 24)}日前`;
}

function refreshShell() {
  window.dispatchEvent(new Event(SHELL_REFRESH_EVENT));
}

type Modal =
  | { type: "delete"; feed: Feed }
  | { type: "edit"; feed: Feed; name: string; interval: string };

export default function FeedsPage() {
  const toast = useToast();
  const [feeds, setFeeds] = useState<Feed[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [addUrl, setAddUrl] = useState("");
  const [addErr, setAddErr] = useState("");
  const [addBusy, setAddBusy] = useState(false);
  const [fetching, setFetching] = useState<Set<number>>(new Set());
  const [menu, setMenu] = useState<number | null>(null);
  const [modal, setModal] = useState<Modal | null>(null);
  const [modalBusy, setModalBusy] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    try {
      setFeeds(await api.listFeeds());
      setLoadError(false);
    } catch {
      setLoadError(true);
    }
  }, []);

  useEffect(() => {
    // 初回表示時にAPIから取得する
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  // メニューの外側クリック・Escで閉じる
  useEffect(() => {
    if (menu === null) return;
    const onDown = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenu(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenu(null);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menu]);

  const replaceFeed = (f: Feed) =>
    setFeeds((fs) => fs?.map((x) => (x.id === f.id ? f : x)) ?? fs);

  const addFeed = async (e: React.FormEvent) => {
    e.preventDefault();
    const url = addUrl.trim();
    if (!url) {
      setAddErr("URLを入力してください。");
      return;
    }
    setAddBusy(true);
    setAddErr("");
    try {
      const feed = await api.createFeed(url);
      setAddUrl("");
      setFeeds((fs) => [...(fs ?? []), feed]);
      // 登録時の初回取得結果を反映するため再取得する
      void load();
      refreshShell();
      toast(
        `「${feed.name}」を追加しました。初回取得が完了しました（記事 ${feed.article_count}件）`,
        "success",
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setAddErr(
          err.code === "invalid_url"
            ? "URLの形式が正しくありません。http:// または https:// から始まるURLを入力してください。"
            : `RSS / Atom として解析できませんでした。${err.message}`,
        );
      } else if (err instanceof ApiError && err.code === "duplicate_url") {
        const dup = feeds?.find((f) => f.url === url);
        setAddErr(
          `このフィードはすでに登録されています${dup ? `（${dup.name}）` : ""}。`,
        );
      } else {
        setAddErr(
          "フィードを追加できませんでした。時間をおいて再度お試しください。",
        );
      }
    } finally {
      setAddBusy(false);
    }
  };

  const toggleEnabled = async (f: Feed) => {
    try {
      replaceFeed(await api.updateFeed(f.id, { enabled: !f.enabled }));
      refreshShell();
      toast(`${f.name} を${f.enabled ? "無効" : "有効"}にしました`);
    } catch {
      toast("有効/無効を切り替えられませんでした", "error");
    }
  };

  const fetchNow = async (f: Feed) => {
    setMenu(null);
    setFetching((s) => new Set(s).add(f.id));
    try {
      const res = await api.fetchFeed(f.id);
      replaceFeed(res.feed);
      refreshShell();
      if (res.feed.last_fetch_ok === false) {
        toast(`${f.name} の取得に失敗しました`, "error");
      } else {
        toast(
          `${f.name} を取得しました（${res.added > 0 ? `新着 ${res.added}件` : "新着なし"}）`,
          "success",
        );
      }
    } catch {
      toast(`${f.name} を取得できませんでした`, "error");
    } finally {
      setFetching((s) => {
        const n = new Set(s);
        n.delete(f.id);
        return n;
      });
    }
  };

  const readAll = async (f: Feed) => {
    setMenu(null);
    try {
      const res = await api.markFeedRead(f.id);
      if (res.count === 0) {
        toast("未読の記事はありません");
        return;
      }
      await load();
      refreshShell();
      toast(`${f.name} の ${res.count}件を既読にしました`, "success", {
        label: "元に戻す",
        onClick: async () => {
          try {
            await api.markUnread(res.article_ids);
            await load();
            refreshShell();
            toast("既読を取り消しました");
          } catch {
            toast("既読を取り消せませんでした", "error");
          }
        },
      });
    } catch {
      toast("既読にできませんでした", "error");
    }
  };

  const submitModal = async () => {
    if (!modal) return;
    setModalBusy(true);
    try {
      if (modal.type === "delete") {
        await api.deleteFeed(modal.feed.id);
        setFeeds((fs) => fs?.filter((x) => x.id !== modal.feed.id) ?? fs);
        toast(`${modal.feed.name} を削除しました`, "success");
      } else {
        const updated = await api.updateFeed(modal.feed.id, {
          name: modal.name.trim() || modal.feed.name,
          fetch_interval_minutes: Number(modal.interval),
        });
        replaceFeed(updated);
        toast("フィードを更新しました", "success");
      }
      setModal(null);
      refreshShell();
    } catch {
      toast("操作を完了できませんでした", "error");
    } finally {
      setModalBusy(false);
    }
  };

  const enabledCount = feeds?.filter((f) => f.enabled).length ?? 0;
  const errCount =
    feeds?.filter((f) => f.enabled && f.last_fetch_ok === false).length ?? 0;

  return (
    <div className="feeds-page">
      <h1 className="page-title feeds-title">購読フィード</h1>

      <form className="feed-add" onSubmit={addFeed}>
        <label htmlFor="dt-add" className="feed-add-label">
          フィードを追加
        </label>
        <div className="feed-add-row">
          <input
            id="dt-add"
            type="url"
            inputMode="url"
            className="feed-add-input"
            value={addUrl}
            placeholder="https://example.com/feed.xml"
            aria-invalid={addErr ? true : undefined}
            style={{ borderColor: addErr ? "var(--err)" : undefined }}
            onChange={(e) => {
              setAddUrl(e.target.value);
              setAddErr("");
            }}
          />
          <button type="submit" className="btn-primary" disabled={addBusy}>
            {addBusy ? "検証中…" : "追加"}
          </button>
        </div>
        {addErr && (
          <div role="alert" className="feed-add-err">
            <svg
              width="15"
              height="15"
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
            <span>{addErr}</span>
          </div>
        )}
        <div className="feed-add-hint">
          RSS 2.0 / Atom に対応。追加時に取得して解析できるかを検証します。
        </div>
      </form>

      <div className="feed-list-head">
        <h2>登録済み</h2>
        {feeds && feeds.length > 0 && (
          <span>
            {feeds.length}件 · 有効 {enabledCount}件
            {errCount > 0 ? ` · エラー ${errCount}件` : ""}
          </span>
        )}
      </div>

      {loadError && (
        <div className="feed-empty" role="alert">
          フィードを取得できませんでした。APIサーバーへの接続を確認してください。
          <br />
          <button
            type="button"
            className="btn-outline"
            onClick={() => void load()}
          >
            再読み込み
          </button>
        </div>
      )}

      {feeds && feeds.length === 0 && (
        <div className="feed-empty">
          まだフィードが登録されていません。
          <br />
          上の入力欄に購読したいサイトの RSS / Atom の URL を入力してください。
        </div>
      )}

      <div className="feed-list">
        {feeds?.map((f) => {
          const busy = fetching.has(f.id);
          const hasError = f.enabled && f.last_fetch_ok === false && !busy;
          const stColor = busy
            ? "var(--ac)"
            : !f.enabled
              ? "var(--tx3)"
              : f.last_fetch_ok === false
                ? "var(--err)"
                : f.last_fetch_ok
                  ? "var(--ok)"
                  : "var(--tx3)";
          const status = busy
            ? "取得中…"
            : !f.enabled
              ? "無効"
              : f.last_fetch_ok === false
                ? "エラー"
                : f.last_fetch_ok
                  ? "正常"
                  : "未取得";
          return (
            <div
              key={f.id}
              className="feed-row"
              style={{ opacity: f.enabled ? 1 : 0.62 }}
            >
              <div className="feed-main">
                <div className="feed-name">{f.name}</div>
                <div className="feed-url" title={f.url}>
                  {f.url}
                </div>
                {hasError && f.last_fetch_error && (
                  <div className="feed-error">{f.last_fetch_error}</div>
                )}
              </div>
              <div className="feed-status">
                <span className="feed-status-label" style={{ color: stColor }}>
                  <span
                    className="feed-status-dot"
                    style={{ background: stColor }}
                  />
                  {status}
                </span>
                <span className="feed-sub">
                  最終取得{" "}
                  {f.last_fetched_at
                    ? `${formatShort(f.last_fetched_at)}（${formatAgo(f.last_fetched_at)}）`
                    : "—"}
                </span>
              </div>
              <div className="feed-counts">
                <span>
                  記事 {f.article_count.toLocaleString("ja-JP")}件 · 未読{" "}
                  <strong
                    style={{
                      color: f.unread_count ? "var(--ac)" : "var(--tx2)",
                      fontWeight: 600,
                    }}
                  >
                    {f.unread_count}
                  </strong>
                </span>
                <span className="feed-sub">
                  取得間隔 {formatInterval(f.effective_fetch_interval_minutes)}
                </span>
              </div>
              <div
                className="feed-actions"
                ref={menu === f.id ? menuRef : undefined}
              >
                <button
                  type="button"
                  role="switch"
                  aria-checked={f.enabled}
                  aria-label="有効/無効"
                  title={
                    f.enabled
                      ? "有効（クリックで無効化）"
                      : "無効（クリックで有効化）"
                  }
                  className="switch"
                  style={{ background: f.enabled ? "var(--ok)" : "var(--off)" }}
                  onClick={() => void toggleEnabled(f)}
                >
                  <span
                    className="switch-knob"
                    style={{ left: f.enabled ? 19 : 3 }}
                  />
                </button>
                <button
                  type="button"
                  className="btn-outline btn-sm"
                  disabled={busy || !f.enabled}
                  onClick={() => void fetchNow(f)}
                >
                  {busy ? "取得中…" : "今すぐ取得"}
                </button>
                <button
                  type="button"
                  className="btn-outline btn-icon"
                  aria-label="その他の操作"
                  aria-expanded={menu === f.id}
                  onClick={() => setMenu((m) => (m === f.id ? null : f.id))}
                >
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="currentColor"
                    aria-hidden="true"
                  >
                    <circle cx="5" cy="12" r="1.7" />
                    <circle cx="12" cy="12" r="1.7" />
                    <circle cx="19" cy="12" r="1.7" />
                  </svg>
                </button>
                {menu === f.id && (
                  <div role="menu" className="feed-menu">
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setMenu(null);
                        setModal({
                          type: "edit",
                          feed: f,
                          name: f.name,
                          interval: String(f.effective_fetch_interval_minutes),
                        });
                      }}
                    >
                      名称・取得間隔を編集
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => void readAll(f)}
                    >
                      このフィードをすべて既読にする
                    </button>
                    <div className="feed-menu-sep" />
                    <button
                      type="button"
                      role="menuitem"
                      className="is-danger"
                      onClick={() => {
                        setMenu(null);
                        setModal({ type: "delete", feed: f });
                      }}
                    >
                      削除…
                    </button>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {modal && (
        <div
          className="modal-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !modalBusy) setModal(null);
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="dt-modal-t"
            className="modal"
          >
            <h2 id="dt-modal-t">
              {modal.type === "delete"
                ? "フィードを削除しますか？"
                : "フィードを編集"}
            </h2>
            {modal.type === "delete" ? (
              <p className="modal-text">
                「{modal.feed.name}」と、このフィードの記事{" "}
                {modal.feed.article_count.toLocaleString("ja-JP")}
                件を削除します。この操作は取り消せません。
              </p>
            ) : (
              <div className="modal-form">
                <label>
                  名称
                  <input
                    value={modal.name}
                    onChange={(e) =>
                      setModal({ ...modal, name: e.target.value })
                    }
                  />
                </label>
                <label>
                  取得間隔
                  <select
                    value={modal.interval}
                    onChange={(e) =>
                      setModal({ ...modal, interval: e.target.value })
                    }
                  >
                    {(INTERVAL_OPTIONS.includes(Number(modal.interval))
                      ? INTERVAL_OPTIONS
                      : [...INTERVAL_OPTIONS, Number(modal.interval)].sort(
                          (a, b) => a - b,
                        )
                    ).map((m) => (
                      <option key={m} value={m}>
                        {formatInterval(m)}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="modal-url">{modal.feed.url}</div>
              </div>
            )}
            <div className="modal-actions">
              <button
                type="button"
                className="btn-cancel"
                disabled={modalBusy}
                onClick={() => setModal(null)}
              >
                キャンセル
              </button>
              <button
                type="button"
                className="btn-ok"
                style={{
                  background:
                    modal.type === "delete" ? "var(--err)" : "var(--ac)",
                  color: modal.type === "delete" ? "#fff" : "var(--onAc)",
                }}
                disabled={modalBusy}
                onClick={() => void submitModal()}
              >
                {modal.type === "delete" ? "削除する" : "保存"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
