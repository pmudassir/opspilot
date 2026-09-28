import { describe, expect, it } from "vitest";

import { safeNextPath } from "./auth";

describe("safeNextPath (open-redirect guard)", () => {
  it.each([
    ["/orgs/1/requests", "/orgs/1/requests"],
    ["/orgs/1/requests?status=open", "/orgs/1/requests?status=open"],
  ])("keeps same-site path %s", (input, expected) => {
    expect(safeNextPath(input)).toBe(expected);
  });

  it.each([null, "", "https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)"])(
    "falls back to / for %s",
    (input) => {
      expect(safeNextPath(input)).toBe("/");
    },
  );
});
