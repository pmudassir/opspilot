"use client";

import Link from "next/link";

import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorAlert } from "@/components/ui/feedback";
import { formatTime } from "@/lib/format";
import {
  type Proposal,
  type ProposalStatus,
  previewChange,
  proposalOutcome,
  useDecideProposal,
  useProposal,
} from "@/lib/proposals";

const OUTCOME_STYLES: Record<Exclude<ProposalStatus, "pending">, string> = {
  executed: "border-emerald-200 bg-emerald-50 text-emerald-900",
  failed: "border-red-200 bg-red-50 text-red-800",
  rejected: "border-zinc-200 bg-zinc-50 text-zinc-700",
  expired: "border-zinc-200 bg-zinc-50 text-zinc-700",
};

/**
 * A change the assistant proposed. The preview is the server's snapshot, not the
 * model's words; approving sends back that snapshot's hash, so what runs is what was shown.
 */
export function ProposalCard({ orgId, initial }: { orgId: string; initial: Proposal }) {
  const proposal = useProposal(orgId, initial).data;
  const decide = useDecideProposal(orgId, proposal);
  const pending = proposal.status === "pending";
  const outcome = proposalOutcome(proposal);

  return (
    <section
      aria-label="Proposed change"
      className={`flex flex-col gap-3 rounded-md border p-4 ${pending ? "border-amber-300 bg-amber-50/40" : "border-zinc-200 bg-white"}`}
    >
      <div>
        <p className={`text-xs font-medium ${pending ? "text-amber-800" : "text-zinc-500"}`}>
          {pending ? "Proposed change · nothing happens until you approve" : "Proposed change"}
        </p>
        <h2 className="text-sm font-semibold text-zinc-900">{proposal.summary}</h2>
      </div>

      {proposal.comment_body && (
        <blockquote className="border-l-2 border-zinc-300 pl-3 text-sm whitespace-pre-wrap text-zinc-800">
          {proposal.comment_body}
        </blockquote>
      )}

      <ul aria-label="Requests in this proposal" className="flex flex-col divide-y divide-zinc-100 text-sm">
        {proposal.items.map((item) => {
          const change = previewChange(proposal, item);
          return (
            <li key={item.request_id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-1.5">
              <span className="flex min-w-0 items-center gap-2">
                <StatusBadge status={item.status} />
                <Link
                  href={`/orgs/${orgId}/requests/${item.request_id}`}
                  title={item.title}
                  className="truncate font-medium text-teal-800 hover:underline"
                >
                  {item.title}
                </Link>
              </span>
              {change && <span className="text-zinc-600">{change}</span>}
            </li>
          );
        })}
      </ul>

      {decide.error && <ErrorAlert error={decide.error} />}

      {proposal.status === "pending" ? (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-amber-200 pt-3">
          <p className="text-xs text-zinc-600">
            As of {formatTime(proposal.created_at)}. Expires at {formatTime(proposal.expires_at)}. If any request
            changes before you approve, nothing is applied.
          </p>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              pending={decide.isPending && decide.variables === "reject"}
              disabled={decide.isPending}
              onClick={() => decide.mutate("reject")}
            >
              Reject
            </Button>
            <Button
              variant={proposal.action === "cancel" ? "danger" : "primary"}
              size="sm"
              pending={decide.isPending && decide.variables === "approve"}
              disabled={decide.isPending}
              onClick={() => decide.mutate("approve")}
            >
              Approve
            </Button>
          </div>
        </div>
      ) : (
        <p
          role="status"
          className={`rounded-md border px-3 py-2 text-sm ${OUTCOME_STYLES[proposal.status]}`}
        >
          {outcome}
        </p>
      )}
    </section>
  );
}
