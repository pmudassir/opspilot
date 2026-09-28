import { useQuery } from "@tanstack/react-query";

import { api, type Schemas, unwrap } from "@/lib/api/client";

export type Department = Schemas["DepartmentOut"];

export const departmentKeys = {
  all: (orgId: string) => ["departments", orgId] as const,
};

export function useDepartments(orgId: string) {
  return useQuery({
    queryKey: departmentKeys.all(orgId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/orgs/{org_id}/departments", { params: { path: { org_id: orgId } } })),
    staleTime: 5 * 60_000, // departments rarely change
  });
}
