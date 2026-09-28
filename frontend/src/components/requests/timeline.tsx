import { formatDateTime, relativeTime } from "@/lib/format";
import { buildTimeline, describeEvent } from "@/lib/timeline";
import type { Comment, RequestEvent } from "@/lib/requests";

export function Timeline({ events, comments }: { events: RequestEvent[]; comments: Comment[] }) {
  const items = buildTimeline(events, comments);
  return (
    <ol className="flex flex-col gap-3">
      {items.map((item) =>
        item.kind === "event" ? (
          <li key={`e-${item.event.id}`} className="flex items-baseline gap-3 pl-1 text-sm text-zinc-600">
            <span aria-hidden className="size-1.5 shrink-0 translate-y-[-1px] rounded-full bg-zinc-400" />
            <span>{describeEvent(item.event)}</span>
            <Time iso={item.at} />
          </li>
        ) : (
          <li key={`c-${item.comment.id}`} className="rounded-md border border-zinc-200 bg-white p-3">
            <div className="flex items-baseline gap-2 text-sm">
              <span className="font-medium text-zinc-900">{item.comment.author.full_name}</span>
              <Time iso={item.at} />
            </div>
            <p className="mt-1 text-sm whitespace-pre-wrap text-zinc-800">{item.comment.body}</p>
          </li>
        ),
      )}
    </ol>
  );
}

function Time({ iso }: { iso: string }) {
  return (
    <time dateTime={iso} title={formatDateTime(iso)} className="text-xs text-zinc-500">
      {relativeTime(iso)}
    </time>
  );
}
