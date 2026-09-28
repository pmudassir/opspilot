import { expect, test } from "@playwright/test";

import { createOrg, PASSWORD, pageAs, uniqueEmail } from "./support";

test("signup creates an organization and lands on its requests", async ({ page }) => {
  await page.goto("/signup");
  await page.getByLabel("Organization name").fill("Harbor View Hotel");
  await page.getByLabel("Your name").fill("Priya Raman");
  await page.getByLabel("Work email").fill(uniqueEmail("priya"));
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create organization" }).click();

  await expect(page).toHaveURL(/\/orgs\/[0-9a-f-]{36}\/requests$/);
  await expect(page.getByRole("banner")).toContainText("Harbor View Hotel");
  await expect(page.getByRole("banner")).toContainText("admin");
});

test("logged-out deep link goes to login, then back to the deep link", async ({ page, baseURL }) => {
  const org = await createOrg(baseURL!);
  const deepLink = `/orgs/${org.orgId}/requests?status=open`;

  await page.goto(deepLink);
  await expect(page).toHaveURL(/\/login\?next=/);
  await page.getByLabel("Email").fill(org.admin.email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(deepLink);
});

test("regression: a logged-out visit checks the session once, not in a loop", async ({ page }) => {
  let meCalls = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/api/v1/auth/me")) meCalls += 1;
  });

  await page.goto("/orgs/00000000-0000-0000-0000-000000000000/requests");
  await expect(page).toHaveURL(/\/login/);
  await page.waitForTimeout(1_000); // a loop would keep firing during this window

  expect(meCalls).toBe(1);
});

test("next= cannot redirect off-site after login (open redirect guard)", async ({ page, baseURL }) => {
  const org = await createOrg(baseURL!);

  await page.goto("/login?next=https://evil.example/phish");
  await page.getByLabel("Email").fill(org.admin.email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(new RegExp(`^${baseURL}/orgs/${org.orgId}/requests$`));
});

test("wrong password shows a generic error", async ({ page, baseURL }) => {
  const org = await createOrg(baseURL!);

  await page.goto("/login");
  await page.getByLabel("Email").fill(org.admin.email);
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("alert").filter({ hasText: "Invalid email or password" })).toBeVisible();
});

test("sign out ends the session server-side", async ({ browser, baseURL }) => {
  const org = await createOrg(baseURL!);
  const page = await pageAs(browser, org.admin);

  await page.goto(`/orgs/${org.orgId}/requests`);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.goto(`/orgs/${org.orgId}/requests`);
  await expect(page).toHaveURL(/\/login\?next=/);
});
