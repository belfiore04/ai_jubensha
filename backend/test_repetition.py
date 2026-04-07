"""Test script: reproduce character repetition problem and compare two solutions.

Usage: .venv/bin/python test_repetition.py
"""
from __future__ import annotations

import asyncio
import os
import time
from collections import Counter

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ── LLM clients ──────────────────────────────────────────────
CHAT_CLIENT = AsyncOpenAI(
    api_key=os.getenv("DISC_CHAT_API_KEY"),
    base_url=os.getenv("DISC_CHAT_BASE_URL"),
)
CHAT_MODEL = os.getenv("DISC_CHAT_MODEL", "deepseek-v3.2")

SELECTOR_CLIENT = AsyncOpenAI(
    api_key=os.getenv("DISC_SELECTOR_API_KEY"),
    base_url=os.getenv("DISC_SELECTOR_BASE_URL"),
)
SELECTOR_MODEL = os.getenv("DISC_SELECTOR_MODEL", "qwen-turbo")

TEMPERATURE = 0.8
MAX_TOKENS = 200

# ── Test character: 赵鹤年 (the one who will generate 5 replies) ──
CHAR_NAME = "赵鹤年"
CHAR_SYSTEM_BASE = """\
你正在参与一场剧本杀游戏的自由讨论环节。一桩发生在民国时期古宅中的谋杀案。

【你的角色】赵鹤年
【你的性格】沉稳老练、观察力敏锐的中年学者
【你的背景】古宅主人的老友，研究历史的大学教授，昨夜应邀来古宅做客
【你的秘密】你在书房偷看过主人的遗嘱，知道遗产分配方案
【你掌握的线索】
- 你昨晚11点在书房看到地上有泥脚印，但当时没声张
- 你闻到茶壶里有一股淡淡的杏仁味
- 你注意到管家今天换了一双新鞋

你是无辜的。你愿意分享线索帮助找出凶手，但你也有自己的秘密不想被发现。只说你确实知道的事，不编造信息。

<对话历史格式说明>
其他角色的消息以 <msg from="名字">内容</msg> 格式出现。
你之前说过的话以纯文本出现（role=assistant）。
</对话历史格式说明>

<严格规则>
1. 你只扮演「赵鹤年」，用 TA 的口吻说话
2. 回复简短自然，1-3句话，不超过80字
3. 你可以回应任何人的话，提出疑问，或分享你的看法
4. 【重要】只输出你要说的话，不要替其他角色说话
5. 【重要】不要加前缀如 [赵鹤年]: 或 <msg> 标签，直接输出纯文本
6. 【禁止】不要用括号描述动作，用语言表达情绪
7. 围绕你的隐藏目标行动，但不要直白地暴露目标本身
</严格规则>"""

# ── 12-message seed history (3 characters discussing a murder) ──

SEED_HISTORY: list[dict] = [
    {"sender": "林婉清", "content": "各位，昨晚的事大家都知道了吧？老宅主人陈先生被发现死在卧室，门窗紧锁。"},
    {"sender": "赵鹤年", "content": "我昨晚在书房待到很晚，大约十一点的时候，注意到地上有泥脚印。"},
    {"sender": "孙明远", "content": "泥脚印？书房离卧室可不远。赵教授你确定是泥脚印，不是别的什么痕迹？"},
    {"sender": "赵鹤年", "content": "我研究历史几十年，泥和墨的区别还是分得清的。那脚印不大，像是女人的鞋。"},
    {"sender": "林婉清", "content": "你这话什么意思？在场的女性就我一个。赵教授，你是在怀疑我吗？"},
    {"sender": "孙明远", "content": "别急着下结论。对了，我昨晚在厨房拿水喝，看到管家鬼鬼祟祟地往后院走。"},
    {"sender": "赵鹤年", "content": "说到管家，我今天注意到他换了一双新鞋。昨天他穿的那双呢？"},
    {"sender": "林婉清", "content": "管家换鞋？这确实可疑。还有，我今早闻了闻陈先生桌上的茶壶，有股奇怪的味道。"},
    {"sender": "孙明远", "content": "什么味道？该不会是毒吧？陈先生生前最爱喝那把紫砂壶泡的茶。"},
    {"sender": "赵鹤年", "content": "那股味道我也闻到了，淡淡的杏仁味。氰化物就是杏仁味的。"},
    {"sender": "林婉清", "content": "氰化物！那凶器可能就是那壶茶。问题是谁有机会下毒？"},
    {"sender": "孙明远", "content": "管家负责泡茶，他嫌疑最大。但也不能排除其他人趁机动手的可能。"},
]


# ── Helper: build context in current (baseline) format ──────

def build_context_baseline(history: list[dict], self_name: str) -> list[dict]:
    """Current engine format: history[-20:], self=assistant, others=user+<msg>."""
    result = []
    for msg in history[-20:]:
        if msg["sender"] == self_name:
            result.append({"role": "assistant", "content": msg["content"]})
        else:
            result.append({
                "role": "user",
                "content": f'<msg from="{msg["sender"]}">{msg["content"]}</msg>',
            })
    return result


# ── Helper: build context for Plan A (C+E) ─────────────────

def build_context_plan_a(history: list[dict], self_name: str) -> list[dict]:
    """Plan A: only keep last 2 of own assistant messages; drop older self msgs."""
    # Separate own vs others
    own_indices = [i for i, m in enumerate(history) if m["sender"] == self_name]
    # Only keep last 2 own messages
    keep_own = set(own_indices[-2:]) if len(own_indices) > 2 else set(own_indices)

    result = []
    for i, msg in enumerate(history[-20:]):
        global_i = len(history) - 20 + i if len(history) >= 20 else i
        if msg["sender"] == self_name:
            if global_i in keep_own:
                result.append({"role": "assistant", "content": msg["content"]})
            # else: drop this message entirely
        else:
            result.append({
                "role": "user",
                "content": f'<msg from="{msg["sender"]}">{msg["content"]}</msg>',
            })
    return result


# ── Helper: build context for Plan B (summary + 5-msg window) ──

async def build_context_plan_b(history: list[dict], self_name: str) -> list[dict]:
    """Plan B: summarize old msgs, keep last 5 as raw context."""
    recent = history[-5:]
    older = history[:-5] if len(history) > 5 else []

    result = []

    if older:
        # Summarize older messages using qwen-turbo
        lines = [f"[{m['sender']}]: {m['content']}" for m in older]
        text = "\n".join(lines)
        summary_prompt = (
            f"请用100字以内概括以下讨论的要点（包括关键线索、怀疑对象、已知事实）：\n\n{text}"
        )
        resp = await SELECTOR_CLIENT.chat.completions.create(
            model=SELECTOR_MODEL,
            messages=[{"role": "user", "content": summary_prompt}],
            max_tokens=150,
            temperature=0.3,
        )
        summary = resp.choices[0].message.content.strip()
        result.append({
            "role": "user",
            "content": f"[之前的讨论摘要] {summary}",
        })

    for msg in recent:
        if msg["sender"] == self_name:
            result.append({"role": "assistant", "content": msg["content"]})
        else:
            result.append({
                "role": "user",
                "content": f'<msg from="{msg["sender"]}">{msg["content"]}</msg>',
            })

    return result


# ── N-gram repetition metrics ───────────────────────────────

def _ngrams(text: str, n: int) -> list[str]:
    chars = list(text)
    return [("".join(chars[i:i+n])) for i in range(len(chars) - n + 1)]


def ngram_overlap(texts: list[str], n: int) -> float:
    """Average pairwise n-gram overlap ratio among a list of texts."""
    if len(texts) < 2:
        return 0.0
    overlaps = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            grams_a = Counter(_ngrams(texts[i], n))
            grams_b = Counter(_ngrams(texts[j], n))
            if not grams_a or not grams_b:
                overlaps.append(0.0)
                continue
            shared = sum((grams_a & grams_b).values())
            total = min(sum(grams_a.values()), sum(grams_b.values()))
            overlaps.append(shared / total if total else 0.0)
    return sum(overlaps) / len(overlaps)


# ── LLM call ────────────────────────────────────────────────

async def generate_reply(system_prompt: str, chat_messages: list[dict]) -> str:
    messages = [{"role": "system", "content": system_prompt}] + chat_messages
    resp = await CHAT_CLIENT.chat.completions.create(
        model=CHAT_MODEL,
        messages=messages,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
    )
    return resp.choices[0].message.content.strip()


# ── Phase 0: Reproduce repetition ──────────────────────────

async def phase_0_baseline():
    print("\n" + "=" * 70)
    print("Phase 0: 复现重复问题 (当前 baseline)")
    print("=" * 70)

    history = [dict(m) for m in SEED_HISTORY]
    replies = []

    for turn in range(5):
        ctx = build_context_baseline(history, CHAR_NAME)
        reply = await generate_reply(CHAR_SYSTEM_BASE, ctx)
        replies.append(reply)
        print(f"\n  Turn {turn+1}: {reply}")

        # Append this reply to history for next turn
        history.append({"sender": CHAR_NAME, "content": reply})

    bi = ngram_overlap(replies, 2)
    tri = ngram_overlap(replies, 3)
    print(f"\n  >> Bigram 重复率: {bi:.2%}")
    print(f"  >> Trigram 重复率: {tri:.2%}")
    return bi, tri, replies


# ── Phase 1: Plan A (C+E) ──────────────────────────────────

async def phase_1_plan_a():
    print("\n" + "=" * 70)
    print("Phase 1: 方案A — 系统提示词增强 + 限制自身 assistant 消息")
    print("=" * 70)

    anti_repeat_rule = (
        "\n8. 【重要】每次发言必须带来新信息、新疑问或新观点。"
        "绝对不要重复你或别人已经说过的内容，哪怕换个说法也不行。"
    )
    system_prompt = CHAR_SYSTEM_BASE + anti_repeat_rule

    history = [dict(m) for m in SEED_HISTORY]
    replies = []

    for turn in range(5):
        ctx = build_context_plan_a(history, CHAR_NAME)
        reply = await generate_reply(system_prompt, ctx)
        replies.append(reply)
        print(f"\n  Turn {turn+1}: {reply}")

        history.append({"sender": CHAR_NAME, "content": reply})

    bi = ngram_overlap(replies, 2)
    tri = ngram_overlap(replies, 3)
    print(f"\n  >> Bigram 重复率: {bi:.2%}")
    print(f"  >> Trigram 重复率: {tri:.2%}")
    return bi, tri, replies


# ── Phase 2: Plan B (summary + 5-msg window) ───────────────

async def phase_2_plan_b():
    print("\n" + "=" * 70)
    print("Phase 2: 方案B — 概括 + 5条滑窗")
    print("=" * 70)

    history = [dict(m) for m in SEED_HISTORY]
    replies = []

    for turn in range(5):
        ctx = await build_context_plan_b(history, CHAR_NAME)
        reply = await generate_reply(CHAR_SYSTEM_BASE, ctx)
        replies.append(reply)
        print(f"\n  Turn {turn+1}: {reply}")

        history.append({"sender": CHAR_NAME, "content": reply})

    bi = ngram_overlap(replies, 2)
    tri = ngram_overlap(replies, 3)
    print(f"\n  >> Bigram 重复率: {bi:.2%}")
    print(f"  >> Trigram 重复率: {tri:.2%}")
    return bi, tri, replies


# ── Scoring ─────────────────────────────────────────────────

def score(bi: float, tri: float) -> int:
    """0-100 score: lower repetition = higher score."""
    # Weighted: trigram matters more (it's more obviously repetitive)
    raw = 1.0 - (0.3 * bi + 0.7 * tri)
    return max(0, min(100, int(raw * 100)))


# ── Main ────────────────────────────────────────────────────

async def main():
    print("=" * 70)
    print("剧本杀角色重复说话测试")
    print(f"角色: {CHAR_NAME} | 模型: {CHAT_MODEL} | 温度: {TEMPERATURE}")
    print(f"每个方案连续生成 5 次回复，检测 n-gram 重复率")
    print("=" * 70)

    t0 = time.time()

    bi0, tri0, r0 = await phase_0_baseline()
    bi1, tri1, r1 = await phase_1_plan_a()
    bi2, tri2, r2 = await phase_2_plan_b()

    elapsed = time.time() - t0

    # ── Final comparison ──
    s0, s1, s2 = score(bi0, tri0), score(bi1, tri1), score(bi2, tri2)

    print("\n" + "=" * 70)
    print("最终对比")
    print("=" * 70)
    print(f"{'方案':<25} {'Bigram重复':>12} {'Trigram重复':>12} {'得分':>8}")
    print("-" * 60)
    print(f"{'Baseline (当前)':.<25} {bi0:>11.2%} {tri0:>11.2%} {s0:>7}/100")
    print(f"{'方案A (C+E)':.<25} {bi1:>11.2%} {tri1:>11.2%} {s1:>7}/100")
    print(f"{'方案B (概括+滑窗)':.<25} {bi2:>11.2%} {tri2:>11.2%} {s2:>7}/100")
    print(f"\n耗时: {elapsed:.1f}s")

    # ── Determine winner ──
    best = max([(s0, "Baseline"), (s1, "方案A"), (s2, "方案B")], key=lambda x: x[0])
    print(f"\n最佳方案: {best[1]} ({best[0]}/100)")


if __name__ == "__main__":
    asyncio.run(main())
