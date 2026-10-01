import { describe, expect, it } from "vitest";

import type { Comment, RequestEvent } from "@/lib/requests";

import { buildTimeline, describeEvent } from "./timeline";

const actor = { membership_id: "m1", full_name: "Sam Okafor" };

function event(overrides: Partial<RequestEvent>): RequestEvent {
  return {
    id: "e",
    event_type: "created",
    from_status: null,
    to_status: "open",
    actor,
    data: {},
    created_at: "2026-09-28T10:00:00+00:00",
    ...overrides,
  };
}

describe("describeEvent", () => {
  it.each([
    [event({}), "Sam Okafor reported this request"],
    [
      event({ event_type: "priority_changed", to_status: null, data: { from_priority: "normal", to_priority: "urgent" } }),
      "Sam Okafor changed the priority from normal to urgent",
    ],
    [event({ event_type: "priority_changed", to_status: null, data: {} }), "Sam Okafor changed the priority"],
    [event({ event_type: "assigned", data: { claimed: true } }), "Sam Okafor claimed this request"],
    [event({ event_type: "assigned", data: { assignee_name: "Ana" } }), "Sam Okafor assigned it to Ana"],
    [
      event({ event_type: "assigned", data: { assignee_name: "Ana", previous_assignee_membership_id: "m9" } }),
      "Sam Okafor reassigned it to Ana",
    ],
    [event({ event_type: "status_changed", to_status: "in_progress" }), "Sam Okafor started work"],
    [event({ event_type: "status_changed", to_status: "completed" }), "Sam Okafor marked it complete"],
    [event({ event_type: "status_changed", to_status: "cancelled" }), "Sam Okafor cancelled it"],
  ])("%#", (input, expected) => {
    expect(describeEvent(input)).toBe(expected);
  });
});

describe("buildTimeline", () => {
  it("interleaves events and comments chronologically", () => {
    const comment: Comment = { id: "c", body: "On my way", author: actor, created_at: "2026-09-28T10:05:00+00:00" };
    const created = event({ created_at: "2026-09-28T10:00:00+00:00" });
    const started = event({ event_type: "status_changed", to_status: "in_progress", created_at: "2026-09-28T10:10:00+00:00" });

    expect(buildTimeline([started, created], [comment]).map((item) => item.kind)).toEqual([
      "event",
      "comment",
      "event",
    ]);
  });
});
