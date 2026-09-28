import {
  type APIRequestContext,
  type Browser,
  expect,
  type Page,
  request,
} from "@playwright/test";

/**
 * Setup goes through the API (fast, deterministic); behaviour under test goes through
 * the UI. Every test builds its own organization, so tests are independent.
 */

export const PASSWORD = "correct-horse-battery";

export function uniqueEmail(name: string): string {
  const suffix = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
  return `${name}-${suffix}@e2e.example`;
}

export type Actor = { email: string; name: string; membershipId: string; api: APIRequestContext };

async function apiContext(baseURL: string): Promise<APIRequestContext> {
  // Origin is required: the backend rejects cross-origin writes (CSRF check).
  return request.newContext({ baseURL, extraHTTPHeaders: { Origin: baseURL } });
}

async function ok<T>(response: Awaited<ReturnType<APIRequestContext["post"]>>): Promise<T> {
  expect(response.ok(), `${response.url()} → ${response.status()} ${await response.text()}`).toBe(true);
  return (response.status() === 204 ? undefined : await response.json()) as T;
}

export type Org = {
  orgId: string;
  admin: Actor;
  addMember: (name: string, role: "admin" | "manager" | "agent" | "member") => Promise<Actor>;
  createDepartment: (name: string) => Promise<string>;
  addToDepartment: (departmentId: string, actor: Actor) => Promise<void>;
  createRequest: (as: Actor, departmentId: string, title: string) => Promise<string>;
  act: (as: Actor, requestId: string, action: string, body?: object) => Promise<void>;
};

export async function createOrg(baseURL: string, orgName = "E2E Hotel"): Promise<Org> {
  const adminApi = await apiContext(baseURL);
  const adminEmail = uniqueEmail("admin");
  const me = await ok<{ memberships: { organization_id: string }[] }>(
    await adminApi.post("/api/v1/auth/signup", {
      data: { email: adminEmail, password: PASSWORD, full_name: "Ana Admin", organization_name: orgName },
    }),
  );
  const orgId = me.memberships[0].organization_id;
  const members = await ok<{ membership_id: string; email: string }[]>(
    await adminApi.get(`/api/v1/orgs/${orgId}/members`),
  );
  const admin: Actor = { email: adminEmail, name: "Ana Admin", membershipId: members[0].membership_id, api: adminApi };
  const org = `/api/v1/orgs/${orgId}`;

  return {
    orgId,
    admin,
    async addMember(name, role) {
      const email = uniqueEmail(name.toLowerCase().replace(/\W+/g, "-"));
      const member = await ok<{ membership_id: string }>(
        await adminApi.post(`${org}/members`, { data: { email, full_name: name, password: PASSWORD, role } }),
      );
      const api = await apiContext(baseURL);
      await ok(await api.post("/api/v1/auth/login", { data: { email, password: PASSWORD } }));
      return { email, name, membershipId: member.membership_id, api };
    },
    async createDepartment(name) {
      return (await ok<{ id: string }>(await adminApi.post(`${org}/departments`, { data: { name } }))).id;
    },
    async addToDepartment(departmentId, actor) {
      await ok(await adminApi.put(`${org}/departments/${departmentId}/members/${actor.membershipId}`));
    },
    async createRequest(as, departmentId, title) {
      const created = await ok<{ id: string }>(
        await as.api.post(`${org}/requests`, { data: { title, department_id: departmentId } }),
      );
      return created.id;
    },
    async act(as, requestId, action, body) {
      await ok(await as.api.post(`${org}/requests/${requestId}/${action}`, { data: body }));
    },
  };
}

/** A browser page signed in as `actor` (session copied from their API context). */
export async function pageAs(browser: Browser, actor: Actor): Promise<Page> {
  const context = await browser.newContext({ storageState: await actor.api.storageState() });
  return context.newPage();
}

/** Our error box. (Next.js also renders an empty, hidden role="alert" route announcer.) */
export function errorBox(page: Page) {
  return page.getByRole("alert").filter({ hasText: /\S/ });
}
