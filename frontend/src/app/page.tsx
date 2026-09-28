"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { ErrorAlert, PageLoading } from "@/components/ui/feedback";
import { isUnauthorized } from "@/lib/api/client";
import { useMe } from "@/lib/auth";

/** Entry point: send the user to login, or into their first organization. */
export default function HomePage() {
  const router = useRouter();
  const me = useMe();
  const firstOrgId = me.data?.memberships[0]?.organization_id;

  useEffect(() => {
    if (isUnauthorized(me.error)) router.replace("/login");
    else if (firstOrgId) router.replace(`/orgs/${firstOrgId}/requests`);
  }, [me.error, firstOrgId, router]);

  if (me.data && !firstOrgId) {
    return (
      <main className="mx-auto max-w-md p-12 text-sm text-zinc-600">
        Your account isn&apos;t an active member of any organization. Ask an admin to add you.
      </main>
    );
  }
  if (me.error && !isUnauthorized(me.error)) {
    return (
      <main className="mx-auto max-w-md p-12">
        <ErrorAlert error={me.error} />
      </main>
    );
  }
  return <PageLoading />;
}
