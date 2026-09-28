"use client";

import { createContext, useContext } from "react";

import type { Schemas } from "@/lib/api/client";
import type { Role } from "@/lib/auth";

export type Permission = Schemas["Permission"];

export type CurrentOrg = {
  organizationId: string;
  organizationName: string;
  role: Role;
  /**
   * The permissions the API enforces for this membership (from /me).
   * Use for showing/hiding UI only; the API checks every call regardless.
   */
  can: (permission: Permission) => boolean;
};

export const OrgContext = createContext<CurrentOrg | null>(null);

export function useCurrentOrg(): CurrentOrg {
  const org = useContext(OrgContext);
  if (!org) throw new Error("useCurrentOrg must be used inside an organization page");
  return org;
}
