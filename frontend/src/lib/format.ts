const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;

const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
const dateTime = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" });
const shortDate = new Intl.DateTimeFormat("en", { month: "short", day: "numeric" });

/** "just now", "5 minutes ago", "yesterday"; older than a week → "Sep 3". */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000);
  const elapsed = Math.abs(seconds);
  if (elapsed < MINUTE) return "just now";
  if (elapsed < HOUR) return relative.format(Math.round(seconds / MINUTE), "minute");
  if (elapsed < DAY) return relative.format(Math.round(seconds / HOUR), "hour");
  if (elapsed < WEEK) return relative.format(Math.round(seconds / DAY), "day");
  return shortDate.format(new Date(iso));
}

export function formatDateTime(iso: string): string {
  return dateTime.format(new Date(iso));
}
