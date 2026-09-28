"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";

import { RequestFiltersBar } from "@/components/requests/request-filters";
import { RequestTable } from "@/components/requests/request-table";
import { Button } from "@/components/ui/button";
import { ErrorAlert, PageLoading } from "@/components/ui/feedback";
import { useDepartments } from "@/lib/departments";
import { useCurrentOrg } from "@/lib/org";
import {
  filtersToSearchParams,
  hasFilters,
  NO_FILTERS,
  parseFilters,
  type RequestFilters,
  useRequests,
} from "@/lib/requests";

export default function RequestsPage() {
  return (
    <Suspense fallback={<PageLoading />}>
      <RequestsView />
    </Suspense>
  );
}

function RequestsView() {
  const { organizationId } = useCurrentOrg();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const filters = useMemo(() => parseFilters(searchParams), [searchParams]);

  const departments = useDepartments(organizationId);
  const requests = useRequests(organizationId, filters);
  const items = requests.data?.pages.flatMap((page) => page.items) ?? [];

  // push (not replace): each filter change is a history entry, so Back undoes it.
  function setFilters(next: RequestFilters) {
    const query = filtersToSearchParams(next).toString();
    router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  return (
    <section className="flex flex-col gap-5">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-lg font-semibold">Requests</h1>
        <Link
          href={`/orgs/${organizationId}/requests/new`}
          className="inline-flex h-9 items-center rounded-md bg-teal-700 px-3.5 text-sm font-medium text-white hover:bg-teal-800"
        >
          New request
        </Link>
      </div>

      <RequestFiltersBar
        filters={filters}
        departments={departments.data ?? []}
        onChange={setFilters}
      />

      {requests.isPending ? (
        <PageLoading label="Loading requests…" />
      ) : requests.isError ? (
        <div className="flex flex-col items-start gap-3">
          <ErrorAlert error={requests.error} />
          <Button variant="secondary" size="sm" onClick={() => void requests.refetch()}>
            Try again
          </Button>
        </div>
      ) : items.length === 0 ? (
        <EmptyState filtered={hasFilters(filters)} onClear={() => setFilters(NO_FILTERS)} />
      ) : (
        <>
          <RequestTable requests={items} />
          {requests.hasNextPage && (
            <div className="flex justify-center">
              <Button
                variant="secondary"
                pending={requests.isFetchingNextPage}
                onClick={() => void requests.fetchNextPage()}
              >
                Load more
              </Button>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function EmptyState({ filtered, onClear }: { filtered: boolean; onClear: () => void }) {
  return (
    <div className="rounded-md border border-dashed border-zinc-300 px-6 py-12 text-center text-sm text-zinc-600">
      {filtered ? (
        <>
          No requests match these filters.{" "}
          <button type="button" onClick={onClear} className="font-medium text-teal-800 hover:underline">
            Clear filters
          </button>
        </>
      ) : (
        "No requests yet. When someone reports an issue, it shows up here."
      )}
    </div>
  );
}
