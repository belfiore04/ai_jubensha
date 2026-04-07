import { test, expect } from "@playwright/test";

/**
 * Test the REAL race condition:
 * 1. getGame initially returns phase="generating" with partial messages
 * 2. SSE delivers remaining messages including discussion
 * 3. Verify input becomes enabled
 */

const GAME_ID = "test-race-123";

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
    acts: [{
      act_number: 1, title: "第一幕", narration: "测试叙述",
      clues: [{ id: "clue-1", title: "线索1", content: "线索内容", act: 1 }],
      choices: [{ id: "q1", question: "测试问题", options: [{ id: "opt-1", text: "A", is_correct: true }, { id: "opt-2", text: "B", is_correct: false }], explanation: "解析" }],
      generated: true,
    }],
  },
  current_act: 1,
  act_answered: 0,
  score: 0,
  player_character_id: "char-zhangshan",
};

const allMessages = [
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

test.describe("Race condition: phase=generating + SSE messages", () => {

  test("Scenario A: getGame returns generating, all messages via SSE", async ({ page }) => {
    const consoleLogs: string[] = [];
    page.on("console", (msg) => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));

    let getGameCallCount = 0;

    // getGame: first call returns generating + no messages, later calls return act_1 + messages
    await page.route("**/api/game/test-race-123", async (route) => {
      getGameCallCount++;
      if (getGameCallCount === 1) {
        // First call: still generating, only the first message
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ...baseSession,
            phase: "generating",
            messages: [allMessages[0]], // just "游戏开始！正在生成第一幕……"
          }),
        });
      } else {
        // Subsequent calls: act_1 with all messages
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ...baseSession,
            phase: "act_1",
            messages: allMessages,
          }),
        });
      }
    });

    // SSE: deliver messages with delays to simulate real-time generation
    await page.route("**/api/game/test-race-123/stream", async (route) => {
      // Skip m1 (already in getGame), send rest
      const sseMessages = allMessages.slice(1);
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

    await page.route("**/api/game/test-race-123/debug", async (route) => {
      await route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: "event: ping\ndata: \n\n",
      });
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
    await page.waitForTimeout(1000);

    const inputDisabled = await page.locator(".input-field").isDisabled();
    const endDiscVisible = await page.locator(".end-discussion-btn").isVisible().catch(() => false);

    console.log(`\n=== Scenario A Results ===`);
    console.log(`getGame calls: ${getGameCallCount}`);
    console.log(`Input disabled: ${inputDisabled}`);
    console.log(`End discussion visible: ${endDiscVisible}`);

    await page.screenshot({ path: "/tmp/scenario-a.png", fullPage: true });

    expect(inputDisabled).toBe(false);
  });

  test("Scenario B: getGame returns generating, NO SSE refresh trigger", async ({ page }) => {
    /**
     * This simulates a bug scenario:
     * - getGame returns phase="generating" with messages including the "正在生成第" one
     * - SSE delivers all messages BUT the "自由讨论开始" refresh trigger doesn't fire
     *   because SSE messages are deduped (already in buffer from getGame)
     */
    const consoleLogs: string[] = [];
    page.on("console", (msg) => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));

    // getGame returns ALL messages with phase="generating"
    // This simulates: getGame runs WHILE start_game is running,
    // messages are pushed but phase hasn't flipped to act_1 yet
    await page.route("**/api/game/test-race-123", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...baseSession,
          phase: "generating",
          messages: allMessages, // ALL messages present
        }),
      });
    });

    // SSE: all messages come again, but they'll be deduped by the frontend
    await page.route("**/api/game/test-race-123/stream", async (route) => {
      const chunks = allMessages.map(
        (msg) => `event: message\ndata: ${JSON.stringify(msg)}\n\n`
      );
      chunks.push(`event: ping\ndata: \n\n`);
      await route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: chunks.join(""),
      });
    });

    await page.route("**/api/game/test-race-123/debug", async (route) => {
      await route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: "event: ping\ndata: \n\n",
      });
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
    await page.waitForTimeout(1000);

    const inputDisabled = await page.locator(".input-field").isDisabled();
    const endDiscVisible = await page.locator(".end-discussion-btn").isVisible().catch(() => false);

    console.log(`\n=== Scenario B Results (worst case) ===`);
    console.log(`Input disabled: ${inputDisabled}`);
    console.log(`End discussion visible: ${endDiscVisible}`);

    await page.screenshot({ path: "/tmp/scenario-b.png", fullPage: true });

    // This is the scenario most likely to fail!
    expect(inputDisabled).toBe(false);
  });

  test("Scenario C: getGame returns generating, SSE messages deduped (no isThinking reset)", async ({ page }) => {
    /**
     * Worst case:
     * - getGame returns phase="generating" + ALL messages
     * - SSE messages are all deduped (already in buffer)
     * - isThinking never gets reset by SSE because messages are skipped
     * - isGenerating stays true because phase never refreshes
     */
    const consoleLogs: string[] = [];
    page.on("console", (msg) => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));

    // getGame returns ALL messages with phase="generating"
    await page.route("**/api/game/test-race-123", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...baseSession,
          phase: "generating",
          messages: allMessages,
        }),
      });
    });

    // SSE: NO messages arrive (they were all already in getGame response)
    await page.route("**/api/game/test-race-123/stream", async (route) => {
      // Only keepalives, no actual messages
      await route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: "event: ping\ndata: \n\n",
      });
    });

    await page.route("**/api/game/test-race-123/debug", async (route) => {
      await route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: "event: ping\ndata: \n\n",
      });
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
    await page.waitForTimeout(1000);

    const inputDisabled = await page.locator(".input-field").isDisabled();
    const endDiscVisible = await page.locator(".end-discussion-btn").isVisible().catch(() => false);

    console.log(`\n=== Scenario C Results (no SSE messages) ===`);
    console.log(`Input disabled: ${inputDisabled}`);
    console.log(`End discussion visible: ${endDiscVisible}`);

    await page.screenshot({ path: "/tmp/scenario-c.png", fullPage: true });

    expect(inputDisabled).toBe(false);
  });
});
