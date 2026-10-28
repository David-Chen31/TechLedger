import { expect, test } from "@playwright/test";

test("source registry, retrieval modes and evaluation page", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "让技术选型有证据，能复核。" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "来源登记" })).toBeVisible();

  await page.getByRole("button", { name: "LangGraph 文档" }).click();
  await page.getByRole("button", { name: "登记来源" }).click();
  await expect(page.getByText("docs.langchain.com").first()).toBeVisible();

  await page.getByLabel("检索模式").selectOption("hybrid");
  await page.getByLabel("检索问题").fill("durable execution");
  await page.getByRole("button", { name: "搜索证据" }).click();
  await expect(page.getByRole("heading", { name: "技术调研" })).toBeVisible();

  await page.getByRole("button", { name: "运行评测" }).click();
  await expect(page.getByText("模式 hybrid · 用例 0 条")).toBeVisible();
});
