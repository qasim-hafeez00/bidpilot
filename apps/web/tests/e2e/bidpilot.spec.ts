import { test, expect, type Page } from "@playwright/test";

// Runs against a live stack (make dev + make seed-demo). BASE_URL defaults to the Vite dev server.
const email = () => `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@bidpilot.dev`;
const REVIEWER = { email: process.env.E2E_EMAIL || "reviewer@bidpilot.dev", password: process.env.E2E_PASSWORD || "reviewer-pass-2026" };

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByTestId("email").fill(REVIEWER.email);
  await page.getByTestId("password").fill(REVIEWER.password);
  await page.getByTestId("submit").click();
  await expect(page).toHaveURL(/inbox/);
}

async function openPending(page: Page) {
  await page.goto("/inbox");
  await page.getByLabel("Filter by status").selectOption("awaiting_approval");
  const row = page.getByTestId("job-row").first();
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.getByRole("link", { name: "Review" }).click();
  await expect(page.getByTestId("dry-run")).toBeVisible();
}

test("onboarding: register, pick a persona, set budget", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("toggle-mode").click();
  await page.getByTestId("email").fill(email());
  await page.getByTestId("password").fill("a-long-password-1");
  await page.getByTestId("submit").click();
  await expect(page).toHaveURL(/onboarding/);
  await page.getByTestId("persona-data_analyst").check();
  await page.getByTestId("budget").fill("60");
  await page.getByTestId("finish-onboarding").click();
  await expect(page).toHaveURL(/inbox/);
  await expect(page.getByRole("heading", { name: "Job inbox" })).toBeVisible();
});

test("approve a proposal: dry-run preview then submit", async ({ page }) => {
  await signIn(page);
  await openPending(page);
  await expect(page.getByTestId("claim").first()).toBeVisible();
  await page.getByTestId("approve").click();
  await expect(page.getByTestId("run-timeline")).toBeVisible();
});

test("reject with a reason", async ({ page }) => {
  await signIn(page);
  await openPending(page);
  await page.getByTestId("reject").click();
  await expect(page.getByTestId("confirm-reject")).toBeDisabled();
  await page.getByTestId("reject-reason").fill("too generic for this client");
  await page.getByTestId("confirm-reject").click();
  await expect(page.getByTestId("run-timeline")).toBeVisible();
});

test("edit a draft: approve button switches to 'with my edits'", async ({ page }) => {
  await signIn(page);
  await openPending(page);
  await page.getByTestId("toggle-edit").click();
  const ed = page.getByTestId("editor");
  await ed.fill((await ed.inputValue()).replace(/^[^.]*\.\s*/, ""));
  await expect(page.getByTestId("approve")).toHaveText(/with my edits/);
});

test("degraded-mode banner when the marketplace is down", async ({ page }) => {
  await page.route("**/api/health/dependencies", (r) => r.fulfill({ json: { api: "up", marketplace: "down", details: {}, queued_degraded: 2 } }));
  await signIn(page);
  await expect(page.getByTestId("degraded-banner")).toContainText("Marketplace unavailable");
});
