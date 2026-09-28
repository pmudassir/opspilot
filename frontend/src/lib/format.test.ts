import { describe, expect, it } from "vitest";

import { relativeTime } from "./format";

const NOW = Date.parse("2026-09-28T12:00:00Z");
const ago = (seconds: number) => new Date(NOW - seconds * 1000).toISOString();

describe("relativeTime", () => {
  it.each([
    [10, "just now"],
    [5 * 60, "5 minutes ago"],
    [3 * 3600, "3 hours ago"],
    [26 * 3600, "yesterday"],
    [10 * 86400, "Sep 18"],
  ])("%is ago → %s", (seconds, expected) => {
    expect(relativeTime(ago(seconds), NOW)).toBe(expected);
  });
});
