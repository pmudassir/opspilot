"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { ErrorAlert, PageLoading } from "@/components/ui/feedback";
import { NoAccess } from "@/components/ui/no-access";
import {
  backlog,
  type FlowMetrics,
  formatHours,
  parsePeriod,
  PERIOD_OPTIONS,
  useMetrics,
} from "@/lib/metrics";
import { useCurrentOrg } from "@/lib/org";

export default function MetricsPage() {
  return (
    <Suspense fallback={<PageLoading />}>
      <MetricsView />
    </Suspense>
  );
}

function MetricsView() {
  const { organizationId, can } = useCurrentOrg();
  const router = useRouter();
  const pathname = usePathname();
  const days = parsePeriod(useSearchParams().get("days"));
  const allowed = can("metrics:read");
  const metrics = useMetrics(organizationId, days, allowed);

  if (!allowed) return <NoAccess />;

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold">Metrics</h1>
          <p className="text-sm text-zinc-600">Backlog is current; everything else covers the selected period.</p>
        </div>
        <label className="flex items-center gap-2 text-sm text-zinc-700">
          Period
          <select
            value={days}
            onChange={(event) => router.push(`${pathname}?days=${event.target.value}`, { scroll: false })}
            className="h-8 rounded-md border border-zinc-300 bg-white px-2 text-sm"
          >
            {PERIOD_OPTIONS.map((option) => (
              <option key={option} value={option}>
                Last {option} days
              </option>
            ))}
          </select>
        </label>
      </div>

      {metrics.isPending ? (
        <PageLoading label="Calculating…" />
      ) : metrics.isError ? (
        <ErrorAlert error={metrics.error} />
      ) : (
        <>
          <KpiRow totals={metrics.data.totals} />
          {metrics.data.departments.length === 0 ? (
            <p className="text-sm text-zinc-600">No departments yet.</p>
          ) : (
            <DepartmentTable rows={metrics.data.departments} />
          )}
          <p className="text-xs text-zinc-500">
            Time to assign: creation → first assignment, for requests created in the period. Time to complete:
            creation → completion, for requests completed in the period. &ldquo;Typical&rdquo; is the median; the
            slowest 10% take longer than p90.
          </p>
        </>
      )}
    </section>
  );
}

function KpiRow({ totals }: { totals: FlowMetrics }) {
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      <Tile
        label="Backlog"
        value={String(backlog(totals))}
        detail={`${totals.open} open · ${totals.assigned} assigned · ${totals.in_progress} in progress`}
      />
      <Tile label="Created" value={String(totals.created_in_period)} />
      <Tile label="Completed" value={String(totals.completed_in_period)} detail={`${totals.cancelled_in_period} cancelled`} />
      <Tile
        label="Typical time to assign"
        value={formatHours(totals.median_hours_to_assign)}
        detail={`p90 ${formatHours(totals.p90_hours_to_assign)}`}
      />
      <Tile
        label="Typical time to complete"
        value={formatHours(totals.median_hours_to_complete)}
        detail={`p90 ${formatHours(totals.p90_hours_to_complete)}`}
      />
    </dl>
  );
}

function Tile({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="rounded-md border border-zinc-200 bg-white px-4 py-3">
      <dt className="text-sm text-zinc-600">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold text-zinc-900">{value}</dd>
      {detail && <dd className="mt-0.5 text-xs text-zinc-500">{detail}</dd>}
    </div>
  );
}

const NUM = "px-3 py-2.5 text-right tabular-nums";
const HEAD = "px-3 py-2 text-xs font-medium tracking-wide text-zinc-500 uppercase";

function DepartmentTable({ rows }: { rows: (FlowMetrics & { department_id: string; department_name: string })[] }) {
  return (
    <div className="overflow-x-auto rounded-md border border-zinc-200 bg-white">
      <table className="w-full min-w-[760px] border-collapse text-sm">
        <caption className="sr-only">Metrics by department</caption>
        <thead className="border-b border-zinc-200 bg-zinc-50">
          <tr>
            <th scope="col" className={`${HEAD} text-left`}>Department</th>
            <th scope="col" className={`${HEAD} text-right`}>Backlog</th>
            <th scope="col" className={`${HEAD} text-right`}>Created</th>
            <th scope="col" className={`${HEAD} text-right`}>Completed</th>
            <th scope="col" className={`${HEAD} text-right`}>Cancelled</th>
            <th scope="col" className={`${HEAD} text-right`}>Time to assign<br /><span className="normal-case">typical / p90</span></th>
            <th scope="col" className={`${HEAD} text-right`}>Time to complete<br /><span className="normal-case">typical / p90</span></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100">
          {rows.map((row) => (
            <tr key={row.department_id}>
              <th scope="row" className="px-3 py-2.5 text-left font-medium text-zinc-900">{row.department_name}</th>
              <td className={NUM} title={`${row.open} open · ${row.assigned} assigned · ${row.in_progress} in progress`}>
                {backlog(row)}
              </td>
              <td className={NUM}>{row.created_in_period}</td>
              <td className={NUM}>{row.completed_in_period}</td>
              <td className={NUM}>{row.cancelled_in_period}</td>
              <td className={NUM}>
                {formatHours(row.median_hours_to_assign)} <span className="text-zinc-400">/ {formatHours(row.p90_hours_to_assign)}</span>
              </td>
              <td className={NUM}>
                {formatHours(row.median_hours_to_complete)} <span className="text-zinc-400">/ {formatHours(row.p90_hours_to_complete)}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
