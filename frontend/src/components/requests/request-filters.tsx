"use client";

import type { Department } from "@/lib/departments";
import {
  hasFilters,
  NO_FILTERS,
  PRIORITY_LABELS,
  REQUEST_PRIORITIES,
  REQUEST_STATUSES,
  type RequestFilters,
  type RequestPriority,
  STATUS_LABELS,
} from "@/lib/requests";

type Props = {
  filters: RequestFilters;
  departments: Department[];
  onChange: (filters: RequestFilters) => void;
};

const SELECT =
  "h-8 rounded-md border border-zinc-300 bg-white px-2 text-sm text-zinc-800 focus:border-teal-700 focus:outline-none";

export function RequestFiltersBar({ filters, departments, onChange }: Props) {
  function toggleStatus(status: (typeof REQUEST_STATUSES)[number]) {
    const statuses = filters.statuses.includes(status)
      ? filters.statuses.filter((s) => s !== status)
      : REQUEST_STATUSES.filter((s) => s === status || filters.statuses.includes(s));
    onChange({ ...filters, statuses });
  }

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <div role="group" aria-label="Status" className="flex flex-wrap gap-1">
        {REQUEST_STATUSES.map((status) => {
          const active = filters.statuses.includes(status);
          return (
            <button
              key={status}
              type="button"
              aria-pressed={active}
              onClick={() => toggleStatus(status)}
              className={`h-8 rounded-md border px-2.5 text-sm transition-colors ${active ? "border-teal-700 bg-teal-700 text-white" : "border-zinc-300 bg-white text-zinc-700 hover:bg-zinc-100"}`}
            >
              {STATUS_LABELS[status]}
            </button>
          );
        })}
      </div>
      <select
        aria-label="Department"
        className={SELECT}
        value={filters.departmentId ?? ""}
        onChange={(event) => onChange({ ...filters, departmentId: event.target.value || null })}
      >
        <option value="">All departments</option>
        {departments.map((department) => (
          <option key={department.id} value={department.id}>
            {department.name}
          </option>
        ))}
      </select>
      <select
        aria-label="Priority"
        className={SELECT}
        value={filters.priority ?? ""}
        onChange={(event) =>
          onChange({ ...filters, priority: (event.target.value || null) as RequestPriority | null })
        }
      >
        <option value="">Any priority</option>
        {REQUEST_PRIORITIES.map((priority) => (
          <option key={priority} value={priority}>
            {PRIORITY_LABELS[priority]}
          </option>
        ))}
      </select>
      {hasFilters(filters) && (
        <button
          type="button"
          onClick={() => onChange(NO_FILTERS)}
          className="text-sm text-zinc-600 underline-offset-2 hover:text-zinc-900 hover:underline"
        >
          Clear filters
        </button>
      )}
    </div>
  );
}
