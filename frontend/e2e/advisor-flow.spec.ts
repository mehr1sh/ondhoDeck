import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

const MAILPIT = process.env.E2E_MAILPIT_URL || "http://localhost:8025/api/v1";
const FIXTURE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "fixtures/synthetic-reit-prospectus.pdf");
const stamp = Date.now().toString(36);
const email = `e2e-advisor-${stamp}@example.com`;
const password = "Correct-Horse-91!";
const fundName = `Example Income REIT ${stamp}`;

async function confirmationLink(to: string): Promise<string> {
  for (let i = 0; i < 30; i++) {
    const res = await fetch(`${MAILPIT}/search?query=${encodeURIComponent(`to:${to}`)}`);
    const { messages = [] } = (await res.json()) as { messages?: { ID: string }[] };
    for (const m of messages) {
      const body = (await (await fetch(`${MAILPIT}/message/${m.ID}`)).json()) as { Text?: string; HTML?: string };
      const links = `${body.Text ?? ""} ${body.HTML ?? ""}`.match(/https?:\/\/[^\s"'<>]+/g) ?? [];
      const link = links.map((l) => l.replace(/&amp;/g, "&")).find((l) => l.includes("/verify") && l.includes("type=signup"));
      if (link) return link;
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`no confirmation email for ${to}`);
}

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByRole("textbox", { name: "Email" }).fill(email);
  await page.getByRole("textbox", { name: "Password", exact: true }).fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
}

test.describe.serial("advisor workflow", () => {
  test("register, confirm email and sign in", async ({ page }) => {
    await page.goto("/register");
    await page.getByRole("textbox", { name: "Email" }).fill(email);
    await page.getByRole("textbox", { name: "Password", exact: true }).fill(password);
    await page.getByRole("textbox", { name: "Confirm password" }).fill(password);
    await page.getByRole("button", { name: /create account/i }).click();
    await expect(page.getByText(/confirmation link/i)).toBeVisible();
    const res = await fetch(await confirmationLink(email), { redirect: "manual" });
    expect([302, 303]).toContain(res.status);
    await signIn(page);
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link")).toHaveText(
      [/Overview/, /Households/, /Fund Library/, /Documents/, /Review Queue/, /Liquidity Scenarios/, /Reports/, /Settings/],
    );
  });

  test("library fund: add, upload, review, approve", async ({ page }) => {
    await signIn(page);
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: /Fund Library/ }).click();
    await page.getByRole("button", { name: "Add fund" }).first().click();
    await page.getByLabel("Name").fill(fundName);
    await page.getByLabel("Fund type").last().selectOption("non_traded_reit");
    await page.locator('button[form="add-fund-form"]').click();
    await expect(page.getByRole("heading", { name: fundName })).toBeVisible();  // creation opens the fund

    await page.locator('input[type="file"]').setInputFiles(FIXTURE);
    await page.getByLabel("Effective date").first().fill("2026-01-01");
    await page.getByRole("button", { name: "Upload", exact: true }).click();
    // Let the browser finish sending the file before polling for extraction results.
    await expect(page.getByRole("cell", { name: /^(Queued|Processing|Extracted)$/ })).toBeVisible({ timeout: 60_000 });
    const approve = page.getByRole("button", { name: /^Approve .*monthly.*page 1$/i });
    await expect(async () => {
      await page.reload();
      await expect(approve).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 90_000 });
    await approve.click();
    await expect(page.getByRole("button", { name: /^Approve .*monthly.*page 1$/i })).toHaveCount(0);
  });

  test("household linked to the fund, scenario and blind-spot check", async ({ page }) => {
    await signIn(page);
    await page.goto("/households/new");
    await page.getByLabel("Household name").fill(`E2E household ${stamp}`);
    await page.getByRole("button", { name: "Create household" }).click();
    await page.waitForURL(/\/households\/[0-9a-f-]{36}/);
    const hid = page.url().match(/households\/([0-9a-f-]{36})/)![1];

    await page.goto(`/households/${hid}/profile`);
    const addButtons = page.getByRole("button", { name: /^Add/ });
    await addButtons.first().click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel(/kind/i).selectOption("non_traded_reit");
    await dialog.getByLabel("Name").fill("REIT position");
    await dialog.getByLabel(/amount/i).first().fill("400000");
    const fundSelect = dialog.getByLabel("Library fund");
    await expect(fundSelect.locator("option", { hasText: fundName })).toHaveCount(1);
    await fundSelect.selectOption({ label: fundName });
    await dialog.getByRole("button", { name: /^Add asset/i }).click();
    await expect(page.getByRole("link", { name: fundName })).toBeVisible();

    await page.goto(`/households/${hid}/scenarios/new`);
    await page.getByLabel("Name").first().fill("E2E stress");
    await page.getByRole("button", { name: /(create|save) scenario/i }).click();
    await page.waitForURL(new RegExp(`/households/${hid}/scenarios/[0-9a-f-]{36}$`));
    await page.getByRole("button", { name: "Run blind-spot check" }).click();
    await expect(page.getByText(/not a forecast/i).first()).toBeVisible();
    const comparison = page.getByRole("region", { name: "Scenario comparison" }).getByRole("table");
    await expect(comparison).toBeVisible();
    await expect(comparison.locator("tbody tr")).toHaveCount(8);  // baseline + 7 documented variants
  });

  test("review queue and overview load with real data", async ({ page }) => {
    await signIn(page);
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: /Review Queue/ }).click();
    await expect(page.getByRole("heading", { name: /review queue/i })).toBeVisible();
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: /Reports/ }).click();
    await expect(page.getByRole("heading", { name: "Reports", level: 1 })).toBeVisible();
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: /Overview/ }).click();
    await expect(page.getByText("Next action")).toBeVisible();
    await expect(page.getByText(`E2E household ${stamp}`).first()).toBeVisible();
  });
});
