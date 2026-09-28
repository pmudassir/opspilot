import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

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

export function useCreateDepartment(orgId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      unwrap(
        api.POST("/api/v1/orgs/{org_id}/departments", {
          params: { path: { org_id: orgId } },
          body: { name },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: departmentKeys.all(orgId) }),
  });
}

type DepartmentMemberChange = { departmentId: string; membershipId: string };

/** Add (PUT) or remove (DELETE) a member; both are idempotent on the API. */
export function useDepartmentMembership(orgId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ change, add }: { change: DepartmentMemberChange; add: boolean }) => {
      const params = {
        path: { org_id: orgId, department_id: change.departmentId, membership_id: change.membershipId },
      };
      const path = "/api/v1/orgs/{org_id}/departments/{department_id}/members/{membership_id}" as const;
      return unwrap(add ? api.PUT(path, { params }) : api.DELETE(path, { params }));
    },
    onSuccess: (_, { change }) =>
      queryClient.invalidateQueries({ queryKey: departmentKeys.members(orgId, change.departmentId) }),
  });
}
