"use client";

import { createContext, useContext } from "react";

import type { Role } from "@/lib/auth";

export type CurrentOrg = {
  organizationId: string;
  organizationName: string;
  /** For showing/hiding UI only. The API enforces every permission. */
  role: Role;
};

export const OrgContext = createContext<CurrentOrg | null>(null);

export function useCurrentOrg(): CurrentOrg {
  const org = useContext(OrgContext);
  if (!org) throw new Error("useCurrentOrg must be used inside an organization page");
  return org;
}
