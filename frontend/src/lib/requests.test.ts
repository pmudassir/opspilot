import { describe, expect, it } from "vitest";

import { filtersToSearchParams, hasFilters, NO_FILTERS, parseFilters } from "./requests";

const DEPT = "0b6f0c9e-6d0e-4d6a-9d3b-2f1c1f5e8a11";

describe("parseFilters", () => {
  it("reads known statuses, department and priority", () => {
    const params = new URLSearchParams(
      `status=assigned&status=open&department_id=${DEPT}&priority=urgent`,
    );

    expect(parseFilters(params)).toEqual({
      statuses: ["open", "assigned"], // canonical order, not URL order
      departmentId: DEPT,
      priority: "urgent",
    });
  });

  it("drops unknown or malformed values instead of trusting the URL", () => {
    const params = new URLSearchParams(
      "status=bogus&status=open&status=open&department_id=not-a-uuid&priority=whenever",
    );

    expect(parseFilters(params)).toEqual({
      statuses: ["open"],
      departmentId: null,
      priority: null,
    });
  });

  it("round-trips through the URL", () => {
    const filters = { statuses: ["open" as const], departmentId: DEPT, priority: "high" as const };

    expect(parseFilters(filtersToSearchParams(filters))).toEqual(filters);
  });
});

describe("hasFilters", () => {
  it("is false only when nothing is filtered", () => {
    expect(hasFilters(NO_FILTERS)).toBe(false);
    expect(hasFilters({ ...NO_FILTERS, priority: "low" })).toBe(true);
  });
});
