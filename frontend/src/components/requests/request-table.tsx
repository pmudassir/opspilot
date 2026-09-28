import { PriorityLabel, StatusBadge } from "@/components/ui/badge";
import { formatDateTime, relativeTime } from "@/lib/format";
import type { RequestItem } from "@/lib/requests";

const HEAD = "px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-zinc-500";
const CELL = "px-3 py-2.5 align-top text-sm";

export function RequestTable({ requests }: { requests: RequestItem[] }) {
  return (
    <div className="overflow-x-auto rounded-md border border-zinc-200 bg-white">
      <table className="w-full min-w-[760px] border-collapse">
        <thead className="border-b border-zinc-200 bg-zinc-50">
          <tr>
            <th scope="col" className={HEAD}>Request</th>
            <th scope="col" className={HEAD}>Status</th>
            <th scope="col" className={HEAD}>Priority</th>
            <th scope="col" className={HEAD}>Department</th>
            <th scope="col" className={HEAD}>Assignee</th>
            <th scope="col" className={HEAD}>Reported</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100">
          {requests.map((request) => (
            <tr key={request.id} className="hover:bg-zinc-50">
              <td className={`${CELL} max-w-md`}>
                <p className="font-medium text-zinc-900">{request.title}</p>
                <p className="text-xs text-zinc-500">by {request.requester.full_name}</p>
              </td>
              <td className={CELL}>
                <StatusBadge status={request.status} />
              </td>
              <td className={CELL}>
                <PriorityLabel priority={request.priority} />
              </td>
              <td className={`${CELL} text-zinc-700`}>{request.department.name}</td>
              <td className={`${CELL} text-zinc-700`}>
                {request.assignee?.full_name ?? <span className="text-zinc-400">Unassigned</span>}
              </td>
              <td className={`${CELL} whitespace-nowrap text-zinc-600`}>
                <time dateTime={request.created_at} title={formatDateTime(request.created_at)}>
                  {relativeTime(request.created_at)}
                </time>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
