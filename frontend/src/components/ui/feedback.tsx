import { errorMessage } from "@/lib/api/client";

export function ErrorAlert({ error }: { error: unknown }) {
  return (
    <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      {errorMessage(error)}
    </div>
  );
}

export function PageLoading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex flex-1 items-center justify-center p-12 text-sm text-zinc-500">
      {label}
    </div>
  );
}
