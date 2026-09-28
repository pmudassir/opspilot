"use client";

import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { ErrorAlert, PageLoading } from "@/components/ui/feedback";
import { TextField } from "@/components/ui/field";
import { ApiError } from "@/lib/api/client";
import {
  type Department,
  useCreateDepartment,
  useDepartmentMembers,
  useDepartmentMembership,
  useDepartments,
} from "@/lib/departments";
import { ROLE_LABELS, useMembers } from "@/lib/members";
import { useCurrentOrg } from "@/lib/org";

export default function DepartmentsPage() {
  const { organizationId, can } = useCurrentOrg();
  const departments = useDepartments(organizationId);
  const canManage = can("departments:manage");
  const canSeeMembers = can("members:read");
  // Everyone in the org, for the "add to department" pickers (admins only).
  const orgMembers = useMembers(organizationId, canManage);

  if (departments.isPending) return <PageLoading label="Loading departments…" />;
  if (departments.isError) return <ErrorAlert error={departments.error} />;

  return (
    <section className="flex flex-col gap-5">
      <div>
        <h1 className="text-lg font-semibold">Departments</h1>
        <p className="text-sm text-zinc-600">Requests are routed to a department; its staff can claim and work them.</p>
      </div>
      {canManage && <CreateDepartmentForm orgId={organizationId} />}
      {departments.data.length === 0 ? (
        <p className="rounded-md border border-dashed border-zinc-300 px-6 py-10 text-center text-sm text-zinc-600">
          No departments yet.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-zinc-100 rounded-md border border-zinc-200 bg-white">
          {departments.data.map((department) => (
            <li key={department.id} className="p-4">
              <h2 className="text-sm font-semibold text-zinc-900">{department.name}</h2>
              {canSeeMembers && (
                <DepartmentStaff
                  orgId={organizationId}
                  department={department}
                  canManage={canManage}
                  candidates={(orgMembers.data ?? []).filter((m) => m.status === "active")}
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function CreateDepartmentForm({ orgId }: { orgId: string }) {
  const create = useCreateDepartment(orgId);
  const [name, setName] = useState("");
  const fieldError = create.error instanceof ApiError ? create.error.fieldErrors.name : undefined;

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    create.mutate(name, { onSuccess: () => setName("") });
  }

  return (
    <form onSubmit={onSubmit} aria-label="Create department" className="flex flex-col gap-2">
      <div className="flex items-end gap-2">
        <TextField
          label="New department"
          name="name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Housekeeping"
          required
          maxLength={100}
          className="w-full max-w-xs"
          error={fieldError}
        />
        <Button type="submit" pending={create.isPending} disabled={!name.trim()}>
          Create
        </Button>
      </div>
      {create.error && !fieldError && <ErrorAlert error={create.error} />}
    </form>
  );
}

type Candidate = { membership_id: string; full_name: string; role: keyof typeof ROLE_LABELS };

function DepartmentStaff({
  orgId,
  department,
  canManage,
  candidates,
}: {
  orgId: string;
  department: Department;
  canManage: boolean;
  candidates: Candidate[];
}) {
  const staff = useDepartmentMembers(orgId, department.id, true);
  const change = useDepartmentMembership(orgId);
  const [selected, setSelected] = useState("");

  if (staff.isPending) return <p className="mt-2 text-sm text-zinc-500">Loading…</p>;
  if (staff.isError) return <ErrorAlert error={staff.error} />;

  const inDepartment = new Set(staff.data.map((m) => m.membership_id));
  const addable = candidates.filter((m) => !inDepartment.has(m.membership_id));
  const busyFor = (membershipId: string) =>
    change.isPending && change.variables?.change.membershipId === membershipId;

  return (
    <div className="mt-2 flex flex-col gap-3">
      {change.error && <ErrorAlert error={change.error} />}
      {staff.data.length === 0 ? (
        <p className="text-sm text-zinc-500">No one in this department yet.</p>
      ) : (
        <ul className="flex flex-wrap gap-2" aria-label={`${department.name} staff`}>
          {staff.data.map((member) => (
            <li key={member.membership_id} className="inline-flex items-center gap-1.5 rounded-md border border-zinc-200 bg-zinc-50 py-1 pr-1 pl-2.5 text-sm">
              <span>{member.full_name}</span>
              <span className="text-xs text-zinc-500">{ROLE_LABELS[member.role]}</span>
              {member.status === "deactivated" && <span className="text-xs text-zinc-400">(deactivated)</span>}
              {canManage && (
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={`Remove ${member.full_name} from ${department.name}`}
                  className="h-6 px-1.5"
                  pending={busyFor(member.membership_id)}
                  onClick={() => change.mutate({ add: false, change: { departmentId: department.id, membershipId: member.membership_id } })}
                >
                  ×
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {canManage && addable.length > 0 && (
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!selected) return;
            change.mutate(
              { add: true, change: { departmentId: department.id, membershipId: selected } },
              { onSuccess: () => setSelected("") },
            );
          }}
        >
          <select
            aria-label={`Add to ${department.name}`}
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
            className="h-8 min-w-0 rounded-md border border-zinc-300 bg-white px-2 text-sm"
          >
            <option value="">Add someone…</option>
            {addable.map((m) => (
              <option key={m.membership_id} value={m.membership_id}>
                {m.full_name} ({ROLE_LABELS[m.role]})
              </option>
            ))}
          </select>
          <Button type="submit" variant="secondary" size="sm" disabled={!selected} pending={change.isPending && change.variables?.add === true}>
            Add
          </Button>
        </form>
      )}
    </div>
  );
}
