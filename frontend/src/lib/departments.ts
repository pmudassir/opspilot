import { useQuery } from "@tanstack/react-query";

import { api, type Schemas, unwrap } from "@/lib/api/client";

export type Department = Schemas["DepartmentOut"];

export type Member = Schemas["MemberOut"];

export const departmentKeys = {
  all: (orgId: string) => ["departments", orgId] as const,
  members: (orgId: string, departmentId: string) =>
    ["departments", orgId, departmentId, "members"] as const,
};

export function useDepartments(orgId: string) {
  return useQuery({
    queryKey: departmentKeys.all(orgId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/orgs/{org_id}/departments", { params: { path: { org_id: orgId } } })),
    staleTime: 5 * 60_000, // departments rarely change
  });
}

/** Only managers/admins may read members; pass enabled=false for everyone else. */
export function useDepartmentMembers(orgId: string, departmentId: string, enabled: boolean) {
  return useQuery({
    queryKey: departmentKeys.members(orgId, departmentId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/orgs/{org_id}/departments/{department_id}/members", {
          params: { path: { org_id: orgId, department_id: departmentId } },
        }),
      ),
    enabled,
  });
}
