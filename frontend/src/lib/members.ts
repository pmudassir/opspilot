import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Schemas, unwrap } from "@/lib/api/client";
import { meQueryKey } from "@/lib/auth";

export type Member = Schemas["MemberOut"];
export type Role = Schemas["MembershipRole"];
export type MembershipStatus = Schemas["MembershipStatus"];

export const ROLE_LABELS: Record<Role, string> = {
  admin: "Admin",
  manager: "Manager",
  agent: "Agent",
  member: "Member",
};

export const ROLES = Object.keys(ROLE_LABELS) as Role[];

export const memberKeys = {
  all: (orgId: string) => ["members", orgId] as const,
};

export function useMembers(orgId: string, enabled = true) {
  return useQuery({
    queryKey: memberKeys.all(orgId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/orgs/{org_id}/members", { params: { path: { org_id: orgId } } })),
    enabled,
  });
}

export function useAddMember(orgId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["AddMemberRequest"]) =>
      unwrap(api.POST("/api/v1/orgs/{org_id}/members", { params: { path: { org_id: orgId } }, body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: memberKeys.all(orgId) }),
  });
}

export function useUpdateMember(orgId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ membershipId, ...body }: { membershipId: string } & Schemas["UpdateMemberRequest"]) =>
      unwrap(
        api.PATCH("/api/v1/orgs/{org_id}/members/{membership_id}", {
          params: { path: { org_id: orgId, membership_id: membershipId } },
          body,
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: memberKeys.all(orgId) });
      // Department member lists show roles/status too; and the change may be to *our own*
      // membership (role → permissions, or deactivation → access), so refresh the session.
      void queryClient.invalidateQueries({ queryKey: ["departments", orgId] });
      void queryClient.invalidateQueries({ queryKey: meQueryKey });
    },
  });
}
