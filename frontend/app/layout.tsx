import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans_JP } from "next/font/google";
import { AppShell } from "@/components/AppShell";
import { themeInitScript } from "@/components/theme";
import "./globals.css";

const plexSans = IBM_Plex_Sans_JP({
  variable: "--font-plex-sans",
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  weight: ["400", "500"],
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Deep Tracker",
  description: "RSSリーダー + AI要約",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // data-theme は下のインラインスクリプトが hydration 前に設定する
    <html
      lang="ja"
      className={`${plexSans.variable} ${plexMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
