import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api, type Schemas, unwrap } from "@/lib/api/client";
import { PRIORITY_LABELS, requestKeys, STATUS_LABELS } from "@/lib/requests";

export type Proposal = Schemas["ProposalOut"];
export type ProposalStatus = Schemas["ProposalStatus"];

const proposalKey = (orgId: string, proposalId: string) => ["proposals", orgId, proposalId] as const;

function proposalPath(orgId: string, proposalId: string) {
  return { path: { org_id: orgId, proposal_id: proposalId } };
}

/** The proposal as the assistant returned it, kept fresh after approve/reject. */
export function useProposal(orgId: string, initial: Proposal) {
  return useQuery({
    queryKey: proposalKey(orgId, initial.id),
    queryFn: () =>
      unwrap(api.GET("/api/v1/orgs/{org_id}/ai/proposals/{proposal_id}", { params: proposalPath(orgId, initial.id) })),
    initialData: initial,
    staleTime: Infinity, // changes only through the mutations below, which update it
  });
}

export type Decision = "approve" | "reject";

/**
 * Approve or reject. Approval sends back the hash of what was shown, so the server
 * executes exactly the previewed change or nothing (409 if anything differs).
 */
export function useDecideProposal(orgId: string, proposal: Proposal) {
  const queryClient = useQueryClient();
  const params = proposalPath(orgId, proposal.id);
  return useMutation({
    mutationFn: (decision: Decision) =>
      decision === "approve"
        ? unwrap(
            api.POST("/api/v1/orgs/{org_id}/ai/proposals/{proposal_id}/approve", {
              params,
              body: { payload_hash: proposal.payload_hash },
            }),
          )
        : unwrap(api.POST("/api/v1/orgs/{org_id}/ai/proposals/{proposal_id}/reject", { params })),
    onSuccess: (updated) => {
      queryClient.setQueryData(proposalKey(orgId, proposal.id), updated);
      if (updated.status === "executed") void queryClient.invalidateQueries({ queryKey: requestKeys.all(orgId) });
    },
    onError: (error) => {
      // 409: expired or already decided (e.g. in another tab). Show its real state.
      if (error instanceof ApiError && error.status === 409) {
        void queryClient.invalidateQueries({ queryKey: proposalKey(orgId, proposal.id) });
      }
    },
  });
}

/** What happened to a decided proposal, in words. `null` while it's pending. */
export function proposalOutcome(proposal: Pick<Proposal, "status" | "failure_detail">): string | null {
  switch (proposal.status) {
    case "pending":
      return null;
    case "executed":
      return "Approved and applied.";
    case "failed":
      // All or nothing: one request that can't change means none did.
      return `Approved, but nothing was changed. ${proposal.failure_detail ?? "The change couldn't be applied."}`;
    case "rejected":
      return "Rejected. Nothing was changed.";
    case "expired":
      return "Expired before it was approved. Nothing was changed; ask again for a fresh proposal.";
    default: {
      const unhandled: never = proposal.status;
      throw new Error(`Unknown proposal status ${String(unhandled)}`);
    }
  }
}

/** One request's change, from the snapshot taken when it was proposed: "Normal → Urgent". */
export function previewChange(
  proposal: Pick<Proposal, "action" | "new_assignee_name" | "new_priority">,
  item: Schemas["ProposalItemOut"],
): string | null {
  switch (proposal.action) {
    case "assign":
      return `${item.assignee_name ?? "Unassigned"} → ${proposal.new_assignee_name ?? "?"}`;
    case "unassign":
      return `${item.assignee_name ?? "Unassigned"} → Unassigned`;
    case "cancel":
      return `${STATUS_LABELS[item.status]} → ${STATUS_LABELS.cancelled}`;
    case "change_priority":
      return `${PRIORITY_LABELS[item.priority]} → ${proposal.new_priority ? PRIORITY_LABELS[proposal.new_priority] : "?"}`;
    case "comment":
      return null; // the comment itself is shown once, above the request
    default: {
      const unhandled: never = proposal.action;
      throw new Error(`Unknown proposal action ${String(unhandled)}`);
    }
  }
}
