const WEEKDAYS = ["日", "月", "火", "水", "木", "金", "土"];

// デザインの fullD に合わせ、JST で「2026年10月19日（月）09:30」形式にする
export function formatFull(iso: string): string {
  const d = new Date(new Date(iso).getTime() + 9 * 3600000);
  const p2 = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}年${d.getUTCMonth() + 1}月${d.getUTCDate()}日（${WEEKDAYS[d.getUTCDay()]}）${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}`;
}
