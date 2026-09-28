import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

/** Typed client for the OpsPilot API (paths, params and bodies come from the OpenAPI schema). */
export const api = createClient<paths>({ baseUrl: "" });

export type Schemas = components["schemas"];

type ValidationIssue = { loc: (string | number)[]; msg: string };

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : `Request failed (${status})`);
    this.name = "ApiError";
  }

  /** FastAPI 422 validation messages keyed by body field name. */
  get fieldErrors(): Record<string, string> {
    if (!Array.isArray(this.detail)) return {};
    const errors: Record<string, string> = {};
    for (const issue of this.detail as ValidationIssue[]) {
      const field = issue.loc.at(-1);
      if (typeof field === "string" && !(field in errors)) errors[field] = issue.msg;
    }
    return errors;
  }
}

export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

type ApiResult<T> = { data?: T; error?: unknown; response: Response };

/** Resolve an openapi-fetch call to its data, or throw an ApiError (for TanStack Query). */
export async function unwrap<T>(call: Promise<ApiResult<T>>): Promise<T> {
  const { data, error, response } = await call;
  if (!response.ok) {
    const detail =
      error && typeof error === "object" && "detail" in error ? error.detail : undefined;
    throw new ApiError(response.status, detail);
  }
  return data as T;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (typeof error.detail === "string") return error.detail;
    if (Array.isArray(error.detail)) return "Please correct the highlighted fields.";
    return `Something went wrong (HTTP ${error.status}). Please try again.`;
  }
  return "Can't reach OpsPilot. Check your connection and try again.";
}
