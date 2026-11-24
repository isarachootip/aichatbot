import { test, expect } from "@playwright/test";
import path from "path";

test("E2E smoke: signup -> upload Thai policy -> wait ready -> playground answer", async ({
  page,
}) => {
  const uniqueEmail = `e2e-${Date.now()}@thaishop.th`;

  // 1. Signup a brand-new 7-day trial shop
  await page.goto("/signup");
  await page.fill("#shop-name", "ร้านอีทูอีไทย");
  await page.fill("#signup-email", uniqueEmail);
  await page.getByRole("button", { name: "สร้างบัญชีและเริ่มใช้งาน" }).click();

  await expect(page).toHaveURL(/\/onboarding/);
  await expect(page.getByTestId("trial-banner")).toContainText("เหลืออีก");

  // 2. Navigate to /knowledge and upload a Thai policy fixture
  await page.goto("/knowledge");
  const fixturePath = path.resolve(
    __dirname,
    "../../backend/evals/fixtures/sample_thai_shop_policy.txt",
  );
  await page.getByTestId("document-file-input").setInputFiles(fixturePath);

  // Wait for ARQ worker ingestion to mark document as "พร้อมใช้งาน" (ready)
  await expect(page.getByTestId("document-row").first()).toContainText(
    "sample_thai_shop_policy.txt",
  );
  await expect(page.getByTestId("document-status").first()).toContainText("พร้อมใช้งาน", {
    timeout: 45_000,
  });

  // 3. Open /playground and ask a grounded Thai shipping question
  await page.goto("/playground");
  await page.getByTestId("playground-input").fill("ค่าจัดส่งกี่บาท ซื้อเท่าไหร่ส่งฟรีคะ");
  await page.getByTestId("playground-submit").click();

  // Verify grounded Thai answer renders with shipping fee / free threshold from the fixture
  const botReply = page.getByTestId("playground-bot-reply").first();
  await expect(botReply).toBeVisible({ timeout: 45_000 });
  const replyText = (await botReply.textContent()) || "";
  expect(replyText).toMatch(/40|500|ส่งฟรี|จัดส่ง/);
});
