export const THEME_STORAGE_KEY = "dt-theme";

export type Theme = "light" | "dark";

// FOUC防止: hydration前に <html data-theme> を確定させるインラインスクリプト（layout.tsx で埋め込む）
export const themeInitScript = `(function(){try{var t=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});if(t!=="light"&&t!=="dark"){t=window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}document.documentElement.dataset.theme=t}catch(e){document.documentElement.dataset.theme="light"}})();`;
