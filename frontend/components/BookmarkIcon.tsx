// マーク（ブックマーク）のアイコン。ON は currentColor で塗りつぶす
export function BookmarkIcon({
  filled,
  size = 16,
  strokeWidth = 1.9,
}: {
  filled: boolean;
  size?: number;
  strokeWidth?: number;
}) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinejoin="round"
    >
      <path d="M6.5 3.5h11a1 1 0 0 1 1 1v16l-6.5-4.6-6.5 4.6v-16a1 1 0 0 1 1-1z" />
    </svg>
  );
}
