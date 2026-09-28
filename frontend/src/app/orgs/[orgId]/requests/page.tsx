"use client";

import { useCurrentOrg } from "@/lib/org";

export default function RequestsPage() {
  const org = useCurrentOrg();
  return (
    <section>
      <h1 className="text-lg font-semibold">Requests</h1>
      <p className="mt-2 text-sm text-zinc-600">
        {org.organizationName}: the request list arrives in the next step.
      </p>
    </section>
  );
}
