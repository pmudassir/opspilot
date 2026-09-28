import { expect, test } from "@playwright/test";

import { createOrg, errorBox, pageAs } from "./support";

const PAGE_SIZE = 25;

test.describe("request list", () => {
  test("load more walks through every page once", async ({ browser, baseURL }) => {
    const org = await createOrg(baseURL!);
    const it = await org.createDepartment("IT");
    for (let n = 0; n < PAGE_SIZE + 3; n++) await org.createRequest(org.admin, it, `Issue ${n}`);
    const page = await pageAs(browser, org.admin);

    await page.goto(`/orgs/${org.orgId}/requests`);
    await expect(page.locator("tbody tr")).toHaveCount(PAGE_SIZE);
    await expect(page.locator("tbody tr").first()).toContainText(`Issue ${PAGE_SIZE + 2}`); // newest first
    await page.getByRole("button", { name: "Load more" }).click();

    await expect(page.locator("tbody tr")).toHaveCount(PAGE_SIZE + 3);
    await expect(page.getByRole("button", { name: "Load more" })).toHaveCount(0);
  });

  test("filters live in the URL and Back undoes them (regression)", async ({ browser, baseURL }) => {
    const org = await createOrg(baseURL!);
    const it = await org.createDepartment("IT");
    const agent = await org.addMember("Sam Okafor", "agent");
    await org.addToDepartment(it, agent);
    await org.createRequest(org.admin, it, "Still open");
    const claimed = await org.createRequest(org.admin, it, "Being worked");
    await org.act(agent, claimed, "claim");
    const page = await pageAs(browser, org.admin);

    await page.goto(`/orgs/${org.orgId}/requests`);
    await expect(page.locator("tbody tr")).toHaveCount(2);
    await page.getByRole("button", { name: "Assigned", exact: true }).click();

    await expect(page).toHaveURL(/\?status=assigned$/);
    await expect(page.locator("tbody tr")).toHaveText([/Being worked/]);
    await page.reload();
    await expect(page.locator("tbody tr")).toHaveText([/Being worked/]); // survives reload

    await page.goBack();
    await expect(page).not.toHaveURL(/status=/);
    await expect(page.locator("tbody tr")).toHaveCount(2);
  });

  test("junk filter values in the URL are ignored, not errors (regression)", async ({ browser, baseURL }) => {
    const org = await createOrg(baseURL!);
    const it = await org.createDepartment("IT");
    await org.createRequest(org.admin, it, "Only request");
    const page = await pageAs(browser, org.admin);

    await page.goto(`/orgs/${org.orgId}/requests?status=bogus&priority=whenever&department_id=nope`);

    await expect(page.locator("tbody tr")).toHaveText([/Only request/]);
    await expect(errorBox(page)).toHaveCount(0);
  });

  test("filtered empty state offers to clear filters", async ({ browser, baseURL }) => {
    const org = await createOrg(baseURL!);
    const it = await org.createDepartment("IT");
    await org.createRequest(org.admin, it, "Normal priority");
    const page = await pageAs(browser, org.admin);

    await page.goto(`/orgs/${org.orgId}/requests?priority=urgent`);
    await expect(page.getByText("No requests match these filters.")).toBeVisible();
    await page.getByRole("button", { name: "Clear filters" }).last().click();

    await expect(page.locator("tbody tr")).toHaveText([/Normal priority/]);
  });
});
