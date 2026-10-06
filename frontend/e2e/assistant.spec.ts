import { expect, type Page, type Request, test } from "@playwright/test";

import { createOrg, errorBox, pageAs } from "./support";

/**
 * The e2e backend runs without an AI key, so the provider is never called. These tests
 * intercept /me (feature on) and the assistant endpoint (canned answer or error), and
 * check what the UI does with them. Tool calling itself has its own backend tests.
 */
async function enableAssistant(page: Page, reply: object | { status: number; detail: string }) {
  const asked: Request[] = [];
  await page.route("**/api/v1/auth/me", async (route) => {
    const response = await route.fetch();
    const json = await response.json();
    await route.fulfill({ response, json: { ...json, features: { ...json.features, ai_assistant: true } } });
  });
  await page.route("**/ai/assistant", (route) => {
    asked.push(route.request());
    return "status" in reply
      ? route.fulfill({ status: reply.status, json: { detail: reply.detail } })
      : route.fulfill({ json: reply });
  });
  return asked;
}

test("without AI configured there is no Ask page in the menu", async ({ browser, baseURL }) => {
  const org = await createOrg(baseURL!);
  const page = await pageAs(browser, org.admin);
  await page.goto(`/orgs/${org.orgId}/requests`);
  await expect(page.getByRole("link", { name: "Requests" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Ask", exact: true })).toHaveCount(0);
});

test("an answer links only the requests the server referenced", async ({ browser, baseURL }) => {
  const org = await createOrg(baseURL!);
  const it = await org.createDepartment("IT");
  const printer = await org.createRequest(org.admin, it, "Printer jammed on floor 2");
  const page = await pageAs(browser, org.admin);
  const asked = await enableAssistant(page, {
    answer: "R1 (Printer jammed on floor 2) is open and unassigned. R9 is not a real ref.",
    references: [{ ref: "R1", request_id: printer, title: "Printer jammed on floor 2" }],
    tools_used: [{ tool: "search_requests", status: "ok" }],
    model: "openai/gpt-oss-120b",
    as_of: new Date().toISOString(),
  });

  await page.goto(`/orgs/${org.orgId}/requests`);
  await page.getByRole("link", { name: "Ask", exact: true }).click();
  await page.getByLabel("Your question").fill("Which requests are unassigned?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();

  const answer = page.getByRole("article", { name: "Answer" });
  await expect(answer).toContainText("is open and unassigned");
  await expect(answer).toContainText("Looked up: searched requests.");
  await expect(answer.getByRole("link", { name: "R9" })).toHaveCount(0);
  expect(asked[0].postDataJSON()).toEqual({ question: "Which requests are unassigned?", request_id: null });

  await answer.getByRole("link", { name: "R1", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Printer jammed on floor 2");
});

test("asking from a request page sends that request as context", async ({ browser, baseURL }) => {
  const org = await createOrg(baseURL!);
  const it = await org.createDepartment("IT");
  const printer = await org.createRequest(org.admin, it, "Printer jammed on floor 2");
  const page = await pageAs(browser, org.admin);
  const asked = await enableAssistant(page, {
    answer: "Nobody has picked it up yet.",
    references: [],
    tools_used: [{ tool: "get_request_history", status: "ok" }],
    model: "openai/gpt-oss-120b",
    as_of: new Date().toISOString(),
  });

  await page.goto(`/orgs/${org.orgId}/requests/${printer}`);
  await page.getByRole("link", { name: "Ask about this request" }).click();
  await expect(page.getByText("About: Printer jammed on floor 2")).toBeVisible();
  await page.getByRole("button", { name: "Summarise this request" }).click();

  await expect(page.getByRole("article", { name: "Answer" })).toContainText("Nobody has picked it up yet.");
  expect(asked[0].postDataJSON()).toEqual({ question: "Summarise this request", request_id: printer });
});

test("an assistant failure is explained and the question is kept", async ({ browser, baseURL }) => {
  const org = await createOrg(baseURL!);
  const page = await pageAs(browser, org.admin);
  await enableAssistant(page, { status: 503, detail: "The AI service is busy right now. Please try again." });

  await page.goto(`/orgs/${org.orgId}/ask`);
  await page.getByLabel("Your question").fill("What's assigned to me?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();

  await expect(errorBox(page)).toContainText("busy right now");
  await expect(page.getByLabel("Your question")).toHaveValue("What's assigned to me?");
});

function proposalReply(printer: string) {
  const now = new Date();
  const proposal = {
    id: "8d4c2c5e-0f5b-4d8f-9a51-3b1f0c7e2a10",
    action: "change_priority",
    status: "pending",
    summary: "Change the priority of 1 request to urgent",
    new_assignee_name: null,
    new_priority: "urgent",
    comment_body: null,
    items: [{ request_id: printer, title: "Printer jammed on floor 2", status: "open", priority: "normal", assignee_name: null }],
    payload_hash: "a".repeat(64),
    expires_at: new Date(now.getTime() + 10 * 60_000).toISOString(),
    created_at: now.toISOString(),
    decided_at: null,
    failure_code: null,
    failure_detail: null,
  };
  return {
    proposal,
    answer: {
      answer: "I've proposed making R1 urgent. It's waiting for your approval.",
      references: [{ ref: "R1", request_id: printer, title: "Printer jammed on floor 2" }],
      tools_used: [{ tool: "propose_priority", status: "ok" }],
      model: "openai/gpt-oss-120b",
      as_of: now.toISOString(),
      proposal,
    },
  };
}

async function askForProposal(page: Page, orgId: string) {
  await page.goto(`/orgs/${orgId}/ask`);
  await page.getByLabel("Your question").fill("Make the printer request urgent");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  return page.getByRole("region", { name: "Proposed change" });
}

test("a proposal is previewed and approving sends back exactly what was shown", async ({ browser, baseURL }) => {
  const org = await createOrg(baseURL!);
  const printer = await org.createRequest(org.admin, await org.createDepartment("IT"), "Printer jammed on floor 2");
  const page = await pageAs(browser, org.admin);
  const { proposal, answer } = proposalReply(printer);
  await enableAssistant(page, answer);
  const approvals: Request[] = [];
  await page.route("**/ai/proposals/*/approve", (route) => {
    approvals.push(route.request());
    return route.fulfill({ json: { ...proposal, status: "executed", decided_at: new Date().toISOString() } });
  });

  const card = await askForProposal(page, org.orgId);
  await expect(card).toContainText("Change the priority of 1 request to urgent");
  await expect(card).toContainText("nothing happens until you approve");
  await expect(card.getByRole("listitem")).toContainText("Normal → Urgent");
  await card.getByRole("button", { name: "Approve" }).click();

  await expect(card.getByRole("status")).toHaveText("Approved and applied.");
  await expect(card.getByRole("button", { name: "Approve" })).toHaveCount(0);
  expect(approvals).toHaveLength(1);
  expect(approvals[0].url()).toContain(`/ai/proposals/${proposal.id}/approve`);
  expect(approvals[0].postDataJSON()).toEqual({ payload_hash: proposal.payload_hash });
});

test("approving a proposal that expired shows why and its real state", async ({ browser, baseURL }) => {
  const org = await createOrg(baseURL!);
  const printer = await org.createRequest(org.admin, await org.createDepartment("IT"), "Printer jammed on floor 2");
  const page = await pageAs(browser, org.admin);
  const { proposal, answer } = proposalReply(printer);
  await enableAssistant(page, answer);
  await page.route("**/ai/proposals/*/approve", (route) =>
    route.fulfill({ status: 409, json: { detail: "This proposal expired. Ask again for a fresh one." } }),
  );
  // After a 409 the card reloads the proposal from the server.
  await page.route(`**/ai/proposals/${proposal.id}`, (route) => route.fulfill({ json: { ...proposal, status: "expired" } }));

  const card = await askForProposal(page, org.orgId);
  await card.getByRole("button", { name: "Approve" }).click();

  await expect(errorBox(page)).toContainText("This proposal expired.");
  await expect(card.getByRole("status")).toContainText("Expired before it was approved. Nothing was changed");
  await expect(card.getByRole("button", { name: "Approve" })).toHaveCount(0);
});
