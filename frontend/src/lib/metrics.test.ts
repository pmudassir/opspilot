import { describe, expect, it } from "vitest";

import { formatHours, parsePeriod } from "./metrics";

describe("formatHours", () => {
  it.each([
    [null, "—"],
    [0, "< 1 min"],
    [0.005, "< 1 min"],
    [0.75, "45 min"],
    [5.2, "5.2 h"],
    [47.9, "47.9 h"],
    [76, "3.2 d"],
  ])("%s → %s", (hours, expected) => {
    expect(formatHours(hours)).toBe(expected);
  });
});

describe("parsePeriod", () => {
  it.each([
    ["7", 7],
    ["90", 90],
    [null, 30],
    ["365", 30],
    ["soon", 30],
  ])("%s → %d", (raw, expected) => {
    expect(parsePeriod(raw)).toBe(expected);
  });
});
