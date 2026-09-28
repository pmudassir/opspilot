import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { api, type Schemas, unwrap } from "@/lib/api/client";

export type RequestItem = Schemas["RequestOut"];
export type RequestStatus = Schemas["RequestStatus"];
export type RequestPriority = Schemas["RequestPriority"];

// Records keyed by the generated union types: adding a status in the backend makes these
// fail to compile until the frontend handles it.
export const STATUS_LABELS: Record<RequestStatus, string> = {
  open: "Open",
  assigned: "Assigned",
  in_progress: "In progress",
  completed: "Completed",
  cancelled: "Cancelled",
};

export const PRIORITY_LABELS: Record<RequestPriority, string> = {
  urgent: "Urgent",
  high: "High",
  normal: "Normal",
  low: "Low",
};

export const REQUEST_STATUSES = Object.keys(STATUS_LABELS) as RequestStatus[];
export const REQUEST_PRIORITIES = Object.keys(PRIORITY_LABELS) as RequestPriority[];

export const PAGE_SIZE = 25;

export type RequestFilters = {
  statuses: RequestStatus[];
  departmentId: string | null;
  priority: RequestPriority | null;
};

export const NO_FILTERS: RequestFilters = { statuses: [], departmentId: null, priority: null };

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isStatus(value: string): value is RequestStatus {
  return value in STATUS_LABELS;
}

function isPriority(value: string | null): value is RequestPriority {
  return value !== null && value in PRIORITY_LABELS;
}

/** The URL is user input: keep only known values, in canonical order, without duplicates. */
export function parseFilters(params: URLSearchParams): RequestFilters {
  const requested = new Set(params.getAll("status").filter(isStatus));
  const departmentId = params.get("department_id");
  const priority = params.get("priority");
  return {
    statuses: REQUEST_STATUSES.filter((status) => requested.has(status)),
    departmentId: departmentId && UUID_PATTERN.test(departmentId) ? departmentId : null,
    priority: isPriority(priority) ? priority : null,
  };
}

export function filtersToSearchParams(filters: RequestFilters): URLSearchParams {
  const params = new URLSearchParams();
  for (const status of filters.statuses) params.append("status", status);
  if (filters.departmentId) params.set("department_id", filters.departmentId);
  if (filters.priority) params.set("priority", filters.priority);
  return params;
}

export function hasFilters(filters: RequestFilters): boolean {
  return filters.statuses.length > 0 || filters.departmentId !== null || filters.priority !== null;
}

export const requestKeys = {
  all: (orgId: string) => ["requests", orgId] as const,
  list: (orgId: string, filters: RequestFilters) => ["requests", orgId, "list", filters] as const,
};

export function useRequests(orgId: string, filters: RequestFilters) {
  return useInfiniteQuery({
    queryKey: requestKeys.list(orgId, filters),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/orgs/{org_id}/requests", {
          params: {
            path: { org_id: orgId },
            query: {
              status: filters.statuses.length ? filters.statuses : undefined,
              department_id: filters.departmentId ?? undefined,
              priority: filters.priority ?? undefined,
              limit: PAGE_SIZE,
              cursor: pageParam,
            },
          },
        }),
      ),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });
}

export function useCreateRequest(orgId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["CreateRequestBody"]) =>
      unwrap(
        api.POST("/api/v1/orgs/{org_id}/requests", { params: { path: { org_id: orgId } }, body }),
      ),
    // Every filtered list of this org may now be out of date.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: requestKeys.all(orgId) }),
  });
}
