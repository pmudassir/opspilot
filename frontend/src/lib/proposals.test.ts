import { describe, expect, it } from "vitest";

import { previewChange, proposalOutcome } from "@/lib/proposals";

const item = {
  request_id: "id-1",
  title: "Printer jammed",
  status: "assigned" as const,
  priority: "normal" as const,
  assignee_name: "Sam Agent",
};
const params = { new_assignee_name: null, new_priority: null };

describe("previewChange", () => {
  it("shows each request's before and after from the server's snapshot", () => {
    expect(previewChange({ ...params, action: "change_priority", new_priority: "urgent" }, item)).toBe("Normal → Urgent");
    expect(previewChange({ ...params, action: "assign", new_assignee_name: "Ana" }, { ...item, assignee_name: null })).toBe(
      "Unassigned → Ana",
    );
    expect(previewChange({ ...params, action: "unassign" }, item)).toBe("Sam Agent → Unassigned");
    expect(previewChange({ ...params, action: "cancel" }, item)).toBe("Assigned → Cancelled");
  });

  it("has no per-request line for a comment (the comment is shown once)", () => {
    expect(previewChange({ ...params, action: "comment" }, item)).toBeNull();
  });
});

describe("proposalOutcome", () => {
  it("is null while waiting for a decision", () => {
    expect(proposalOutcome({ status: "pending", failure_detail: null })).toBeNull();
  });

  it("says plainly that a failed approval changed nothing, with the server's reason", () => {
    expect(
      proposalOutcome({ status: "failed", failure_detail: "The request changed since it was reviewed. Review it again." }),
    ).toBe("Approved, but nothing was changed. The request changed since it was reviewed. Review it again.");
  });

  it.each([
    ["executed", "Approved and applied."],
    ["rejected", "Rejected. Nothing was changed."],
    ["expired", "Expired before it was approved. Nothing was changed; ask again for a fresh proposal."],
  ] as const)("describes %s", (status, text) => {
    expect(proposalOutcome({ status, failure_detail: null })).toBe(text);
  });
});
