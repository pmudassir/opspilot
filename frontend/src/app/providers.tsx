"use client";

import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";

import { ApiError, isUnauthorized } from "@/lib/api/client";
import { meQueryKey } from "@/lib/auth";

const MAX_RETRIES = 2;

function makeQueryClient(): QueryClient {
  // Any 401 means the session ended (expired, revoked, logged out elsewhere).
  // Refetching "me" lets the app shell notice and send the user to /login in one place.
  const refetchMeOnUnauthorized = (error: unknown) => {
    if (isUnauthorized(error)) void client.invalidateQueries({ queryKey: meQueryKey });
  };
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        // Never for "me" itself: its own 401 would invalidate it again → infinite refetch loop.
        if (query.queryKey[0] !== meQueryKey[0]) refetchMeOnUnauthorized(error);
      },
    }),
    mutationCache: new MutationCache({ onError: refetchMeOnUnauthorized }),
    defaultOptions: {
      queries: {
        // Retrying a 4xx can't succeed; only retry network errors and 5xx.
        retry: (failureCount, error) =>
          !(error instanceof ApiError && error.status < 500) && failureCount < MAX_RETRIES,
      },
    },
  });
  return client;
}

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(makeQueryClient);
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
