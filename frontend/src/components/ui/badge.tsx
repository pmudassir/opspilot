import {
  PRIORITY_LABELS,
  type RequestPriority,
  type RequestStatus,
  STATUS_LABELS,
} from "@/lib/requests";

const STATUS_STYLES: Record<RequestStatus, string> = {
  open: "bg-sky-50 text-sky-800 ring-sky-200",
  assigned: "bg-amber-50 text-amber-800 ring-amber-200",
  in_progress: "bg-violet-50 text-violet-800 ring-violet-200",
  completed: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  cancelled: "bg-zinc-100 text-zinc-600 ring-zinc-200",
};

const PRIORITY_STYLES: Record<RequestPriority, string> = {
  urgent: "text-red-700 font-semibold",
  high: "text-orange-700 font-medium",
  normal: "text-zinc-700",
  low: "text-zinc-500",
};

export function StatusBadge({ status }: { status: RequestStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset ${STATUS_STYLES[status]}`}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

export function PriorityLabel({ priority }: { priority: RequestPriority }) {
  return <span className={`text-sm ${PRIORITY_STYLES[priority]}`}>{PRIORITY_LABELS[priority]}</span>;
}
