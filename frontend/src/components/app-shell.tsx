"use client";

import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect } from "react";

import { Button } from "@/components/ui/button";
import { ErrorAlert, PageLoading } from "@/components/ui/feedback";
import { isUnauthorized } from "@/lib/api/client";
import { useLogout, useMe } from "@/lib/auth";
import { OrgContext, type Permission } from "@/lib/org";

const NAV: { href: string; label: string; permission: Permission }[] = [
  { href: "requests", label: "Requests", permission: "requests:read" },
  { href: "members", label: "Members", permission: "members:read" },
  { href: "departments", label: "Departments", permission: "departments:read" },
  { href: "metrics", label: "Metrics", permission: "metrics:read" },
];

/** Layout for /orgs/[orgId]/*: requires a session and membership of that organization. */
export function AppShell({ children }: { children: ReactNode }) {
  const { orgId } = useParams<{ orgId: string }>();
  const pathname = usePathname();
  const router = useRouter();
  const me = useMe();
  const logout = useLogout();

  useEffect(() => {
    if (!isUnauthorized(me.error)) return;
    // Include the query string, so a filtered deep link survives the trip through login.
    const here = window.location.pathname + window.location.search;
    router.replace(`/login?next=${encodeURIComponent(here)}`);
  }, [me.error, router]);

  if (me.error && !isUnauthorized(me.error)) {
    return (
      <main className="mx-auto max-w-md p-12">
        <ErrorAlert error={me.error} />
      </main>
    );
  }
  if (!me.data) return <PageLoading />;

  const membership = me.data.memberships.find((m) => m.organization_id === orgId);
  if (!membership) {
    return (
      <main className="mx-auto max-w-md p-12 text-sm text-zinc-600">
        Organization not found.{" "}
        <Link href="/" className="font-medium text-teal-800 hover:underline">
          Go to your organizations
        </Link>
      </main>
    );
  }

  const permissions = new Set(membership.permissions);
  const org = {
    organizationId: membership.organization_id,
    organizationName: membership.organization_name,
    role: membership.role,
    can: (permission: Permission) => permissions.has(permission),
  };

  return (
    <OrgContext.Provider value={org}>
      <header className="border-b border-zinc-200 bg-white">
        {/* Wraps on small screens: the nav drops to its own full-width row and scrolls
            horizontally, instead of making the whole page wider than the viewport. */}
        <div className="mx-auto flex min-h-14 max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2 sm:px-6">
          <span className="text-sm font-semibold tracking-tight text-teal-800">OpsPilot</span>
          <OrgSwitcher currentOrgId={orgId} memberships={me.data.memberships} />
          <nav className="order-last -mx-1 flex w-full gap-1 overflow-x-auto sm:order-none sm:mx-0 sm:w-auto">
            {NAV.filter((item) => org.can(item.permission)).map((item) => {
              const href = `/orgs/${orgId}/${item.href}`;
              const active = pathname.startsWith(href);
              return (
                <Link
                  key={item.href}
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={`shrink-0 rounded-md px-3 py-1.5 text-sm ${active ? "bg-zinc-100 font-medium text-zinc-900" : "text-zinc-600 hover:text-zinc-900"}`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <span className="hidden text-zinc-700 sm:inline">{me.data.user.full_name}</span>
            <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-600">{membership.role}</span>
            <Button
              variant="ghost"
              size="sm"
              pending={logout.isPending}
              onClick={() => logout.mutate()}
            >
              Sign out
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6 sm:py-8">{children}</main>
    </OrgContext.Provider>
  );
}

function OrgSwitcher({
  currentOrgId,
  memberships,
}: {
  currentOrgId: string;
  memberships: { organization_id: string; organization_name: string }[];
}) {
  const router = useRouter();
  if (memberships.length === 1) {
    return <span className="text-sm text-zinc-700">{memberships[0].organization_name}</span>;
  }
  return (
    <select
      aria-label="Organization"
      value={currentOrgId}
      onChange={(event) => router.push(`/orgs/${event.target.value}/requests`)}
      className="h-8 rounded-md border border-zinc-300 bg-white px-2 text-sm"
    >
      {memberships.map((m) => (
        <option key={m.organization_id} value={m.organization_id}>
          {m.organization_name}
        </option>
      ))}
    </select>
  );
}
