import { expect, test } from "@playwright/test";

import { createOrg, pageAs } from "./support";

test("a manager changes priority; it shows in history; an agent gets no control", async ({ browser, baseURL }) => {
  const org = await createOrg(baseURL!);
  const it = await org.createDepartment("IT");
  const manager = await org.addMember("Mona Manager", "manager");
  const agent = await org.addMember("Arjun Agent", "agent");
  await org.addToDepartment(it, agent);
  const requestId = await org.createRequest(org.admin, it, "Projector in ballroom not working");

  const page = await pageAs(browser, manager);
  await page.goto(`/orgs/${org.orgId}/requests/${requestId}`);
  await page.getByLabel("Priority").selectOption("urgent");
  await page.getByRole("button", { name: "Change priority" }).click();
  await expect(page.getByText("Mona Manager changed the priority from normal to urgent")).toBeVisible();
  await expect(page.getByRole("button", { name: "Change priority" })).toBeDisabled(); // already urgent

  const agentPage = await pageAs(browser, agent);
  await agentPage.goto(`/orgs/${org.orgId}/requests/${requestId}`);
  await expect(agentPage.getByRole("heading", { level: 1 })).toHaveText("Projector in ballroom not working");
  await expect(agentPage.getByRole("button", { name: "Change priority" })).toHaveCount(0);
});
