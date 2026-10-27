"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { SHELL_REFRESH_EVENT } from "@/components/AppShell";
import { useToast } from "@/components/Toast";
import {
  ApiErrorPanel,
  ErrorPanel,
  LoadingSkeleton,
} from "@/components/states";
import { api } from "@/lib/api/client";
import {
  ArticlePreview,
  type PreviewPosition,
} from "./_components/ArticlePreview";
import type {
  ArticleDetail,
  GenerationState,
  SummaryConfig,
  SummaryDetail,
  SummaryListItem,
  SummarySource,
} from "@/lib/api/types";

const POLL_MS = 2000;
const PREVIEW_POS_KEY = "summary-preview-position";
const WEEKDAYS = ["日", "月", "火", "水", "木", "金", "土"];
const STEP_LABELS = [
  "対象期間の記事を収集",
  "Claude Code で要約を作成",
  "サマリを保存",
];
const SCHEDULE_TEXT: Record<SummaryConfig["interval"], string> = {
  daily: "毎日 0:00 以降（前日を対象）",
  weekly: "毎週 月曜 0:00 以降（前週の月曜〜日曜を対象）",
  monthly: "毎月1日 0:00 以降（前月を対象）",
};

const p2 = (n: number) => String(n).padStart(2, "0");
const hm = (d: Date) => `${p2(d.getHours())}:${p2(d.getMinutes())}`;
const mdw = (d: Date) =>
  `${d.getMonth() + 1}月${d.getDate()}日（${WEEKDAYS[d.getDay()]}）`;

function nextRunText(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}/${p2(d.getMonth() + 1)}/${p2(d.getDate())}（${WEEKDAYS[d.getDay()]}）${d.getHours()}:${p2(d.getMinutes())} 以降`;
}

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function shortDate(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(d, now)) return `今日 ${hm(d)}`;
  if (sameDay(d, yesterday)) return `昨日 ${hm(d)}`;
  return `${d.getMonth() + 1}/${d.getDate()} ${hm(d)}`;
}

// period_end は排他的な終端なので、表示は1ミリ秒前の日付にする
function periodEnd(s: SummaryListItem): Date {
  return new Date(new Date(s.period_end).getTime() - 1);
}

function periodLabel(s: SummaryListItem): string {
  const start = new Date(s.period_start);
  return `${start.getFullYear()}年${mdw(start)}〜${mdw(periodEnd(s))}`;
}

function periodShort(s: SummaryListItem): string {
  const start = new Date(s.period_start);
  const end = periodEnd(s);
  return `${start.getMonth() + 1}/${start.getDate()}〜${end.getMonth() + 1}/${end.getDate()}`;
}

// 日本語の解除見込みなどはそのまま、元の文言を強調して見せる
function failureMessage(g: GenerationState) {
  if (!g.rate_limited) return g.error ?? "原因不明のエラーが発生しました。";
  return (
    <>
      AI（Claude Code）の利用制限に達しました。
      {g.reset_text ? (
        <>
          制限は <strong>{g.reset_text}</strong> 頃に解除される見込みです。
        </>
      ) : null}
      解除後に再試行するか、次回の定期実行をお待ちください。
    </>
  );
}

function refreshShell() {
  window.dispatchEvent(new Event(SHELL_REFRESH_EVENT));
}

function scrollTop() {
  document.querySelector(".main")?.scrollTo(0, 0);
}

function GenerateIcon() {
  return (
    <svg
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M20 11a8 8 0 1 0-2.3 5.7" />
      <path d="M20 4v7h-7" />
    </svg>
  );
}

export default function SummaryPage() {
  const router = useRouter();
  const toast = useToast();
  const [list, setList] = useState<SummaryListItem[]>([]);
  const [detail, setDetail] = useState<SummaryDetail | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [generation, setGeneration] = useState<GenerationState | null>(null);
  const [dismissed, setDismissed] = useState<number | null>(null);
  // 設定取得前は null（誤った周期を一瞬出さない）
  const [schedule, setSchedule] = useState<SummaryConfig | null>(null);
  const [noFeeds, setNoFeeds] = useState(false);
  // 画面遷移せずプレビュー表示している元記事
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [previewPos, setPreviewPos] = useState<PreviewPosition>("right");
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [starting, setStarting] = useState(false);
  // 古いレスポンスで画面を上書きしないための世代
  const generationRef = useRef(0);
  const prevState = useRef<GenerationState["state"] | null>(null);

  const load = useCallback(
    async (id: number | null) => {
      const gen = ++generationRef.current;
      try {
        const [items, state, cfg, feeds] = await Promise.all([
          api.listSummaries(),
          api.getGeneration(dismissed),
          api.getSummaryConfig(),
          api.listFeeds(),
        ]);
        const target = items.find((s) => s.id === id) ?? items[0] ?? null;
        const d = target ? await api.getSummary(target.id) : null;
        if (gen !== generationRef.current) return;
        setList(items);
        setDetail(d);
        setSelected(d && !d.is_latest ? d.id : null);
        setGeneration(state);
        setSchedule(cfg);
        setNoFeeds(feeds.length === 0);
        setLoadError(false);
      } catch {
        if (gen !== generationRef.current) return;
        setLoadError(true);
      }
      setLoaded(true);
    },
    [dismissed],
  );

  useEffect(() => {
    const saved = localStorage.getItem(PREVIEW_POS_KEY);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (saved === "right" || saved === "bottom") setPreviewPos(saved);
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(null);
  }, [load]);

  // 生成中は状態を定期的に確認し、完了したらサマリを読み直す
  const running = generation?.state === "running";
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => {
      api
        .getGeneration(dismissed)
        .then(setGeneration)
        .catch(() => {});
    }, POLL_MS);
    return () => clearInterval(t);
  }, [running, dismissed]);

  useEffect(() => {
    const prev = prevState.current;
    const cur = generation?.state ?? null;
    prevState.current = cur;
    if (prev !== "running") return;
    if (cur === "idle") {
      toast("サマリを生成しました", "success");
      refreshShell();
      // eslint-disable-next-line react-hooks/set-state-in-effect
      void load(null);
    } else if (cur === "failed") {
      toast(
        generation?.rate_limited
          ? "サマリの生成に失敗しました（AIの利用制限）"
          : "サマリの生成に失敗しました",
        "error",
      );
    }
  }, [generation, load, toast]);

  const generate = async () => {
    if (starting || running) return;
    setStarting(true);
    try {
      const state = await api.generateSummary();
      setDismissed(null);
      setGeneration(state);
      setSelected(null);
      scrollTop();
    } catch (e) {
      const err = e as { status?: number; message?: string };
      toast(
        err.status === 409
          ? (err.message ?? "対象期間に記事がありません")
          : "サマリの生成を開始できませんでした",
        "error",
      );
    } finally {
      setStarting(false);
    }
  };

  const select = (id: number) => {
    setSelected(id);
    setPreviewId(null);
    scrollTop();
    void api
      .getSummary(id)
      .then((d) => {
        setDetail(d);
        setSelected(d.is_latest ? null : d.id);
      })
      .catch(() => toast("サマリの取得に失敗しました", "error"));
  };

  const selectLatest = () => {
    if (list[0]) select(list[0].id);
  };

  const openSource = (s: SummarySource) => {
    setPreviewId((cur) => (cur === s.id ? null : s.id));
  };

  const changePreviewPos = (p: PreviewPosition) => {
    setPreviewPos(p);
    localStorage.setItem(PREVIEW_POS_KEY, p);
  };

  // 取得できた元記事を既読にし、サマリ内の表示にも反映する
  const markSourceRead = (a: ArticleDetail) => {
    if (a.is_read) return;
    void api.setArticleRead(a.id, true).then(
      () => {
        refreshShell();
        setDetail(
          (d) =>
            d && {
              ...d,
              topics: d.topics.map((t) => ({
                ...t,
                sources: t.sources.map((s) =>
                  s.id === a.id ? { ...s, is_read: true } : s,
                ),
              })),
            },
        );
      },
      () => {},
    );
  };

  const dismiss = () => {
    setDismissed(generation?.job_id ?? null);
    setGeneration({ ...generation!, state: "idle" });
  };

  // 表示中のサマリが引用している元記事だけをプレビューする
  const previewOpen =
    previewId !== null &&
    !!detail?.topics.some((t) => t.sources.some((s) => s.id === previewId));

  const failed = generation?.state === "failed";
  const busy = running || starting;
  const noSummary = loaded && !loadError && !detail && !running;

  const generateButton = (cls: string) => (
    <button
      type="button"
      className={cls}
      disabled={busy}
      onClick={() => void generate()}
    >
      <GenerateIcon />
      今すぐサマリを生成
    </button>
  );

  return (
    <div className={`sum-page${previewOpen ? ` has-pv pv-${previewPos}` : ""}`}>
      <div className="sum-wrap">
        <div className="sum-main">
          <div className="sum-head">
            <h1 className="page-title sum-title">サマリ</h1>
            {generateButton("sum-gen-btn")}
          </div>
          {generateButton("sum-gen-btn-m")}

          {loadError && (
            <ApiErrorPanel
              onRetry={() => {
                setLoaded(false);
                void load(selected);
              }}
            />
          )}
          {!loaded && <LoadingSkeleton />}

          {running && generation && (
            <div role="status" className="sum-progress">
              <div className="sum-progress-title">
                <span className="skel-spin" aria-hidden="true" />
                サマリを生成しています…
              </div>
              <p>
                {generation.period_start
                  ? `${new Date(generation.period_start).getMonth() + 1}月${new Date(generation.period_start).getDate()}日以降の`
                  : ""}
                記事{" "}
                {generation.article_count != null
                  ? `${generation.article_count}件を`
                  : "を"}
                要約中です。数分かかる場合があります。画面を離れても処理は続きます。
              </p>
              <ol>
                {STEP_LABELS.map((label, i) => {
                  const st =
                    i < generation.step - 1
                      ? "done"
                      : i === generation.step - 1
                        ? "active"
                        : "todo";
                  return (
                    <li key={label} className={`sum-step is-${st}`}>
                      <span className="sum-step-mark">
                        {st === "done" ? "✓" : ""}
                      </span>
                      {label}
                      {st === "active" ? "…" : ""}
                    </li>
                  );
                })}
              </ol>
            </div>
          )}

          {failed && generation && (
            <ErrorPanel
              compact
              title="サマリの生成に失敗しました"
              message={failureMessage(generation)}
              detail={`${generation.rate_limited ? "rate_limit_exceeded" : "failed"} · job #${generation.job_id}`}
              onRetry={() => void generate()}
            >
              <button
                type="button"
                className="err-panel-close"
                onClick={dismiss}
              >
                閉じる
              </button>
            </ErrorPanel>
          )}

          {noSummary && (
            <div className="sum-empty">
              <div className="sum-empty-title">まだサマリがありません</div>
              <p>
                {noFeeds
                  ? "購読フィードを登録すると、定期実行のタイミングで過去の記事をもとにサマリが作成されます。"
                  : "次回の定期実行を待つか、今すぐ生成できます。"}
              </p>
              <button
                type="button"
                className="sum-empty-btn"
                disabled={!noFeeds && busy}
                onClick={() =>
                  noFeeds ? router.push("/feeds") : void generate()
                }
              >
                {noFeeds ? "フィードを登録する" : "今すぐサマリを生成"}
              </button>
            </div>
          )}

          {detail && (
            <article>
              {detail.is_latest && detail.new_since.count > 0 && (
                <Link href="/articles" className="sum-since">
                  <span className="sum-since-dot" aria-hidden="true" />
                  <span className="sum-since-text">
                    このサマリ以降の新着{" "}
                    <strong>{detail.new_since.count}件</strong>
                    （未読 {detail.new_since.unread_count}件）
                  </span>
                  <span className="sum-since-go">記事一覧へ →</span>
                </Link>
              )}
              <div className="sum-tags">
                <span className="sum-tag">{detail.kind}</span>
                {detail.is_latest && (
                  <span className="sum-tag sum-tag-latest">最新</span>
                )}
                {!detail.is_latest && (
                  <button
                    type="button"
                    className="sum-back-latest"
                    onClick={selectLatest}
                  >
                    最新のサマリに戻る
                  </button>
                )}
              </div>
              <h2 className="sum-period">{periodLabel(detail)}</h2>
              <div className="sum-stats">
                <span>生成 {shortDate(detail.created_at)}</span>
                <span>対象記事 {detail.article_count}件</span>
                <span>{detail.topic_count}トピック</span>
              </div>
              <p className="sum-lead">{detail.overview}</p>

              {detail.topics.map((t, i) => (
                <section key={i} className="sum-topic">
                  <div className="sum-topic-head">
                    <span className="sum-topic-num">{p2(i + 1)}</span>
                    <h3>{t.title}</h3>
                  </div>
                  {t.summary
                    .split(/\n+/)
                    .filter(Boolean)
                    .map((para, j) => (
                      <p key={j} className="sum-para">
                        {para}
                      </p>
                    ))}
                  <div className="sum-sources">
                    <div className="sum-sources-head">
                      元記事 {t.sources.length}件
                    </div>
                    {t.sources.map((s) => (
                      <div
                        key={s.id}
                        className={`sum-src${previewOpen && previewId === s.id ? " is-on" : ""}`}
                      >
                        <button
                          type="button"
                          className={`sum-src-open${s.is_read ? "" : " is-unread"}`}
                          aria-expanded={previewOpen && previewId === s.id}
                          onClick={() => openSource(s)}
                        >
                          <span className="sum-src-dot" aria-hidden="true" />
                          <span className="sum-src-body">
                            <span className="sum-src-title">{s.title}</span>
                            <span className="sum-src-meta">
                              {s.feed_name}
                              {s.published_at
                                ? ` · ${shortDate(s.published_at)}`
                                : ""}
                            </span>
                          </span>
                        </button>
                        {s.url && (
                          <a
                            className="sum-src-ext"
                            href={s.url}
                            target="_blank"
                            rel="noopener"
                            aria-label="元記事を新しいタブで開く"
                            title="元記事を開く"
                          >
                            <svg
                              width="15"
                              height="15"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.8"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            >
                              <path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6" />
                            </svg>
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              ))}
            </article>
          )}
        </div>

        {previewOpen && previewId !== null && (
          <ArticlePreview
            id={previewId}
            position={previewPos}
            onPositionChange={changePreviewPos}
            onClose={() => setPreviewId(null)}
            onLoaded={markSourceRead}
          />
        )}
      </div>

      {list.length > 0 && (
        <aside className="sum-side">
          <div className="sum-side-title">サマリ一覧</div>
          <div className="sum-side-list">
            {list.map((s) => (
              <button
                key={s.id}
                type="button"
                className={`sum-side-item${detail?.id === s.id ? " is-on" : ""}`}
                onClick={() => select(s.id)}
              >
                <span className="sum-side-period">{periodShort(s)}</span>
                <span className="sum-side-meta">
                  {s.kind} · 生成 {shortDate(s.created_at)} · {s.article_count}
                  件
                </span>
              </button>
            ))}
          </div>
          {schedule && (
            <p className="sum-side-note">
              定期実行：{SCHEDULE_TEXT[schedule.interval]}
              <br />
              次回実行予定：{nextRunText(schedule.next_run_at)}
            </p>
          )}
        </aside>
      )}
    </div>
  );
}
