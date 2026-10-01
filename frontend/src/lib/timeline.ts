import { type Comment, PRIORITY_LABELS, type RequestEvent, type RequestPriority } from "@/lib/requests";

export type TimelineItem =
  | { kind: "event"; at: string; event: RequestEvent }
  | { kind: "comment"; at: string; comment: Comment };

/** History events and comments as one chronological stream. */
export function buildTimeline(events: RequestEvent[], comments: Comment[]): TimelineItem[] {
  const items: TimelineItem[] = [
    ...events.map((event) => ({ kind: "event" as const, at: event.created_at, event })),
    ...comments.map((comment) => ({ kind: "comment" as const, at: comment.created_at, comment })),
  ];
  return items.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
}

function dataString(event: RequestEvent, key: string): string | null {
  const value = event.data[key];
  return typeof value === "string" ? value : null;
}

/** "Sam Okafor claimed this request", "Priya Raman assigned it to Sam Okafor", ... */
export function describeEvent(event: RequestEvent): string {
  const actor = event.actor.full_name;
  switch (event.event_type) {
    case "created":
      return `${actor} reported this request`;
    case "assigned": {
      if (event.data.claimed === true) return `${actor} claimed this request`;
      const assignee = dataString(event, "assignee_name") ?? "someone";
      const verb = dataString(event, "previous_assignee_membership_id") ? "reassigned" : "assigned";
      return `${actor} ${verb} it to ${assignee}`;
    }
    case "unassigned":
      return `${actor} unassigned it`;
    case "priority_changed": {
      const from = dataString(event, "from_priority");
      const to = dataString(event, "to_priority");
      if (!from || !to || !(from in PRIORITY_LABELS) || !(to in PRIORITY_LABELS)) return `${actor} changed the priority`;
      const label = (value: string) => PRIORITY_LABELS[value as RequestPriority].toLowerCase();
      return `${actor} changed the priority from ${label(from)} to ${label(to)}`;
    }
    case "status_changed":
      switch (event.to_status) {
        case "in_progress":
          return `${actor} started work`;
        case "completed":
          return `${actor} marked it complete`;
        case "cancelled":
          return `${actor} cancelled it`;
        default:
          return `${actor} changed the status`;
      }
    default:
      return `${actor} updated it`;
  }
}
