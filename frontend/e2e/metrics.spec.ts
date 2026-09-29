import { expect, type Page, test } from "@playwright/test";

import { createOrg, pageAs } from "./support";

const tile = (page: Page, label: string) =>
  page.locator("dl > div").filter({ has: page.locator("dt", { hasText: new RegExp(`^${label}$`) }) });

test("managers see backlog and flow metrics per department", async ({ browser, baseURL }) => {
  const org = await createOrg(baseURL!);
  const it = await org.createDepartment("IT");
  await org.createDepartment("Security");
  const agent = await org.addMember("Sam Okafor", "agent");
  const manager = await org.addMember("Diego Alvarez", "manager");
  await org.addToDepartment(it, agent);
  const done = await org.createRequest(org.admin, it, "Projector remote missing");
  for (const action of ["claim", "start", "complete"]) await org.act(agent, done, action);
  await org.createRequest(org.admin, it, "Wi-Fi drops in room 2");

  const page = await pageAs(browser, manager);
  await page.goto(`/orgs/${org.orgId}/requests`);
  await page.getByRole("link", { name: "Metrics" }).click();

  await expect(tile(page, "Backlog").locator("dd").first()).toHaveText("1");
  await expect(tile(page, "Created").locator("dd").first()).toHaveText("2");
  await expect(tile(page, "Completed").locator("dd").first()).toHaveText("1");
  const itRow = page.getByRole("row", { name: /^IT/ });
  await expect(itRow.getByRole("cell")).toHaveText(["1", "2", "1", "0", /\d.*\/.*\d/, /\d.*\/.*\d/]);
  await expect(page.getByRole("row", { name: /^Security/ })).toContainText("— / —");

  await page.getByLabel("Period").selectOption("7");
  await expect(page).toHaveURL(/\?days=7$/);
  await expect(tile(page, "Created").locator("dd").first()).toHaveText("2");
});

test("agents don't get metrics", async ({ browser, baseURL }) => {
  const org = await createOrg(baseURL!);
  const agent = await org.addMember("Sam Okafor", "agent");
  const page = await pageAs(browser, agent);

  await page.goto(`/orgs/${org.orgId}/requests`);
  await expect(page.locator("header nav a")).not.toContainText(["Metrics"]);
  await page.goto(`/orgs/${org.orgId}/metrics`);
  await expect(page.getByText("You don't have access to this page.")).toBeVisible();
});
