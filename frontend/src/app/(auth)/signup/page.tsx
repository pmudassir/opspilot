"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { ErrorAlert } from "@/components/ui/feedback";
import { TextField } from "@/components/ui/field";
import { ApiError } from "@/lib/api/client";
import { useSignup } from "@/lib/auth";

const PASSWORD_MIN_LENGTH = 12;

export default function SignupPage() {
  const router = useRouter();
  const signup = useSignup();
  const fieldErrors = signup.error instanceof ApiError ? signup.error.fieldErrors : {};

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    signup.mutate(
      {
        full_name: String(form.get("full_name")),
        email: String(form.get("email")),
        password: String(form.get("password")),
        organization_name: String(form.get("organization_name")),
      },
      {
        onSuccess: (me) => {
          const orgId = me.memberships[0]?.organization_id;
          router.replace(orgId ? `/orgs/${orgId}/requests` : "/");
        },
      },
    );
  }

  return (
    <>
      <h1 className="text-xl font-semibold">Create your organization</h1>
      <p className="mt-1 text-sm text-zinc-600">You&apos;ll be its first admin.</p>
      <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-4">
        {signup.error && <ErrorAlert error={signup.error} />}
        <TextField label="Organization name" name="organization_name" required error={fieldErrors.organization_name} placeholder="Harbor View Hotel" />
        <TextField label="Your name" name="full_name" autoComplete="name" required error={fieldErrors.full_name} />
        <TextField label="Work email" name="email" type="email" autoComplete="email" required error={fieldErrors.email} />
        <TextField
          label="Password"
          name="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={PASSWORD_MIN_LENGTH}
          hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}
          error={fieldErrors.password}
        />
        <Button type="submit" pending={signup.isPending}>
          Create organization
        </Button>
      </form>
      <p className="mt-6 text-sm text-zinc-600">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-teal-800 hover:underline">
          Sign in
        </Link>
      </p>
    </>
  );
}
