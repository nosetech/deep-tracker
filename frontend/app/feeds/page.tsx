"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { SHELL_REFRESH_EVENT } from "@/components/AppShell";
import { useToast } from "@/components/Toast";
import { ApiErrorPanel, LoadingSkeleton } from "@/components/states";
import { ApiError, api } from "@/lib/api/client";
import type { Feed, FeedGroup } from "@/lib/api/types";
import { describeFeedError } from "@/lib/feed-error";
import {
  COLLAPSED_GROUPS_STORAGE_KEY,
  groupFeeds,
  parseCollapsedGroups,
  sectionKey,
  serializeCollapsedGroups,
} from "@/lib/feed-groups";
import { FeedGroupSection } from "./_components/FeedGroupSection";
import { FeedRow, formatInterval } from "./_components/FeedRow";

const INTERVAL_OPTIONS = [15, 30, 60, 180, 360, 720, 1440];

// グループの選択欄の値: "" は未分類、NEW_GROUP は新規作成、それ以外はグループID
const NEW_GROUP = "__new";

const GROUP_FAILED =
  "グループの操作に失敗しました。時間をおいて再試行してください。";
const GROUP_NAME_EMPTY = "グループ名を入力してください。";
const GROUP_NAME_DUPLICATE = "同じ名前のグループがすでにあります。";
const GROUP_NOT_FOUND =
  "選択したグループが見つかりません。画面を再読み込みしてください。";

function refreshShell() {
  window.dispatchEvent(new Event(SHELL_REFRESH_EVENT));
}

/** グループ作成・名前変更のエラーを、入力欄の下に出す文言にする（該当しなければ null） */
function groupNameError(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  if (err.code === "duplicate_name") return GROUP_NAME_DUPLICATE;
  if (err.code === "invalid_name") return GROUP_NAME_EMPTY;
  return null;
}

type Modal =
  | { type: "delete"; feed: Feed }
  | {
      type: "edit";
      feed: Feed;
      name: string;
      url: string;
      interval: string;
      group: string;
      groupName: string;
      err: string;
      errCode?: string;
      gnErr: string;
    }
  | { type: "group"; group: FeedGroup | null; name: string; err: string }
  | { type: "groupDelete"; group: FeedGroup; count: number };

type Section = { group: FeedGroup | null; feeds: Feed[] };

function GroupSelect({
  value,
  groups,
  onChange,
  className,
  ariaLabel,
}: {
  value: string;
  groups: FeedGroup[];
  onChange: (v: string) => void;
  className?: string;
  ariaLabel?: string;
}) {
  const sorted = groupFeeds(groups, []).flatMap((s) =>
    s.group ? [s.group] : [],
  );
  return (
    <select
      className={className}
      value={value}
      aria-label={ariaLabel}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">未分類</option>
      {sorted.map((g) => (
        <option key={g.id} value={g.id}>
          {g.name}
        </option>
      ))}
      <option value={NEW_GROUP}>新しいグループを作成…</option>
    </select>
  );
}

export default function FeedsPage() {
  const toast = useToast();
  const [feeds, setFeeds] = useState<Feed[] | null>(null);
  const [groups, setGroups] = useState<FeedGroup[]>([]);
  const [loadError, setLoadError] = useState(false);
  const [addUrl, setAddUrl] = useState("");
  const [addGroup, setAddGroup] = useState("");
  const [addGroupName, setAddGroupName] = useState("");
  const [addErr, setAddErr] = useState("");
  const [addErrCode, setAddErrCode] = useState("");
  const [addBusy, setAddBusy] = useState(false);
  const [fetching, setFetching] = useState<Set<number>>(new Set());
  // フィードのメニューは "f:<id>"、グループ見出しのメニューは "g:<セクションのキー>"
  const [menu, setMenu] = useState<string | null>(null);
  const [modal, setModal] = useState<Modal | null>(null);
  const [modalBusy, setModalBusy] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const menuRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    try {
      const [fs, gs] = await Promise.all([
        api.listFeeds(),
        api.listFeedGroups(),
      ]);
      setFeeds(fs);
      setGroups(gs);
      setLoadError(false);
    } catch {
      setLoadError(true);
    }
  }, []);

  useEffect(() => {
    // 初回表示時にAPIから取得し、折りたたみ状態をブラウザの保存値から復元する
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    try {
      setCollapsed(
        parseCollapsedGroups(
          localStorage.getItem(COLLAPSED_GROUPS_STORAGE_KEY),
        ),
      );
    } catch {
      // ストレージが使えない場合はすべて展開
    }
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

  const toggleCollapsed = (key: string) => {
    setCollapsed((cur) => {
      const next = new Set(cur);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      try {
        localStorage.setItem(
          COLLAPSED_GROUPS_STORAGE_KEY,
          serializeCollapsedGroups(next),
        );
      } catch {
        // 保存できなくても表示は切り替える
      }
      return next;
    });
  };

  /** 「新しいグループを作成…」の名前を検証して作成する。失敗時はエラー文言を返す */
  const createGroupFor = async (
    name: string,
  ): Promise<{ group: FeedGroup } | { error: string }> => {
    if (!name) return { error: GROUP_NAME_EMPTY };
    try {
      return { group: await api.createFeedGroup(name) };
    } catch (err) {
      return { error: groupNameError(err) ?? GROUP_FAILED };
    }
  };

  // 後続の操作が失敗したときに、作成したばかりのグループを取り消す
  const discardGroup = async (g: FeedGroup) => {
    try {
      await api.deleteFeedGroup(g.id);
    } catch {
      // 残っても空のグループとして表示されるだけなので無視する
    }
  };

  const addFeed = async (e: React.FormEvent) => {
    e.preventDefault();
    const url = addUrl.trim();
    if (!url) {
      setAddErr("URLを入力してください。");
      return;
    }
    const isNew = addGroup === NEW_GROUP;
    if (isNew && !addGroupName.trim()) {
      setAddErr(GROUP_NAME_EMPTY);
      setAddErrCode("");
      return;
    }
    setAddBusy(true);
    setAddErr("");
    setAddErrCode("");
    let created: FeedGroup | null = null;
    try {
      if (isNew) {
        const res = await createGroupFor(addGroupName.trim());
        if ("error" in res) {
          setAddErr(res.error);
          return;
        }
        created = res.group;
      }
      const groupId = created
        ? created.id
        : addGroup && groups.some((g) => String(g.id) === addGroup)
          ? Number(addGroup)
          : null;
      const feed = await api.createFeed(url, groupId);
      setAddUrl("");
      setAddGroupName("");
      // 続けて同じグループに登録できるよう、選択中のグループは保持する
      setAddGroup(groupId === null ? "" : String(groupId));
      setFeeds((fs) => [...(fs ?? []), feed]);
      if (created) {
        const g = created;
        setGroups((gs) => [...gs, g]);
      }
      // 登録時の初回取得結果を反映するため再取得する
      void load();
      refreshShell();
      toast(
        `「${feed.name}」を追加しました${created ? `（グループ「${created.name}」を作成）` : ""}。初回取得が完了しました（記事 ${feed.article_count}件）`,
        "success",
      );
    } catch (err) {
      // サーバが失敗を返した場合だけ取り消す（応答が失われただけなら登録済みの可能性がある）
      if (created && err instanceof ApiError) void discardGroup(created);
      if (err instanceof ApiError && err.status === 422) {
        const view =
          err.code === "invalid_url" || err.code === "group_not_found"
            ? null
            : describeFeedError(err);
        setAddErr(
          err.code === "invalid_url"
            ? "URLの形式が正しくありません。http:// または https:// から始まるURLを入力してください。"
            : err.code === "group_not_found"
              ? GROUP_NOT_FOUND
              : (view?.message ??
                "フィードを追加できませんでした。時間をおいて再度お試しください。"),
        );
        setAddErrCode(view?.code ?? "");
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

  /** 一括既読の結果をトーストで知らせる（「元に戻す」付き） */
  const afterBulkRead = async (
    res: { count: number; article_ids: number[] },
    label: string,
  ) => {
    if (res.count === 0) {
      toast("未読の記事はありません");
      return;
    }
    await load();
    refreshShell();
    toast(`${label} の ${res.count}件を既読にしました`, "success", {
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
  };

  const readAll = async (f: Feed) => {
    setMenu(null);
    try {
      await afterBulkRead(await api.markFeedRead(f.id), f.name);
    } catch {
      toast("既読にできませんでした", "error");
    }
  };

  const groupReadAll = async (sec: Section) => {
    setMenu(null);
    try {
      const res = await api.markFeedGroupRead(sec.group?.id ?? null);
      await afterBulkRead(res, sec.group?.name ?? "未分類");
    } catch {
      toast(GROUP_FAILED, "error");
    }
  };

  const groupSetEnabled = async (sec: Section, enabled: boolean) => {
    setMenu(null);
    const name = sec.group?.name ?? "未分類";
    const label = enabled ? "有効" : "無効";
    try {
      const res = await api.setFeedGroupEnabled(sec.group?.id ?? null, enabled);
      if (res.count === 0) {
        toast(`${name} のフィードはすべて${label}です`);
        return;
      }
      await load();
      refreshShell();
      toast(`${name} の ${res.count}件を${label}にしました`);
    } catch {
      toast(GROUP_FAILED, "error");
    }
  };

  const submitModal = async () => {
    if (!modal) return;
    if (modal.type === "group") {
      const name = modal.name.trim();
      if (!name) {
        setModal({ ...modal, err: GROUP_NAME_EMPTY });
        return;
      }
      setModalBusy(true);
      try {
        if (modal.group) {
          await api.renameFeedGroup(modal.group.id, name);
          toast("グループ名を変更しました", "success");
        } else {
          await api.createFeedGroup(name);
          toast(`グループ「${name}」を作成しました`, "success");
        }
        setModal(null);
        await load();
      } catch (err) {
        const message = groupNameError(err);
        if (message) setModal({ ...modal, err: message });
        else toast(GROUP_FAILED, "error");
      } finally {
        setModalBusy(false);
      }
      return;
    }
    if (modal.type === "groupDelete") {
      setModalBusy(true);
      try {
        await api.deleteFeedGroup(modal.group.id);
        setModal(null);
        const key = sectionKey(modal.group.id);
        if (collapsed.has(key)) toggleCollapsed(key);
        if (addGroup === String(modal.group.id)) setAddGroup("");
        await load();
        toast(`グループ「${modal.group.name}」を削除しました`, "success");
      } catch {
        toast(GROUP_FAILED, "error");
      } finally {
        setModalBusy(false);
      }
      return;
    }
    if (modal.type === "edit" && modal.group === NEW_GROUP) {
      if (!modal.groupName.trim()) {
        setModal({ ...modal, gnErr: GROUP_NAME_EMPTY });
        return;
      }
    }
    setModalBusy(true);
    let created: FeedGroup | null = null;
    try {
      if (modal.type === "delete") {
        await api.deleteFeed(modal.feed.id);
        setFeeds((fs) => fs?.filter((x) => x.id !== modal.feed.id) ?? fs);
        toast(`${modal.feed.name} を削除しました`, "success");
        void load();
      } else {
        if (modal.group === NEW_GROUP) {
          const res = await createGroupFor(modal.groupName.trim());
          if ("error" in res) {
            if (res.error === GROUP_FAILED) toast(GROUP_FAILED, "error");
            else setModal({ ...modal, gnErr: res.error });
            return;
          }
          created = res.group;
        }
        const groupId = created
          ? created.id
          : modal.group
            ? Number(modal.group)
            : null;
        const updated = await api.updateFeed(modal.feed.id, {
          name: modal.name.trim() || modal.feed.name,
          fetch_interval_minutes: Number(modal.interval),
          // URLが変わったときだけ送る（変更時はバックエンドが取得・解析を検証する）
          ...(modal.url.trim() !== modal.feed.url
            ? { url: modal.url.trim() }
            : {}),
          ...(groupId !== modal.feed.group_id ? { group_id: groupId } : {}),
        });
        replaceFeed(updated);
        if (created) {
          const g = created;
          setGroups((gs) => [...gs, g]);
        }
        toast(
          created
            ? `フィードを更新しました（グループ「${created.name}」を作成）`
            : "フィードを更新しました",
          "success",
        );
        void load();
      }
      setModal(null);
      refreshShell();
    } catch (err) {
      if (created && err instanceof ApiError) void discardGroup(created);
      if (modal.type === "edit" && err instanceof ApiError && err.code) {
        const view = describeFeedError(err);
        const message =
          err.code === "invalid_url"
            ? "URLの形式が正しくありません。http:// または https:// から始まるURLを入力してください。"
            : err.code === "duplicate_url"
              ? "このフィードはすでに登録されています。"
              : err.code === "group_not_found"
                ? GROUP_NOT_FOUND
                : (view?.message ?? "");
        if (message) {
          setModal({ ...modal, err: message, errCode: view?.code });
          return;
        }
      }
      toast("操作を完了できませんでした", "error");
    } finally {
      setModalBusy(false);
    }
  };

  const enabledCount = feeds?.filter((f) => f.enabled).length ?? 0;
  const errCount =
    feeds?.filter((f) => f.enabled && f.last_fetch_ok === false).length ?? 0;
  const grouped = groups.length > 0;
  const sections: Section[] = grouped ? groupFeeds(groups, feeds ?? []) : [];

  const renderRow = (f: Feed) => {
    const key = `f:${f.id}`;
    return (
      <FeedRow
        key={f.id}
        feed={f}
        busy={fetching.has(f.id)}
        menuOpen={menu === key}
        menuRef={menuRef}
        onToggleEnabled={() => void toggleEnabled(f)}
        onFetch={() => void fetchNow(f)}
        onToggleMenu={() => setMenu((m) => (m === key ? null : key))}
        onEdit={() => {
          setMenu(null);
          setModal({
            type: "edit",
            feed: f,
            name: f.name,
            url: f.url,
            interval: String(f.effective_fetch_interval_minutes),
            group:
              f.group_id !== null && groups.some((g) => g.id === f.group_id)
                ? String(f.group_id)
                : "",
            groupName: "",
            err: "",
            gnErr: "",
          });
        }}
        onReadAll={() => void readAll(f)}
        onDelete={() => {
          setMenu(null);
          setModal({ type: "delete", feed: f });
        }}
      />
    );
  };

  const modalTitle =
    modal?.type === "delete"
      ? "フィードを削除しますか？"
      : modal?.type === "edit"
        ? "フィードを編集"
        : modal?.type === "groupDelete"
          ? "グループを削除しますか？"
          : modal?.group
            ? "グループ名を変更"
            : "グループを作成";
  const isDanger = modal?.type === "delete" || modal?.type === "groupDelete";
  const okLabel = isDanger
    ? "削除する"
    : modal?.type === "group"
      ? modal.group
        ? "保存"
        : "作成"
      : modalBusy
        ? "検証中…"
        : "保存";

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
              setAddErrCode("");
            }}
          />
          <GroupSelect
            className="feed-add-group"
            ariaLabel="所属グループ"
            value={addGroup}
            groups={groups}
            onChange={(v) => {
              setAddGroup(v);
              setAddErr("");
              setAddErrCode("");
            }}
          />
          <button type="submit" className="btn-primary" disabled={addBusy}>
            {addBusy ? "検証中…" : "追加"}
          </button>
        </div>
        {addGroup === NEW_GROUP && (
          <label className="feed-add-newgroup">
            新しいグループ名
            <input
              value={addGroupName}
              placeholder="例: AWS障害情報"
              onChange={(e) => {
                setAddGroupName(e.target.value);
                setAddErr("");
                setAddErrCode("");
              }}
            />
          </label>
        )}
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
            <div className="feed-add-err-body">
              <span>{addErr}</span>
              {addErrCode && (
                <div className="feed-add-err-code">{addErrCode}</div>
              )}
            </div>
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
        {feeds && (
          <button
            type="button"
            className="btn-outline feed-group-create"
            onClick={() => {
              setMenu(null);
              setModal({ type: "group", group: null, name: "", err: "" });
            }}
          >
            <svg
              aria-hidden="true"
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            >
              <path d="M12 5v14M5 12h14" />
            </svg>
            グループを作成
          </button>
        )}
      </div>

      {loadError && <ApiErrorPanel onRetry={() => void load()} />}

      {!feeds && !loadError && <LoadingSkeleton list />}

      {feeds && feeds.length === 0 && (
        <div className="feed-empty">
          まだフィードが登録されていません。
          <br />
          上の入力欄に購読したいサイトの RSS / Atom の URL を入力してください。
        </div>
      )}

      {feeds && !grouped && (
        <div className="feed-list">{feeds.map(renderRow)}</div>
      )}

      {feeds && grouped && (
        <div className="feed-groups">
          {sections.map((sec) => {
            const key = sectionKey(sec.group?.id ?? null);
            const menuKey = `g:${key}`;
            return (
              <FeedGroupSection
                key={key}
                group={sec.group}
                feeds={sec.feeds}
                expanded={!collapsed.has(key)}
                menuOpen={menu === menuKey}
                menuRef={menuRef}
                onToggleExpanded={() => toggleCollapsed(key)}
                onToggleMenu={() =>
                  setMenu((m) => (m === menuKey ? null : menuKey))
                }
                onRename={() => {
                  setMenu(null);
                  if (sec.group)
                    setModal({
                      type: "group",
                      group: sec.group,
                      name: sec.group.name,
                      err: "",
                    });
                }}
                onSetEnabled={(enabled) => void groupSetEnabled(sec, enabled)}
                onReadAll={() => void groupReadAll(sec)}
                onDelete={() => {
                  setMenu(null);
                  if (sec.group)
                    setModal({
                      type: "groupDelete",
                      group: sec.group,
                      count: sec.feeds.length,
                    });
                }}
              >
                {sec.feeds.map(renderRow)}
              </FeedGroupSection>
            );
          })}
        </div>
      )}

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
            <h2 id="dt-modal-t">{modalTitle}</h2>
            {modal.type === "delete" && (
              <p className="modal-text">
                「{modal.feed.name}」と、このフィードの記事{" "}
                {modal.feed.article_count.toLocaleString("ja-JP")}
                件を削除します。この操作は取り消せません。
              </p>
            )}
            {modal.type === "groupDelete" && (
              <p className="modal-text">
                グループ「{modal.group.name}」を削除します。所属するフィード{" "}
                {modal.count}件は削除されず「未分類」に移動します。
              </p>
            )}
            {modal.type === "group" && (
              <div className="modal-form">
                <div className="modal-field">
                  <label>
                    グループ名
                    <input
                      value={modal.name}
                      placeholder="例: AWS障害情報"
                      aria-invalid={modal.err ? true : undefined}
                      style={{
                        borderColor: modal.err ? "var(--err)" : undefined,
                      }}
                      onChange={(e) =>
                        setModal({ ...modal, name: e.target.value, err: "" })
                      }
                    />
                  </label>
                  {modal.err && (
                    <div role="alert" className="modal-field-err">
                      <span>{modal.err}</span>
                    </div>
                  )}
                </div>
              </div>
            )}
            {modal.type === "edit" && (
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
                  URL
                  <input
                    type="url"
                    inputMode="url"
                    value={modal.url}
                    aria-invalid={modal.err ? true : undefined}
                    style={{
                      borderColor: modal.err ? "var(--err)" : undefined,
                    }}
                    onChange={(e) =>
                      setModal({
                        ...modal,
                        url: e.target.value,
                        err: "",
                        errCode: undefined,
                      })
                    }
                  />
                </label>
                {modal.err && (
                  <div role="alert" className="feed-add-err">
                    <div className="feed-add-err-body">
                      <span>{modal.err}</span>
                      {modal.errCode && (
                        <div className="feed-add-err-code">{modal.errCode}</div>
                      )}
                    </div>
                  </div>
                )}
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
                <label>
                  グループ
                  <GroupSelect
                    value={modal.group}
                    groups={groups}
                    onChange={(v) =>
                      setModal({ ...modal, group: v, gnErr: "" })
                    }
                  />
                </label>
                {modal.group === NEW_GROUP && (
                  <div className="modal-field">
                    <label>
                      新しいグループ名
                      <input
                        value={modal.groupName}
                        aria-invalid={modal.gnErr ? true : undefined}
                        style={{
                          borderColor: modal.gnErr ? "var(--err)" : undefined,
                        }}
                        onChange={(e) =>
                          setModal({
                            ...modal,
                            groupName: e.target.value,
                            gnErr: "",
                          })
                        }
                      />
                    </label>
                    {modal.gnErr && (
                      <div role="alert" className="modal-field-err">
                        <span>{modal.gnErr}</span>
                      </div>
                    )}
                  </div>
                )}
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
                  background: isDanger ? "var(--err)" : "var(--ac)",
                  color: isDanger ? "#fff" : "var(--onAc)",
                }}
                disabled={modalBusy}
                onClick={() => void submitModal()}
              >
                {okLabel}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
