"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, Suspense } from "react";

import { Button } from "@/components/ui/button";
import { ErrorAlert } from "@/components/ui/feedback";
import { TextField } from "@/components/ui/field";
import { safeNextPath, useLogin } from "@/lib/auth";

export default function LoginPage() {
  // useSearchParams must sit inside a Suspense boundary (Next.js prerendering rule).
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const next = safeNextPath(useSearchParams().get("next"));
  const login = useLogin();

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    login.mutate(
      { email: String(form.get("email")), password: String(form.get("password")) },
      { onSuccess: () => router.replace(next) },
    );
  }

  return (
    <>
      <h1 className="text-xl font-semibold">Sign in</h1>
      <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-4">
        {login.error && <ErrorAlert error={login.error} />}
        <TextField label="Email" name="email" type="email" autoComplete="email" required autoFocus />
        <TextField label="Password" name="password" type="password" autoComplete="current-password" required />
        <Button type="submit" pending={login.isPending}>
          Sign in
        </Button>
      </form>
      <p className="mt-6 text-sm text-zinc-600">
        New to OpsPilot?{" "}
        <Link href="/signup" className="font-medium text-teal-800 hover:underline">
          Create an organization
        </Link>
      </p>
    </>
  );
}
