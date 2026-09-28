import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Schemas, unwrap } from "@/lib/api/client";

export const meQueryKey = ["me"] as const;

export type Me = Schemas["MeResponse"];
export type Role = Schemas["MembershipRole"];

export function useMe() {
  return useQuery({
    queryKey: meQueryKey,
    queryFn: () => unwrap(api.GET("/api/v1/auth/me")),
    retry: false,
    staleTime: 60_000,
  });
}

/** Clears every cached query first: nothing from a previous user may leak into this session. */
function useStartSession() {
  const queryClient = useQueryClient();
  return (me: Me) => {
    queryClient.clear();
    queryClient.setQueryData(meQueryKey, me);
  };
}

export function useLogin() {
  const startSession = useStartSession();
  return useMutation({
    mutationFn: (body: Schemas["LoginRequest"]) =>
      unwrap(api.POST("/api/v1/auth/login", { body })),
    onSuccess: startSession,
  });
}

export function useSignup() {
  const startSession = useStartSession();
  return useMutation({
    mutationFn: (body: Schemas["SignupRequest"]) =>
      unwrap(api.POST("/api/v1/auth/signup", { body })),
    onSuccess: startSession,
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/auth/logout")),
    onSettled: () => queryClient.clear(),
  });
}

/**
 * Only allow same-site relative paths as a post-login destination.
 * Otherwise `/login?next=https://evil.example` (or `//evil.example`) would be an open redirect.
 */
export function safeNextPath(raw: string | null): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return "/";
  return raw;
}
