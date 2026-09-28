"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import type { ReactNode } from "react";

import { CommentForm } from "@/components/requests/comment-form";
import { RequestActions } from "@/components/requests/request-actions";
import { Timeline } from "@/components/requests/timeline";
import { PriorityLabel, StatusBadge } from "@/components/ui/badge";
import { ErrorAlert, PageLoading } from "@/components/ui/feedback";
import { ApiError } from "@/lib/api/client";
import { formatDateTime } from "@/lib/format";
import { useCurrentOrg } from "@/lib/org";
import { type RequestItem, useComments, useRequest, useRequestEvents } from "@/lib/requests";

export default function RequestDetailPage() {
  const { organizationId } = useCurrentOrg();
  const { requestId } = useParams<{ requestId: string }>();
  const request = useRequest(organizationId, requestId);
  const listHref = `/orgs/${organizationId}/requests`;

  if (request.isPending) return <PageLoading />;
  if (request.isError) {
    const notFound = request.error instanceof ApiError && request.error.status === 404;
    return (
      <div className="flex max-w-xl flex-col gap-3">
        {notFound ? (
          <p className="text-sm text-zinc-600">This request doesn&apos;t exist, or you don&apos;t have access to it.</p>
        ) : (
          <ErrorAlert error={request.error} />
        )}
        <Link href={listHref} className="text-sm font-medium text-teal-800 hover:underline">
          Back to requests
        </Link>
      </div>
    );
  }

  const data = request.data;
  return (
    <article className="flex flex-col gap-6">
      <div>
        <Link href={listHref} className="text-sm text-zinc-600 hover:text-zinc-900">
          ← Requests
        </Link>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold text-zinc-900">{data.title}</h1>
          <StatusBadge status={data.status} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex flex-col gap-6">
          <section aria-label="Description">
            {data.description ? (
              <p className="text-sm whitespace-pre-wrap text-zinc-800">{data.description}</p>
            ) : (
              <p className="text-sm text-zinc-500">No details were given.</p>
            )}
          </section>
          <section aria-labelledby="activity" className="flex flex-col gap-4">
            <h2 id="activity" className="text-sm font-semibold text-zinc-900">
              Activity
            </h2>
            <Activity orgId={organizationId} requestId={requestId} />
            <CommentForm orgId={organizationId} requestId={requestId} />
          </section>
        </div>

        <aside className="flex flex-col gap-6">
          <section aria-labelledby="actions" className="flex flex-col gap-3">
            <h2 id="actions" className="text-sm font-semibold text-zinc-900">
              Actions
            </h2>
            <RequestActions orgId={organizationId} request={data} />
          </section>
          <Details request={data} />
        </aside>
      </div>
    </article>
  );
}

function Activity({ orgId, requestId }: { orgId: string; requestId: string }) {
  const events = useRequestEvents(orgId, requestId);
  const comments = useComments(orgId, requestId);
  if (events.isPending || comments.isPending) {
    return <p className="text-sm text-zinc-500">Loading activity…</p>;
  }
  if (events.isError) return <ErrorAlert error={events.error} />;
  if (comments.isError) return <ErrorAlert error={comments.error} />;
  return <Timeline events={events.data} comments={comments.data} />;
}

function Details({ request }: { request: RequestItem }) {
  const timestamps: [string, string | null | undefined][] = [
    ["Reported", request.created_at],
    ["Assigned", request.assigned_at],
    ["Started", request.started_at],
    ["Completed", request.completed_at],
    ["Cancelled", request.cancelled_at],
  ];
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 rounded-md border border-zinc-200 bg-white p-4 text-sm">
      <Row label="Priority">
        <PriorityLabel priority={request.priority} />
      </Row>
      <Row label="Department">{request.department.name}</Row>
      <Row label="Requester">{request.requester.full_name}</Row>
      <Row label="Assignee">
        {request.assignee?.full_name ?? <span className="text-zinc-400">Unassigned</span>}
      </Row>
      {timestamps
        .filter((entry): entry is [string, string] => Boolean(entry[1]))
        .map(([label, iso]) => (
          <Row key={label} label={label}>
            <time dateTime={iso}>{formatDateTime(iso)}</time>
          </Row>
        ))}
    </dl>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-zinc-500">{label}</dt>
      <dd className="text-zinc-900">{children}</dd>
    </>
  );
}
