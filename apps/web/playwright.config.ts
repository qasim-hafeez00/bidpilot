import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 90_000,
  reporter: [["html", { outputFolder: "playwright-report", open: "never" }], ["list"]],
  use: { baseURL: process.env.BASE_URL || "http://localhost:15173", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "phone", use: { ...devices["Pixel 7"] } },
  ],
});
