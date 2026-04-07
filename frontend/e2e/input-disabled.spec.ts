import { test, expect } from "@playwright/test";

/**
 * E2E test: verify the input field becomes enabled after discussion starts.
 *
 * Strategy: intercept all backend API calls and SSE streams with mock data
 * to simulate the exact game flow without needing real LLM calls.
 */

const GAME_ID = "test-game-123";

// Mock game session in different phases
const baseSession = {
  id: GAME_ID,
  style: "detective",
  characters: [
    { id: "char-zhangshan", name: "张山", avatar: "", personality: "豪爽", description: "厨师" },
    { id: "char-kue", name: "酷鹅", avatar: "", personality: "毒舌", description: "监护人" },
    { id: "char-huyifei", name: "胡一菲", avatar: "", personality: "彪悍", description: "教师" },
    { id: "char-bbbb", name: "豆几", avatar: "", personality: "搞怪", description: "爱豆" },
  ],
  mappings: [
    { character_id: "char-zhangshan", role_id: "role-1", is_player: true },
    { character_id: "char-kue", role_id: "role-2", is_player: false },
    { character_id: "char-huyifei", role_id: "role-3", is_player: false },
    { character_id: "char-bbbb", role_id: "role-4", is_player: false },
  ],
  script: {
    style: "detective",
    title: "测试剧本",
    prologue: "测试开场白",
    roles: [
      { id: "role-1", name: "林墨白", alignment: "innocent", background: "作家", secret: "秘密1", goal: "找真相", clues: [] },
      { id: "role-2", name: "苏晴", alignment: "murderer", background: "医生", secret: "秘密2", goal: "转移注意", clues: [] },
      { id: "role-3", name: "陈浩", alignment: "innocent", background: "律师", secret: "秘密3", goal: "保护自己", clues: [] },
      { id: "role-4", name: "王芳", alignment: "innocent", background: "学生", secret: "秘密4", goal: "找线索", clues: [] },
    ],
    truth: "测试真相",
    murderer_role_id: "role-2",
    acts: [
      {
        act_number: 1,
        title: "第一幕",
        narration: "测试叙述",
        clues: [{ id: "clue-1", title: "线索1", content: "线索内容", act: 1 }],
        choices: [
          {
            id: "q1",
            question: "测试问题",
            options: [
              { id: "opt-1", text: "选项A", is_correct: true },
              { id: "opt-2", text: "选项B", is_correct: false },
            ],
            explanation: "解析",
          },
        ],
        generated: true,
      },
    ],
  },
  messages: [],
  current_act: 1,
  act_answered: 0,
  score: 0,
  player_character_id: "char-zhangshan",
};

// SSE messages that the backend would push
const sseMessages = [
  { id: "m1", type: "system", sender_id: "system", sender_name: "系统", content: "游戏开始！正在生成第一幕……", choices: null, timestamp: 1 },
  { id: "m2", type: "dm_narration", sender_id: "dm", sender_name: "DM", content: "测试开场白", choices: null, timestamp: 2 },
  { id: "m3", type: "dm_narration", sender_id: "dm", sender_name: "DM", content: "【第一幕：第一幕】\n测试叙述", choices: null, timestamp: 3 },
  { id: "m4", type: "clue", sender_id: "system", sender_name: "系统", content: "【线索：线索1】线索内容", choices: null, timestamp: 4 },
  { id: "m5", type: "system", sender_id: "system", sender_name: "系统", content: "自由讨论开始，角色们正在发表看法……", choices: null, timestamp: 5 },
  { id: "m6", type: "character_speak", sender_id: "char-kue", sender_name: "酷鹅", content: "这件事情很蹊跷啊", choices: null, timestamp: 6 },
  { id: "m7", type: "character_speak", sender_id: "char-huyifei", sender_name: "胡一菲", content: "我觉得需要仔细分析", choices: null, timestamp: 7 },
  { id: "m8", type: "character_speak", sender_id: "char-bbbb", sender_name: "豆几", content: "有没有人注意到那个线索？", choices: null, timestamp: 8 },
  { id: "m9", type: "system", sender_id: "system", sender_name: "系统", content: "角色们已发表看法。你可以自由发言参与讨论，或点击「结束讨论」进入推理环节。", choices: null, timestamp: 9 },
];

test.describe("InputBar disabled state during game flow", () => {
  test("input should be enabled after discussion starts", async ({ page }) => {
    // Collect console logs for debugging
    const consoleLogs: string[] = [];
    page.on("console", (msg) => {
      consoleLogs.push(`[${msg.type()}] ${msg.text()}`);
    });

    // ── Mock API routes ──────────────────────────
    // GET /api/game/:id — return session in act_1 phase
    await page.route("**/api/game/test-game-123", async (route) => {
      const sessionWithMessages = {
        ...baseSession,
        phase: "act_1",
        messages: sseMessages,
      };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(sessionWithMessages),
      });
    });

    // SSE stream — push messages one by one
    await page.route("**/api/game/test-game-123/stream", async (route) => {
      const chunks = sseMessages.map(
        (msg) => `event: message\ndata: ${JSON.stringify(msg)}\n\n`
      );
      // Add a keepalive at the end
      chunks.push(`event: ping\ndata: \n\n`);

      await route.fulfill({
        status: 200,
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
        },
        body: chunks.join(""),
      });
    });

    // Debug SSE — empty
    await page.route("**/api/game/test-game-123/debug", async (route) => {
      await route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: "event: ping\ndata: \n\n",
      });
    });

    // ── Navigate to game room ────────────────────
    await page.goto(`http://localhost:5173/game/${GAME_ID}`);

    // Wait for messages to load
    await page.waitForTimeout(2000);

    // ── Click through paced messages ─────────────
    // The auto-advance shows system + first DM (prologue).
    // We need to click "下一条" for: act narration, clue
    for (let i = 0; i < 10; i++) {
      const nextBtn = page.locator(".next-message-btn");
      if (await nextBtn.isVisible({ timeout: 500 }).catch(() => false)) {
        await nextBtn.click();
        await page.waitForTimeout(300);
      } else {
        break;
      }
    }

    // Wait for auto-advance to finish
    await page.waitForTimeout(1000);

    // ── Diagnose the input state ─────────────────
    const inputField = page.locator(".input-field");
    const sendBtn = page.locator(".send-btn");
    const endDiscBtn = page.locator(".end-discussion-btn");

    const inputDisabled = await inputField.isDisabled();
    const sendDisabled = await sendBtn.isDisabled();
    const endDiscVisible = await endDiscBtn.isVisible().catch(() => false);

    // Inject diagnostic script to read React state
    const diagnostics = await page.evaluate(() => {
      const inputEl = document.querySelector(".input-field") as HTMLInputElement;
      const sendEl = document.querySelector(".send-btn") as HTMLButtonElement;
      const endDiscEl = document.querySelector(".end-discussion-btn");
      return {
        inputDisabled: inputEl?.disabled,
        sendDisabled: sendEl?.disabled,
        endDiscExists: !!endDiscEl,
        visibleMessageCount: document.querySelectorAll(".chat-bubble, .msg-bubble, [class*='message'], [class*='chat']").length,
        bodyText: document.body.innerText.substring(0, 2000),
      };
    });

    console.log("=== DIAGNOSTICS ===");
    console.log("Input disabled:", inputDisabled);
    console.log("Send disabled:", sendDisabled);
    console.log("End discussion visible:", endDiscVisible);
    console.log("Diagnostics:", JSON.stringify(diagnostics, null, 2));
    console.log("Console logs:", consoleLogs.slice(-20).join("\n"));

    // The actual assertion
    expect(inputDisabled).toBe(false);
    expect(endDiscVisible).toBe(true);
  });

  test("diagnose which condition disables input", async ({ page }) => {
    // This test injects a console.log to show exactly which condition is true

    // Mock routes (same as above)
    await page.route("**/api/game/test-game-123", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...baseSession, phase: "act_1", messages: sseMessages }),
      });
    });

    await page.route("**/api/game/test-game-123/stream", async (route) => {
      const chunks = sseMessages.map(
        (msg) => `event: message\ndata: ${JSON.stringify(msg)}\n\n`
      );
      chunks.push(`event: ping\ndata: \n\n`);
      await route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: chunks.join(""),
      });
    });

    await page.route("**/api/game/test-game-123/debug", async (route) => {
      await route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: "event: ping\ndata: \n\n",
      });
    });

    // Add a script to monitor the disabled state
    await page.addInitScript(() => {
      // Patch React's setState to log isThinking changes
      const origSetInterval = window.setInterval;
      origSetInterval(() => {
        const input = document.querySelector(".input-field") as HTMLInputElement;
        if (input) {
          console.log(`[MONITOR] input.disabled=${input.disabled}`);
        }
      }, 500);
    });

    const consoleLogs: string[] = [];
    page.on("console", (msg) => {
      consoleLogs.push(`[${msg.type()}] ${msg.text()}`);
    });

    await page.goto(`http://localhost:5173/game/${GAME_ID}`);
    await page.waitForTimeout(2000);

    // Click through paced messages
    for (let i = 0; i < 10; i++) {
      const nextBtn = page.locator(".next-message-btn");
      if (await nextBtn.isVisible({ timeout: 500 }).catch(() => false)) {
        await nextBtn.click();
        await page.waitForTimeout(300);
      } else {
        break;
      }
    }

    await page.waitForTimeout(1500);

    // Check all monitor logs
    const monitorLogs = consoleLogs.filter((l) => l.includes("[MONITOR]"));
    console.log("=== MONITOR LOGS ===");
    monitorLogs.forEach((l) => console.log(l));

    // Final state
    const inputDisabled = await page.locator(".input-field").isDisabled();
    console.log("FINAL input disabled:", inputDisabled);

    // Take screenshot for visual inspection
    await page.screenshot({ path: "/tmp/game-input-state.png", fullPage: true });
    console.log("Screenshot saved to /tmp/game-input-state.png");

    expect(inputDisabled).toBe(false);
  });
});
