import { expect, type Page, test } from "@playwright/test";

import { createOrg, errorBox, pageAs } from "./support";

/**
 * The e2e backend runs without an AI key (like CI), so the real provider is never called.
 * These tests intercept two calls in the browser: /me (feature flag on) and the draft
 * endpoint (canned suggestion). Backend AI behaviour has its own tests.
 */
async function enableAiDrafts(page: Page, draft: object | { status: number; detail: string }) {
  await page.route("**/api/v1/auth/me", async (route) => {
    const response = await route.fetch();
    const json = await response.json();
    await route.fulfill({ response, json: { ...json, features: { ...json.features, ai_request_drafts: true } } });
  });
  await page.route("**/ai/request-drafts", (route) =>
    "status" in draft
      ? route.fulfill({ status: draft.status, json: { detail: draft.detail } })
      : route.fulfill({ json: draft }),
  );
}

const TEXT = "The Wi-Fi in the second-floor meeting room keeps disconnecting and we have a client meeting in 20 minutes.";

test("without AI configured there is no AI panel", async ({ browser, baseURL }) => {
  const org = await createOrg(baseURL!);
  await org.createDepartment("IT");
  const page = await pageAs(browser, org.admin);

  await page.goto(`/orgs/${org.orgId}/requests/new`);

  await expect(page.getByLabel("What's wrong?")).toBeVisible();
  await expect(page.getByRole("button", { name: "Draft with AI" })).toHaveCount(0);
});

test("an AI draft pre-fills the form; the person edits and submits it", async ({ browser, baseURL }) => {
  const org = await createOrg(baseURL!);
  const it = await org.createDepartment("IT");
  await org.createDepartment("Housekeeping");
  const page = await pageAs(browser, org.admin);
  await enableAiDrafts(page, {
    title: "Wi-Fi drops in second-floor meeting room",
    description: "Keeps disconnecting; client meeting in 20 minutes.",
    department_id: it,
    department_name: "IT",
    priority: "urgent",
    rationale: "Network issue with imminent business impact.",
    model: "openai/gpt-oss-120b",
  });

  await page.goto(`/orgs/${org.orgId}/requests/new`);
  await page.getByLabel("Describe the problem").fill(TEXT);
  await page.getByRole("button", { name: "Draft with AI" }).click();

  await expect(page.getByRole("status")).toContainText("Drafted by AI. Please review before submitting.");
  await expect(page.getByRole("status")).toContainText("Network issue with imminent business impact.");
  await expect(page.getByLabel("What's wrong?")).toHaveValue("Wi-Fi drops in second-floor meeting room");
  await expect(page.getByLabel("Details")).toHaveValue("Keeps disconnecting; client meeting in 20 minutes.");
  await expect(page.getByLabel("Department")).toHaveValue(it);
  await expect(page.getByLabel("Priority")).toHaveValue("urgent");

  // The draft is only a suggestion: the person changes it, and their version is saved.
  await page.getByLabel("What's wrong?").fill("Wi-Fi down in meeting room 2B");
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Wi-Fi down in meeting room 2B");
  await expect(page.getByText("Ana Admin reported this request")).toBeVisible();
});

test("when AI can't pick a department, the person is asked to choose", async ({ browser, baseURL }) => {
  const org = await createOrg(baseURL!);
  await org.createDepartment("IT");
  const page = await pageAs(browser, org.admin);
  await enableAiDrafts(page, {
    title: "Strange smell near the loading dock",
    description: "",
    department_id: null,
    department_name: null,
    priority: "high",
    rationale: "Possible safety issue; no department clearly fits.",
    model: "openai/gpt-oss-120b",
  });

  await page.goto(`/orgs/${org.orgId}/requests/new`);
  await page.getByLabel("Describe the problem").fill("There's a strange smell near the loading dock.");
  await page.getByRole("button", { name: "Draft with AI" }).click();

  await expect(page.getByRole("status")).toContainText("Choose one below.");
  await expect(page.getByLabel("Department")).toHaveValue("");
});

test("an AI failure is explained and the form still works by hand", async ({ browser, baseURL }) => {
  const org = await createOrg(baseURL!);
  await org.createDepartment("IT");
  const page = await pageAs(browser, org.admin);
  await enableAiDrafts(page, {
    status: 503,
    detail: "The AI service is busy right now. Please try again or fill in the request yourself.",
  });

  await page.goto(`/orgs/${org.orgId}/requests/new`);
  await page.getByLabel("Describe the problem").fill(TEXT);
  await page.getByRole("button", { name: "Draft with AI" }).click();

  await expect(errorBox(page)).toContainText("fill in the request yourself");
  await page.getByLabel("What's wrong?").fill("Wi-Fi keeps disconnecting");
  await page.getByLabel("Department").selectOption({ label: "IT" });
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Wi-Fi keeps disconnecting");
});
