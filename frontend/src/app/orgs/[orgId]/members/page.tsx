"use client";

import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { ErrorAlert, PageLoading } from "@/components/ui/feedback";
import { SelectField, TextField } from "@/components/ui/field";
import { NoAccess } from "@/components/ui/no-access";
import { ApiError } from "@/lib/api/client";
import { useMe } from "@/lib/auth";
import {
  type Member,
  ROLE_LABELS,
  ROLES,
  type Role,
  useAddMember,
  useMembers,
  useUpdateMember,
} from "@/lib/members";
import { useCurrentOrg } from "@/lib/org";

const PASSWORD_MIN_LENGTH = 12;

export default function MembersPage() {
  const { organizationId, can } = useCurrentOrg();
  const canRead = can("members:read");
  const canManage = can("members:manage");
  const members = useMembers(organizationId, canRead);
  const update = useUpdateMember(organizationId);
  const me = useMe();
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  if (!canRead) return <NoAccess />;
  if (members.isPending) return <PageLoading label="Loading members…" />;
  if (members.isError) return <ErrorAlert error={members.error} />;

  const active = members.data.filter((m) => m.status === "active").length;

  return (
    <section className="flex flex-col gap-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold">Members</h1>
          <p className="text-sm text-zinc-600">
            {active} active of {members.data.length}
          </p>
        </div>
        {canManage && !adding && (
          <Button size="sm" onClick={() => { setAdding(true); setNotice(null); }}>
            Add member
          </Button>
        )}
      </div>

      {notice && (
        <p role="status" className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
          {notice}
        </p>
      )}
      {adding && (
        <AddMemberForm
          orgId={organizationId}
          onDone={(added) => {
            setAdding(false);
            if (added) setNotice(`${added.full_name} was added as ${ROLE_LABELS[added.role].toLowerCase()}. Share their initial password with them securely.`);
          }}
        />
      )}
      {update.error && <ErrorAlert error={update.error} />}

      <div className="overflow-x-auto rounded-md border border-zinc-200 bg-white">
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <thead className="border-b border-zinc-200 bg-zinc-50 text-left text-xs font-medium tracking-wide text-zinc-500 uppercase">
            <tr>
              <th scope="col" className="px-3 py-2">Name</th>
              <th scope="col" className="px-3 py-2">Role</th>
              <th scope="col" className="px-3 py-2">Status</th>
              {canManage && <th scope="col" className="px-3 py-2"><span className="sr-only">Actions</span></th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {members.data.map((member) => (
              <MemberRow
                key={member.membership_id}
                member={member}
                isYou={member.user_id === me.data?.user.id}
                canManage={canManage}
                update={update}
              />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

type Update = ReturnType<typeof useUpdateMember>;

function MemberRow({ member, isYou, canManage, update }: { member: Member; isYou: boolean; canManage: boolean; update: Update }) {
  const [confirmingDeactivate, setConfirmingDeactivate] = useState(false);
  const busy = update.isPending && update.variables?.membershipId === member.membership_id;
  const deactivated = member.status === "deactivated";

  return (
    <tr className={deactivated ? "bg-zinc-50 text-zinc-500" : undefined}>
      <td className="px-3 py-2.5">
        <p className={deactivated ? "" : "font-medium text-zinc-900"}>
          {member.full_name} {isYou && <span className="text-xs font-normal text-zinc-500">(you)</span>}
        </p>
        <p className="text-xs text-zinc-500">{member.email}</p>
      </td>
      <td className="px-3 py-2.5">
        {canManage && !deactivated ? (
          <select
            aria-label={`Role for ${member.full_name}`}
            value={member.role}
            disabled={busy}
            onChange={(event) => update.mutate({ membershipId: member.membership_id, role: event.target.value as Role })}
            className="h-8 rounded-md border border-zinc-300 bg-white px-2 text-sm"
          >
            {ROLES.map((role) => (
              <option key={role} value={role}>{ROLE_LABELS[role]}</option>
            ))}
          </select>
        ) : (
          ROLE_LABELS[member.role]
        )}
      </td>
      <td className="px-3 py-2.5">
        <span className={`rounded px-1.5 py-0.5 text-xs ring-1 ring-inset ${deactivated ? "bg-zinc-100 text-zinc-600 ring-zinc-200" : "bg-emerald-50 text-emerald-800 ring-emerald-200"}`}>
          {deactivated ? "Deactivated" : "Active"}
        </span>
      </td>
      {canManage && (
        <td className="px-3 py-2.5 text-right whitespace-nowrap">
          {deactivated ? (
            <Button variant="secondary" size="sm" pending={busy} onClick={() => update.mutate({ membershipId: member.membership_id, status: "active" })}>
              Reactivate
            </Button>
          ) : confirmingDeactivate ? (
            <span className="inline-flex items-center gap-2">
              <span className="text-xs text-zinc-600">{isYou ? "You'll lose access." : "They'll lose access."}</span>
              <Button
                variant="danger"
                size="sm"
                pending={busy}
                onClick={() => update.mutate({ membershipId: member.membership_id, status: "deactivated" }, { onSettled: () => setConfirmingDeactivate(false) })}
              >
                Deactivate
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setConfirmingDeactivate(false)}>Keep</Button>
            </span>
          ) : (
            <Button variant="ghost" size="sm" disabled={update.isPending} onClick={() => setConfirmingDeactivate(true)}>
              Deactivate…
            </Button>
          )}
        </td>
      )}
    </tr>
  );
}

function AddMemberForm({ orgId, onDone }: { orgId: string; onDone: (added: Member | null) => void }) {
  const add = useAddMember(orgId);
  const fieldErrors = add.error instanceof ApiError ? add.error.fieldErrors : {};

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    add.mutate(
      {
        full_name: String(form.get("full_name")),
        email: String(form.get("email")),
        role: String(form.get("role")) as Role,
        password: String(form.get("password")),
      },
      { onSuccess: (added) => onDone(added) },
    );
  }

  return (
    <form onSubmit={onSubmit} aria-label="Add member" className="flex flex-col gap-4 rounded-md border border-zinc-200 bg-white p-4">
      <h2 className="text-sm font-semibold">Add a member</h2>
      {add.error && <ErrorAlert error={add.error} />}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <TextField label="Full name" name="full_name" required autoFocus error={fieldErrors.full_name} />
        <TextField label="Email" name="email" type="email" required error={fieldErrors.email} />
        <SelectField label="Role" name="role" defaultValue="agent" error={fieldErrors.role}>
          {ROLES.map((role) => (
            <option key={role} value={role}>{ROLE_LABELS[role]}</option>
          ))}
        </SelectField>
        <TextField
          label="Initial password"
          name="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={PASSWORD_MIN_LENGTH}
          hint={`At least ${PASSWORD_MIN_LENGTH} characters. Share it with them securely.`}
          error={fieldErrors.password}
        />
      </div>
      <div className="flex gap-2">
        <Button type="submit" size="sm" pending={add.isPending}>Add member</Button>
        <Button variant="ghost" size="sm" onClick={() => onDone(null)}>Cancel</Button>
      </div>
    </form>
  );
}
