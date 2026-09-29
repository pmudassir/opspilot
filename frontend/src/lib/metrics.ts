import { useQuery } from "@tanstack/react-query";

import { api, type Schemas, unwrap } from "@/lib/api/client";

export type Metrics = Schemas["MetricsOut"];
export type FlowMetrics = Schemas["FlowMetricsOut"];

export const PERIOD_OPTIONS = [7, 30, 90] as const;
export type PeriodDays = (typeof PERIOD_OPTIONS)[number];
export const DEFAULT_PERIOD: PeriodDays = 30;

/** The URL is user input: only the offered periods are accepted. */
export function parsePeriod(raw: string | null): PeriodDays {
  const days = Number(raw);
  return (PERIOD_OPTIONS as readonly number[]).includes(days) ? (days as PeriodDays) : DEFAULT_PERIOD;
}

export function backlog(metrics: FlowMetrics): number {
  return metrics.open + metrics.assigned + metrics.in_progress;
}

const MINUTE_IN_HOURS = 1 / 60;

/** 0.005 → "< 1 min", 0.75 → "45 min", 5.2 → "5.2 h", 76 → "3.2 d"; null → "—" (no data). */
export function formatHours(hours: number | null | undefined): string {
  if (hours === null || hours === undefined) return "—";
  if (hours < MINUTE_IN_HOURS) return "< 1 min"; // not "0 min": it did take time
  if (hours < 1) return `${Math.round(hours * 60)} min`;
  if (hours < 48) return `${hours.toFixed(1)} h`;
  return `${(hours / 24).toFixed(1)} d`;
}

export function useMetrics(orgId: string, days: PeriodDays, enabled: boolean) {
  return useQuery({
    queryKey: ["metrics", orgId, days] as const,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/orgs/{org_id}/metrics", {
          params: { path: { org_id: orgId }, query: { days } },
        }),
      ),
    enabled,
  });
}
