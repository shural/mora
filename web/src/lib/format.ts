/** Formatting helpers — all user-facing strings here are Chinese. */

export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const total = Math.floor(seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${minutes}:${rest.toString().padStart(2, "0")}`;
}

/** "3 天后" / "10 分钟后" / "现在" — used after grading a card. */
export function formatDue(iso: string): string {
  const due = new Date(iso).getTime();
  if (Number.isNaN(due)) return "稍后";
  const deltaMs = due - Date.now();
  if (deltaMs <= 60_000) return "现在";
  const minutes = Math.round(deltaMs / 60_000);
  if (minutes < 60) return `${minutes} 分钟后`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} 小时后`;
  const days = Math.round(hours / 24);
  if (days === 1) return "明天";
  return `${days} 天后`;
}

export function formatScore(score: number): string {
  return `${Math.max(0, Math.min(100, Math.round(score)))}`;
}

export function pad2(value: number): string {
  return value.toString().padStart(2, "0");
}

export function formatCount(count: number, unit: string): string {
  return `${count} ${unit}`;
}
