"use client";

import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect } from "react";

import { Button } from "@/components/ui/button";
import { ErrorAlert, PageLoading } from "@/components/ui/feedback";
import { isUnauthorized } from "@/lib/api/client";
import { useLogout, useMe } from "@/lib/auth";
import { OrgContext } from "@/lib/org";

const NAV = [{ href: "requests", label: "Requests" }] as const;

/** Layout for /orgs/[orgId]/*: requires a session and membership of that organization. */
export function AppShell({ children }: { children: ReactNode }) {
  const { orgId } = useParams<{ orgId: string }>();
  const pathname = usePathname();
  const router = useRouter();
  const me = useMe();
  const logout = useLogout();

  useEffect(() => {
    if (isUnauthorized(me.error)) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [me.error, pathname, router]);

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

  const org = {
    organizationId: membership.organization_id,
    organizationName: membership.organization_name,
    role: membership.role,
  };

  return (
    <OrgContext.Provider value={org}>
      <header className="border-b border-zinc-200 bg-white">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-6">
          <span className="text-sm font-semibold tracking-tight text-teal-800">OpsPilot</span>
          <OrgSwitcher currentOrgId={orgId} memberships={me.data.memberships} />
          <nav className="flex gap-1">
            {NAV.map((item) => {
              const href = `/orgs/${orgId}/${item.href}`;
              const active = pathname.startsWith(href);
              return (
                <Link
                  key={item.href}
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={`rounded-md px-3 py-1.5 text-sm ${active ? "bg-zinc-100 font-medium text-zinc-900" : "text-zinc-600 hover:text-zinc-900"}`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <span className="text-zinc-700">{me.data.user.full_name}</span>
            <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-600">{membership.role}</span>
            <Button
              variant="ghost"
              size="sm"
              pending={logout.isPending}
              onClick={() => logout.mutate(undefined, { onSettled: () => router.replace("/login") })}
            >
              Sign out
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">{children}</main>
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
