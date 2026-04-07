import { test, expect } from "@playwright/test";

/**
 * Real E2E test — goes through the actual game flow using the real backend.
 * Requires: backend running on :8000, frontend on :5173
 */

test.describe("Real game flow — input disabled bug", () => {
  test("full flow: style → role → game room → input enabled after discussion", async ({ page }) => {
    test.setTimeout(180_000); // 3 minutes for LLM calls

    const consoleLogs: string[] = [];
    page.on("console", (msg) => {
      const text = msg.text();
      consoleLogs.push(`[${msg.type()}] ${text}`);
      // Print disabled-related logs immediately
      if (text.includes("InputBar") || text.includes("DISABLED") || text.includes("MONITOR")) {
        console.log(`  >> ${text}`);
      }
    });

    // Step 1: Go to style select page
    await page.goto("http://localhost:5173/style");
    await page.waitForTimeout(1000);

    // Step 2: Click first style card
    const styleCard = page.locator(".style-card").first();
    await expect(styleCard).toBeVisible({ timeout: 5000 });
    await styleCard.click();
    await page.waitForTimeout(500);

    // Step 3: Wait for outline generation + navigate to role select
    // The app should auto-navigate after style is set
    await page.waitForURL("**/roles**", { timeout: 120_000 });
    console.log("✓ Reached role select page");

    // Step 4: Wait for roles to appear (outline generation)
    const roleCard = page.locator(".character-card").first();
    await expect(roleCard).toBeVisible({ timeout: 120_000 });
    console.log("✓ Roles loaded");

    // Step 5: Select first role
    await roleCard.click();
    await page.waitForTimeout(300);

    // Step 6: Click start game
    const startBtn = page.locator(".start-btn");
    await expect(startBtn).toBeEnabled({ timeout: 5000 });
    await startBtn.click();

    // Step 7: Should navigate to game room
    await page.waitForURL("**/game/**", { timeout: 10_000 });
    console.log("✓ Reached game room");

    // Step 8: Wait for discussion messages (character_speak or "已发表看法")
    console.log("Waiting for discussion messages to arrive...");
    try {
      await page.waitForFunction(
        () => document.body.innerText.includes("已发表看法") ||
              document.body.innerText.includes("结束讨论"),
        { timeout: 150_000 }
      );
      console.log("✓ Discussion messages arrived");
    } catch {
      console.log("✗ Timed out waiting for discussion");
    }

    await page.waitForTimeout(2000);

    // Step 9: Click through ALL paced messages
    let clickCount = 0;
    for (let i = 0; i < 30; i++) {
      const nextBtn = page.locator(".next-message-btn");
      if (await nextBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
        await nextBtn.click();
        clickCount++;
        await page.waitForTimeout(400);
      } else {
        break;
      }
    }
    console.log(`✓ Clicked "下一条" ${clickCount} times`);

    await page.waitForTimeout(1000);

    // Step 11: Check input state
    const inputField = page.locator(".input-field");
    const endDiscBtn = page.locator(".end-discussion-btn");

    const inputExists = await inputField.isVisible({ timeout: 5000 }).catch(() => false);
    const inputDisabled = inputExists ? await inputField.isDisabled() : null;
    const endDiscVisible = await endDiscBtn.isVisible().catch(() => false);

    console.log("\n=== FINAL STATE ===");
    console.log(`Input exists: ${inputExists}`);
    console.log(`Input disabled: ${inputDisabled}`);
    console.log(`End discussion visible: ${endDiscVisible}`);

    // Print all disabled-related console logs
    const disabledLogs = consoleLogs.filter(l => l.includes("DISABLED") || l.includes("InputBar"));
    if (disabledLogs.length > 0) {
      console.log("\n=== DISABLED LOGS ===");
      disabledLogs.forEach(l => console.log(l));
    }

    // Take screenshot
    await page.screenshot({ path: "/tmp/real-flow-final.png", fullPage: true });
    console.log("Screenshot: /tmp/real-flow-final.png");

    // Assert
    expect(inputDisabled).toBe(false);
  });
});
