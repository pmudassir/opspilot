import { expect, test } from "@playwright/test";

import { PASSWORD, uniqueEmail } from "./support";

/**
 * The critical path, entirely through the UI: a new organization is set up, a member
 * reports a problem, an agent works it to completion, and the history is complete.
 */
test("new organization → setup → request reported, claimed, worked and completed", async ({ browser }) => {
  const emails = { ana: uniqueEmail("ana"), raj: uniqueEmail("raj"), mei: uniqueEmail("mei") };
  const ana = await (await browser.newContext()).newPage();

  // Signup
  await ana.goto("/signup");
  await ana.getByLabel("Organization name").fill("Lakeside Offices");
  await ana.getByLabel("Your name").fill("Ana Lima");
  await ana.getByLabel("Work email").fill(emails.ana);
  await ana.getByLabel("Password").fill(PASSWORD);
  await ana.getByRole("button", { name: "Create organization" }).click();
  await expect(ana).toHaveURL(/\/requests$/);

  // No departments yet → the new-request page sends the admin to create one
  await ana.getByRole("link", { name: "New request" }).click();
  await ana.getByRole("link", { name: "Create a department first." }).click();
  await ana.getByLabel("New department").fill("IT");
  await ana.getByRole("button", { name: "Create" }).click();
  await expect(ana.getByRole("heading", { name: "IT", level: 2, exact: true })).toBeVisible();

  // Members
  await ana.getByRole("link", { name: "Members" }).click();
  for (const [key, fullName, role] of [["raj", "Raj Patel", "agent"], ["mei", "Mei Chen", "member"]] as const) {
    await ana.getByRole("button", { name: "Add member" }).click();
    const form = ana.getByRole("form", { name: "Add member" });
    await form.getByLabel("Full name").fill(fullName);
    await form.getByLabel("Email").fill(emails[key]);
    await form.getByLabel("Role").selectOption(role);
    await form.getByLabel("Initial password").fill(PASSWORD);
    await form.getByRole("button", { name: "Add member" }).click();
    await expect(ana.getByRole("status")).toContainText(`${fullName} was added`);
  }

  // Raj joins IT
  await ana.getByRole("link", { name: "Departments" }).click();
  await ana.getByLabel("Add to IT").selectOption({ label: "Raj Patel (Agent)" });
  await ana.getByLabel("Add to IT").locator("xpath=..").getByRole("button", { name: "Add", exact: true }).click();
  await expect(ana.getByRole("list", { name: "IT staff" })).toContainText("Raj Patel");

  // Mei reports a problem
  const mei = await (await browser.newContext()).newPage();
  await mei.goto("/login");
  await mei.getByLabel("Email").fill(emails.mei);
  await mei.getByLabel("Password").fill(PASSWORD);
  await mei.getByRole("button", { name: "Sign in" }).click();
  await mei.getByRole("link", { name: "New request" }).click();
  await mei.getByLabel("What's wrong?").fill("Laptop won't connect to the VPN");
  await mei.getByLabel("Details").fill("Since this morning, both at home and in the office.");
  await mei.getByLabel("Department").selectOption({ label: "IT" });
  await mei.getByLabel("Priority").selectOption("high");
  await mei.getByRole("button", { name: "Submit request" }).click();
  await expect(mei.getByText("Mei Chen reported this request")).toBeVisible();
  const requestUrl = mei.url();

  // Raj claims, starts, comments, completes
  const raj = await (await browser.newContext()).newPage();
  await raj.goto("/login");
  await raj.getByLabel("Email").fill(emails.raj);
  await raj.getByLabel("Password").fill(PASSWORD);
  await raj.getByRole("button", { name: "Sign in" }).click();
  await raj.getByRole("link", { name: "Laptop won't connect to the VPN" }).click();
  await expect(raj).toHaveURL(requestUrl);
  await raj.getByRole("button", { name: "Claim" }).click();
  await expect(raj.getByText("Raj Patel claimed this request")).toBeVisible();
  await raj.getByRole("button", { name: "Start work" }).click();
  // Wait like a person would: otherwise the comment races the start request.
  await expect(raj.getByText("Raj Patel started work")).toBeVisible();
  await raj.getByLabel("Add a comment").fill("VPN profile expired. Reissued it.");
  await raj.getByRole("button", { name: "Comment", exact: true }).click();
  await expect(raj.getByLabel("Add a comment")).toHaveValue("");
  await raj.getByRole("button", { name: "Mark complete" }).click();
  await expect(raj.getByText("No actions available to you on this request.")).toBeVisible();

  // Mei sees the whole story
  await mei.reload();
  await expect(mei.getByRole("heading", { level: 1 }).locator("xpath=..")).toContainText("Completed");
  await expect(mei.locator("ol > li")).toHaveText([
    /Mei Chen reported this request/,
    /Raj Patel claimed this request/,
    /Raj Patel started work/,
    /VPN profile expired/,
    /Raj Patel marked it complete/,
  ]);
});
