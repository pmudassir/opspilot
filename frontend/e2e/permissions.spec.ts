import { expect, test } from "@playwright/test";

import { createOrg, errorBox, pageAs } from "./support";

test("navigation and pages follow the API's permissions per role", async ({ browser, baseURL }) => {
  const org = await createOrg(baseURL!);
  const agent = await org.addMember("Sam Okafor", "agent");
  const member = await org.addMember("Mei Chen", "member");
  const nav = (page: import("@playwright/test").Page) => page.locator("header nav a");

  const memberPage = await pageAs(browser, member);
  await memberPage.goto(`/orgs/${org.orgId}/requests`);
  await expect(nav(memberPage)).toHaveText(["Requests", "Departments"]);
  await memberPage.goto(`/orgs/${org.orgId}/members`);
  await expect(memberPage.getByText("You don't have access to this page.")).toBeVisible();

  const agentPage = await pageAs(browser, agent);
  await agentPage.goto(`/orgs/${org.orgId}/members`);
  await expect(nav(agentPage)).toHaveText(["Requests", "Members", "Departments"]);
  await expect(agentPage.locator("tbody tr")).toHaveCount(3);
  await expect(agentPage.getByRole("button", { name: "Add member" })).toHaveCount(0);
  await expect(agentPage.getByRole("combobox")).toHaveCount(0);
});

test("a stale page gets a 409 and refreshes to the actions that are valid now", async ({ browser, baseURL }) => {
  const org = await createOrg(baseURL!);
  const it = await org.createDepartment("IT");
  const agent = await org.addMember("Sam Okafor", "agent");
  await org.addToDepartment(it, agent);
  const requestId = await org.createRequest(org.admin, it, "Printer jammed");
  const page = await pageAs(browser, agent);
  await page.goto(`/orgs/${org.orgId}/requests/${requestId}`);
  await expect(page.getByRole("button", { name: "Claim" })).toBeVisible();

  await org.act(org.admin, requestId, "assign", { assignee_membership_id: agent.membershipId }); // meanwhile
  await page.getByRole("button", { name: "Claim" }).click();

  await expect(errorBox(page)).toContainText("Cannot claim a request that is assigned");
  await expect(page.getByRole("button", { name: "Start work" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Claim" })).toHaveCount(0);
});

test("deactivating someone removes their access on the next request", async ({ browser, baseURL }) => {
  const org = await createOrg(baseURL!);
  const agent = await org.addMember("Sam Okafor", "agent");
  const agentPage = await pageAs(browser, agent);
  await agentPage.goto(`/orgs/${org.orgId}/requests`);
  await expect(agentPage.getByRole("heading", { name: "Requests" })).toBeVisible();

  const adminPage = await pageAs(browser, org.admin);
  await adminPage.goto(`/orgs/${org.orgId}/members`);
  const row = adminPage.locator("tbody tr").filter({ hasText: "Sam Okafor" });
  await row.getByRole("button", { name: "Deactivate…" }).click();
  await row.getByRole("button", { name: "Deactivate", exact: true }).click();
  await expect(row).toContainText("Deactivated");

  await agentPage.reload();
  await expect(agentPage.getByText("Organization not found.")).toBeVisible();
});

test("the last admin can't be demoted, and the UI says why", async ({ browser, baseURL }) => {
  const org = await createOrg(baseURL!);
  const page = await pageAs(browser, org.admin);
  await page.goto(`/orgs/${org.orgId}/members`);

  await page.getByLabel("Role for Ana Admin").selectOption("agent");

  await expect(errorBox(page)).toContainText("An organization must keep at least one active admin");
  await expect(page.getByLabel("Role for Ana Admin")).toHaveValue("admin");
});
