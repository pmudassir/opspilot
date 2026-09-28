"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { ErrorAlert, PageLoading } from "@/components/ui/feedback";
import { SelectField, TextAreaField, TextField } from "@/components/ui/field";
import { ApiError } from "@/lib/api/client";
import { useDepartments } from "@/lib/departments";
import { useCurrentOrg } from "@/lib/org";
import {
  PRIORITY_LABELS,
  REQUEST_PRIORITIES,
  type RequestPriority,
  useCreateRequest,
} from "@/lib/requests";

const TITLE_MAX_LENGTH = 200;
const DESCRIPTION_MAX_LENGTH = 5000;

export default function NewRequestPage() {
  const { organizationId, can } = useCurrentOrg();
  const router = useRouter();
  const departments = useDepartments(organizationId);
  const create = useCreateRequest(organizationId);
  const fieldErrors = create.error instanceof ApiError ? create.error.fieldErrors : {};
  const listHref = `/orgs/${organizationId}/requests`;

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    create.mutate(
      {
        title: String(form.get("title")),
        description: String(form.get("description") ?? ""),
        department_id: String(form.get("department_id")),
        priority: String(form.get("priority")) as RequestPriority,
      },
      { onSuccess: (created) => router.push(`${listHref}/${created.id}`) },
    );
  }

  if (departments.isPending) return <PageLoading />;
  if (departments.isError) return <ErrorAlert error={departments.error} />;
  if (departments.data.length === 0) {
    return (
      <div className="max-w-xl text-sm text-zinc-600">
        Requests are routed to a department, and this organization has none yet.{" "}
        {can("departments:manage") ? (
          <Link href={`/orgs/${organizationId}/departments`} className="font-medium text-teal-800 hover:underline">
            Create a department first.
          </Link>
        ) : (
          "Ask an admin to create one."
        )}
      </div>
    );
  }

  return (
    <section className="max-w-xl">
      <Link href={listHref} className="text-sm text-zinc-600 hover:text-zinc-900">
        ← Requests
      </Link>
      <h1 className="mt-3 text-lg font-semibold">New request</h1>
      <p className="mt-1 text-sm text-zinc-600">Describe the problem and where it is. The right team will pick it up.</p>
      <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-4">
        {create.error && <ErrorAlert error={create.error} />}
        <TextField
          label="What's wrong?"
          name="title"
          required
          maxLength={TITLE_MAX_LENGTH}
          placeholder="Wi-Fi keeps dropping in meeting room 2"
          error={fieldErrors.title}
          autoFocus
        />
        <TextAreaField
          label="Details"
          name="description"
          maxLength={DESCRIPTION_MAX_LENGTH}
          hint="Location, when it started, anything already tried."
          error={fieldErrors.description}
        />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <SelectField label="Department" name="department_id" required defaultValue="" error={fieldErrors.department_id}>
            <option value="" disabled>
              Choose a department
            </option>
            {departments.data.map((department) => (
              <option key={department.id} value={department.id}>
                {department.name}
              </option>
            ))}
          </SelectField>
          <SelectField label="Priority" name="priority" defaultValue="normal" error={fieldErrors.priority}>
            {REQUEST_PRIORITIES.map((priority) => (
              <option key={priority} value={priority}>
                {PRIORITY_LABELS[priority]}
              </option>
            ))}
          </SelectField>
        </div>
        <div className="flex gap-2">
          <Button type="submit" pending={create.isPending}>
            Submit request
          </Button>
          <Link
            href={listHref}
            className="inline-flex h-10 items-center rounded-md px-4 text-sm text-zinc-600 hover:bg-zinc-100"
          >
            Cancel
          </Link>
        </div>
      </form>
    </section>
  );
}
