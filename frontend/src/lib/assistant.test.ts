import { describe, expect, it } from "vitest";

import { describeToolUse, exampleQuestions, segmentAnswer } from "@/lib/assistant";

const printer = { ref: "R1", request_id: "id-1", title: "Printer jammed" };

describe("segmentAnswer", () => {
  it("links only refs the server returned", () => {
    expect(segmentAnswer("R1 (Printer jammed) is open; R7 is not mine.", [printer])).toEqual([
      { reference: printer },
      { text: " (Printer jammed) is open; R7 is not mine." },
    ]);
  });

  it("leaves words that merely contain R and digits alone", () => {
    expect(segmentAnswer("Room R12B and XR1 are fine, see R1.", [printer])).toEqual([
      { text: "Room R12B and XR1 are fine, see " },
      { reference: printer },
      { text: "." },
    ]);
  });

  it("returns plain text when there are no references", () => {
    expect(segmentAnswer("Nothing is open.", [])).toEqual([{ text: "Nothing is open." }]);
  });
});

describe("describeToolUse", () => {
  it("describes successful and failed lookups", () => {
    expect(describeToolUse({ tool: "search_requests", status: "ok" })).toBe("searched requests");
    expect(describeToolUse({ tool: "get_request", status: "repeated" })).toBe("opened a request");
    expect(describeToolUse({ tool: "get_request", status: "not_found" })).toBe("opened a request (not found)");
    expect(describeToolUse({ tool: "drop_tables", status: "unknown_tool" })).toBe("used an unknown tool (unknown tool)");
  });
});

describe("exampleQuestions", () => {
  it("fits what the role can see", () => {
    const member = exampleQuestions(() => false);
    const manager = exampleQuestions(() => true);
    expect(member.every((q) => q.includes("my"))).toBe(true);
    expect(manager).toContain("Which department has the biggest backlog this week?");
  });
});
