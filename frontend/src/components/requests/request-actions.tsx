"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ErrorAlert } from "@/components/ui/feedback";
import { useDepartmentMembers } from "@/lib/departments";
import {
  ACTION_LABELS,
  PRIORITY_LABELS,
  REQUEST_PRIORITIES,
  type RequestAction,
  type RequestItem,
  type RequestPriority,
  useRequestAction,
} from "@/lib/requests";

// Simple one-click actions, in the order people usually need them.
const QUICK_ACTIONS: { action: RequestAction; variant: "primary" | "secondary" }[] = [
  { action: "claim", variant: "primary" },
  { action: "start", variant: "primary" },
  { action: "complete", variant: "primary" },
  { action: "unassign", variant: "secondary" },
];

/** Renders only what the API says the current user may do (`allowed_actions`). */
export function RequestActions({ orgId, request }: { orgId: string; request: RequestItem }) {
  const perform = useRequestAction(orgId, request.id);
  const allowed = new Set(request.allowed_actions);
  const quick = QUICK_ACTIONS.filter(({ action }) => allowed.has(action));

  if (allowed.size === 0) {
    return <p className="text-sm text-zinc-500">No actions available to you on this request.</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      {perform.error && <ErrorAlert error={perform.error} />}
      {quick.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {quick.map(({ action, variant }) => (
            <Button
              key={action}
              variant={variant}
              size="sm"
              pending={perform.isPending && perform.variables?.action === action}
              disabled={perform.isPending}
              onClick={() => perform.mutate({ action })}
            >
              {ACTION_LABELS[action]}
            </Button>
          ))}
        </div>
      )}
      {allowed.has("assign") && (
        <AssignPicker orgId={orgId} request={request} perform={perform} />
      )}
      {allowed.has("change_priority") && <PriorityPicker request={request} perform={perform} />}
      {allowed.has("cancel") && <CancelButton perform={perform} />}
    </div>
  );
}

type Perform = ReturnType<typeof useRequestAction>;

function AssignPicker({
  orgId,
  request,
  perform,
}: {
  orgId: string;
  request: RequestItem;
  perform: Perform;
}) {
  const members = useDepartmentMembers(orgId, request.department.id, true);
  const [assigneeId, setAssigneeId] = useState("");
  const eligible = (members.data ?? []).filter(
    (m) =>
      m.status === "active" &&
      m.role !== "member" &&
      m.membership_id !== request.assignee?.membership_id,
  );

  if (members.isPending) return <p className="text-sm text-zinc-500">Loading staff…</p>;
  if (members.isError) return <ErrorAlert error={members.error} />;
  if (eligible.length === 0) {
    return (
      <p className="text-sm text-zinc-500">
        No other staff in {request.department.name} to assign.
      </p>
    );
  }

  return (
    <form
      className="flex gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (assigneeId) perform.mutate({ action: "assign", assigneeMembershipId: assigneeId });
      }}
    >
      <select
        aria-label={request.assignee ? "Reassign to" : "Assign to"}
        value={assigneeId}
        onChange={(event) => setAssigneeId(event.target.value)}
        className="h-8 min-w-0 flex-1 rounded-md border border-zinc-300 bg-white px-2 text-sm"
      >
        <option value="">{request.assignee ? "Reassign to…" : "Assign to…"}</option>
        {eligible.map((m) => (
          <option key={m.membership_id} value={m.membership_id}>
            {m.full_name} ({m.role})
          </option>
        ))}
      </select>
      <Button
        type="submit"
        variant="secondary"
        size="sm"
        disabled={!assigneeId || perform.isPending}
        pending={perform.isPending && perform.variables?.action === "assign"}
      >
        {ACTION_LABELS.assign}
      </Button>
    </form>
  );
}

function PriorityPicker({ request, perform }: { request: RequestItem; perform: Perform }) {
  const [priority, setPriority] = useState<RequestPriority>(request.priority);
  return (
    <form
      className="flex gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        perform.mutate({ action: "change_priority", priority });
      }}
    >
      <select
        aria-label="Priority"
        value={priority}
        onChange={(event) => setPriority(event.target.value as RequestPriority)}
        className="h-8 min-w-0 flex-1 rounded-md border border-zinc-300 bg-white px-2 text-sm"
      >
        {REQUEST_PRIORITIES.map((option) => (
          <option key={option} value={option}>
            {PRIORITY_LABELS[option]}
          </option>
        ))}
      </select>
      <Button
        type="submit"
        variant="secondary"
        size="sm"
        disabled={priority === request.priority || perform.isPending}
        pending={perform.isPending && perform.variables?.action === "change_priority"}
      >
        {ACTION_LABELS.change_priority}
      </Button>
    </form>
  );
}

/** Two-step inline confirmation: cancelling is terminal. */
function CancelButton({ perform }: { perform: Perform }) {
  const [confirming, setConfirming] = useState(false);
  if (!confirming) {
    return (
      <div>
        <Button variant="danger" size="sm" disabled={perform.isPending} onClick={() => setConfirming(true)}>
          {ACTION_LABELS.cancel}
        </Button>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-900">
      <span>Cancel this request? This can&apos;t be undone.</span>
      <Button
        variant="danger"
        size="sm"
        pending={perform.isPending && perform.variables?.action === "cancel"}
        onClick={() => perform.mutate({ action: "cancel" }, { onSettled: () => setConfirming(false) })}
      >
        Yes, cancel it
      </Button>
      <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
        Keep it
      </Button>
    </div>
  );
}
