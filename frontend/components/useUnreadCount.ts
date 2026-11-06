"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import {
  applyUnreadToTitle,
  createUnreadPoller,
  faviconDataUrl,
} from "@/lib/tab-unread";

// 未読件数を取得し、定期ポーリングする。refreshKey が変わると即時に再取得する
export function useUnreadCount(refreshKey: unknown): number {
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    const poller = createUnreadPoller({
      fetchTotal: async () => (await api.getUnreadCounts()).total,
      onChange: setUnread,
      isVisible: () => document.visibilityState === "visible",
    });
    const onVisibility = () => poller.onVisibilityChange();
    document.addEventListener("visibilitychange", onVisibility);
    poller.start();
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      poller.stop();
    };
  }, [refreshKey]);

  return unread;
}

// タブのタイトル先頭の件数とファビコンのドットを、未読件数に合わせる
export function useTabUnreadIndicator(unread: number) {
  useEffect(() => {
    const titleEl = document.querySelector("title");
    const sync = () => {
      const next = applyUnreadToTitle(document.title, unread);
      if (next !== document.title) document.title = next;
    };
    sync();
    // ページ遷移で metadata によりタイトルが再設定されても付け直す
    const observer = titleEl ? new MutationObserver(sync) : null;
    observer?.observe(titleEl!, {
      childList: true,
      characterData: true,
      subtree: true,
    });
    return () => observer?.disconnect();
  }, [unread]);

  useEffect(() => {
    const links = Array.from(
      document.querySelectorAll<HTMLLinkElement>('link[rel~="icon"]'),
    );
    if (unread > 0) {
      // 既存のicon（SVG・ico）を退避して、ドット付きSVGだけを有効にする
      const link = document.createElement("link");
      link.rel = "icon";
      link.type = "image/svg+xml";
      link.href = faviconDataUrl(true);
      link.dataset.unreadIcon = "1";
      links.forEach((l) => l.setAttribute("data-prev-disabled", l.media));
      links.forEach((l) => (l.media = "not all"));
      document.head.appendChild(link);
      return () => {
        link.remove();
        links.forEach((l) => {
          l.media = l.getAttribute("data-prev-disabled") ?? "";
          l.removeAttribute("data-prev-disabled");
        });
      };
    }
  }, [unread > 0]); // eslint-disable-line react-hooks/exhaustive-deps
}
