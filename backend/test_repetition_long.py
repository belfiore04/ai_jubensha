"""Long multi-character discussion test: reproduce repetition and compare solutions.

Simulates a realistic 3-character murder mystery discussion over 15 rounds.
Characters take turns speaking (A -> B -> C -> A -> ...) to reproduce the
repetition problem and evaluate two mitigation strategies.

Usage: .venv/bin/python test_repetition_long.py
"""
from __future__ import annotations

import asyncio
import os
import re
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
NUM_ROUNDS = 15

# ── Character definitions ────────────────────────────────────

CHARACTERS = {
    "赵鹤年": {
        "personality": "沉稳老练、细心谨慎的老管家",
        "background": "沈家老管家，侍奉沈家三十年，对宅中一切了如指掌",
        "secret": "你在案发当晚偷偷清洗了茶壶，因为你发现茶壶里有异味，担心被牵连",
        "alignment": "innocent",
        "clues": [
            "案发当晚你去书房送茶，发现沈明远已经倒在桌前",
            "你清洗茶壶时注意到壶内有白色粉末残留",
            "你听到苏曼华在案发前一小时和沈明远激烈争吵",
        ],
        "goal": "隐藏你清洗茶壶的事实，同时帮助找出真凶",
    },
    "苏曼华": {
        "personality": "优雅端庄但内心焦虑的少妇",
        "background": "沈明远的妻子，嫁入沈家五年，婚姻名存实亡",
        "secret": "你用砒霜毒死了沈明远，动机是一份价值百万的人寿保险",
        "alignment": "murderer",
        "clues": [
            "你知道沈明远有严重的心脏病，长期服药",
            "你在丈夫的书桌抽屉里发现了一封寄给律师的信，内容是要更改遗嘱",
            "你看到纪云舟深夜出现在书房附近",
        ],
        "goal": "把嫌疑引向纪云舟或赵鹤年，绝不能暴露保险动机",
    },
    "纪云舟": {
        "personality": "年轻气盛、正直但冲动的青年",
        "background": "沈明远的徒弟，学习古董鉴定三年，视师父如父",
        "secret": "你知道沈明远和一个叫黄老三的人有大笔债务纠纷，黄老三曾威胁过沈明远",
        "alignment": "innocent",
        "clues": [
            "你前天晚上在古董店看到黄老三来找沈明远，两人大吵一架",
            "你在书房发现一张借条，沈明远欠黄老三三十万",
            "案发当晚你去书房想借一本参考书，发现门虚掩着但没进去",
        ],
        "goal": "揭露黄老三的威胁，同时隐藏你深夜出现在书房附近的事实",
    },
}

# Turn order: rotate through characters
TURN_ORDER = ["赵鹤年", "苏曼华", "纪云舟"]

# ── Initial context (scene description) ─────────────────────

SCENE_CONTEXT = "一桩发生在沈家老宅的谋杀案。死者沈明远，知名古董商人，被发现毒死在书房。桌上有一只茶杯，茶壶已被清洗干净，书房门没有上锁。"

# ── Seed history (opening 3 messages, one per character) ─────

SEED_HISTORY: list[dict] = [
    {"sender": "系统", "content": "各位，沈明远先生被发现死在书房，初步判断是中毒身亡。请各位回忆昨晚的情况，配合调查。"},
    {"sender": "赵鹤年", "content": "老爷昨晚让我九点送茶到书房，我送完茶就回房了。没想到今早发现老爷已经……"},
    {"sender": "苏曼华", "content": "我昨晚一直在卧室，十点左右听到书房方向有响动，但没在意。明远他最近身体不好，我以为他早睡了。"},
    {"sender": "纪云舟", "content": "师父前几天心情很不好，好像跟什么人闹了不愉快。我本想昨晚去找师父聊聊，但看到书房门虚掩着就没进去。"},
]


# ── System prompt builder ────────────────────────────────────

def build_system_prompt(char_name: str, extra_rules: str = "") -> str:
    """Build system prompt following discussion_engine._build_system_prompt format."""
    char = CHARACTERS[char_name]

    if char["alignment"] == "murderer":
        alignment_hint = (
            "你是凶手，但绝不能暴露自己。你的策略：\n"
            "- 主动把话题引向其他嫌疑人，制造合理怀疑\n"
            "- 对指向你的证据轻描淡写地解释\n"
            "- 偶尔分享无关紧要的真实信息来建立信任\n"
            "- 表现得像积极参与推理的无辜者"
        )
    else:
        alignment_hint = (
            "你是无辜的。你愿意分享线索帮助找出凶手，"
            "但你也有自己的秘密不想被发现。只说你确实知道的事，不编造信息。"
        )

    clues_text = "\n".join(f"- {c}" for c in char["clues"])
    goal_text = f"\n【你的隐藏目标】{char['goal']}"

    prompt = f"""\
你正在参与一场剧本杀游戏的自由讨论环节。{SCENE_CONTEXT}

【你的角色】{char_name}
【你的性格】{char['personality']}
【你的背景】{char['background']}
【你的秘密】{char['secret']}{goal_text}
【你掌握的线索】
{clues_text}

{alignment_hint}

<对话历史格式说明>
其他角色的消息以 <msg from="名字">内容</msg> 格式出现。
你之前说过的话以纯文本出现（role=assistant）。
</对话历史格式说明>

<严格规则>
1. 你只扮演「{char_name}」，用 TA 的口吻说话
2. 回复简短自然，1-3句话，不超过80字
3. 你可以回应任何人的话，提出疑问，或分享你的看法
4. 【重要】只输出你要说的话，不要替其他角色说话
5. 【重要】不要加前缀如 [{char_name}]: 或 <msg> 标签，直接输出纯文本
6. 【禁止】不要用括号描述动作，用语言表达情绪
7. 围绕你的隐藏目标行动，但不要直白地暴露目标本身
</严格规则>{extra_rules}"""
    return prompt


# ── Context builders ─────────────────────────────────────────

def build_context_baseline(history: list[dict], self_name: str) -> list[dict]:
    """Baseline: history[-20:], self=assistant, others=user+<msg>."""
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


def build_context_plan_a(history: list[dict], self_name: str) -> list[dict]:
    """Plan A: keep last 3 own assistant msgs; older own msgs become user msgs."""
    # Find indices of own messages in the full history
    own_indices = [i for i, m in enumerate(history) if m["sender"] == self_name]
    # Only the last 3 remain as assistant
    keep_as_assistant = set(own_indices[-3:]) if len(own_indices) > 3 else set(own_indices)

    result = []
    window = history[-20:]
    offset = max(0, len(history) - 20)
    for i, msg in enumerate(window):
        global_i = offset + i
        if msg["sender"] == self_name:
            if global_i in keep_as_assistant:
                result.append({"role": "assistant", "content": msg["content"]})
            else:
                # Convert older own messages to user msg so model still sees them
                # but doesn't treat them as its own pattern to repeat
                result.append({
                    "role": "user",
                    "content": f'<msg from="你之前说">{msg["content"]}</msg>',
                })
        else:
            result.append({
                "role": "user",
                "content": f'<msg from="{msg["sender"]}">{msg["content"]}</msg>',
            })
    return result


async def build_context_plan_b(history: list[dict], self_name: str) -> list[dict]:
    """Plan B: summarize old msgs, keep last 5 as raw context."""
    recent = history[-5:]
    older = history[:-5] if len(history) > 5 else []

    result = []

    if older:
        lines = [f"[{m['sender']}]: {m['content']}" for m in older]
        text = "\n".join(lines)
        summary_prompt = (
            f"请用100字以内概括以下剧本杀讨论的要点（包括关键线索、怀疑对象、各角色立场）：\n\n{text}"
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
            "content": f"[讨论摘要] {summary}",
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


# ── Post-processing (mirrors discussion_engine) ─────────────

def clean_response(text: str) -> str:
    text = re.sub(r'\*[^*]+\*', '', text)
    text = re.sub(r'[（(][^）)]{1,10}[）)]', '', text)
    text = re.sub(r'^#+\s+.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'^[-*]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{2,}', '\n', text)
    return text.strip()


def post_process_reply(reply: str, char_name: str) -> str:
    all_names = list(CHARACTERS.keys()) + ["系统"]
    reply = re.sub(r'^\[?' + re.escape(char_name) + r'\]?\s*[:：]\s*', '', reply)
    for name in all_names:
        reply = re.sub(r'<msg\s+from="' + re.escape(name) + r'">.*?</msg>', '', reply, flags=re.DOTALL)
    for name in all_names:
        reply = re.sub(r'^\[' + re.escape(name) + r'\]\s*[:：]\s*', '', reply, flags=re.MULTILINE)
    reply = clean_response(reply)
    return reply.strip()


# ── LLM call ─────────────────────────────────────────────────

async def generate_reply(system_prompt: str, chat_messages: list[dict]) -> str:
    messages = [{"role": "system", "content": system_prompt}] + chat_messages
    resp = await CHAT_CLIENT.chat.completions.create(
        model=CHAT_MODEL,
        messages=messages,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
    )
    raw = resp.choices[0].message.content.strip()
    return raw


# ── N-gram metrics ───────────────────────────────────────────

def _ngrams(text: str, n: int) -> list[str]:
    chars = list(text)
    return ["".join(chars[i:i + n]) for i in range(len(chars) - n + 1)]


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


def unique_keywords(texts: list[str]) -> int:
    """Count unique meaningful keywords (2+ char segments) across all texts."""
    # Simple keyword extraction: split on punctuation, keep 2+ char tokens
    all_kw = set()
    for t in texts:
        tokens = re.split(r'[，。！？、；：\u201c\u201d\u2018\u2019（）\s\n\r]+', t)
        for tok in tokens:
            if len(tok) >= 2:
                all_kw.add(tok)
    return len(all_kw)


def check_tag_leaks(texts: list[str]) -> int:
    """Count how many replies contain leaked <msg> tags."""
    count = 0
    for t in texts:
        if '<msg' in t or '</msg>' in t:
            count += 1
    return count


# ── Scoring ──────────────────────────────────────────────────

def compute_scores(
    all_replies: dict[str, list[str]],
) -> dict:
    """Compute per-character and aggregate scores.

    Returns dict with per-character metrics and totals.
    """
    char_metrics = {}
    total_bi = 0.0
    total_topics = 0
    total_leaks = 0
    n_chars = 0

    for name, replies in all_replies.items():
        if not replies:
            continue
        bi = ngram_overlap(replies, 2)
        topics = unique_keywords(replies)
        leaks = check_tag_leaks(replies)
        char_metrics[name] = {
            "bigram_overlap": bi,
            "topics": topics,
            "leaks": leaks,
            "num_replies": len(replies),
        }
        total_bi += bi
        total_topics += topics
        total_leaks += leaks
        n_chars += 1

    avg_bi = total_bi / n_chars if n_chars else 0
    # Score: lower repetition + more topics + fewer leaks = better
    # Repetition penalty: 0-60 points (0% overlap = 60, 100% = 0)
    rep_score = max(0, 60 * (1 - avg_bi))
    # Topic diversity bonus: 0-30 points (more topics = better, cap at 60 total)
    topic_score = min(30, total_topics * 0.5)
    # Leak penalty: -10 per leak
    leak_penalty = total_leaks * 10
    total_score = max(0, min(100, int(rep_score + topic_score - leak_penalty)))

    return {
        "per_char": char_metrics,
        "avg_bigram_overlap": avg_bi,
        "total_topics": total_topics,
        "total_leaks": total_leaks,
        "score": total_score,
    }


def print_scores(scores: dict) -> None:
    print()
    for name, m in scores["per_char"].items():
        print(f"  {name} 重复率: {m['bigram_overlap']:.1%}, 话题数: {m['topics']}, 回复数: {m['num_replies']}")
    print(f"  角色混乱(tag泄露): {scores['total_leaks']}次")
    print(f"  平均重复率: {scores['avg_bigram_overlap']:.1%}")
    print(f"  总话题多样性: {scores['total_topics']}")
    print(f"  总分: {scores['score']}/100")


# ── Phase 0: Baseline ────────────────────────────────────────

async def phase_0_baseline() -> dict:
    print("\n" + "=" * 70)
    print("Phase 0: 基线 (当前引擎逻辑: history[-20:], self=assistant)")
    print("=" * 70)

    history = [dict(m) for m in SEED_HISTORY]
    all_replies: dict[str, list[str]] = {name: [] for name in CHARACTERS}

    for turn in range(NUM_ROUNDS):
        char_name = TURN_ORDER[turn % len(TURN_ORDER)]
        system_prompt = build_system_prompt(char_name)
        ctx = build_context_baseline(history, char_name)
        raw_reply = await generate_reply(system_prompt, ctx)
        reply = post_process_reply(raw_reply, char_name)
        if not reply:
            reply = "……"

        all_replies[char_name].append(reply)
        print(f"  [{turn + 1:2d}] {char_name}: {reply}")

        history.append({"sender": char_name, "content": reply})

    scores = compute_scores(all_replies)
    print_scores(scores)
    return scores


# ── Phase 1: Plan A — prompt enhancement + limit assistant + soft cap ──

async def phase_1_plan_a() -> dict:
    print("\n" + "=" * 70)
    print("Phase 1: 方案A — 提示词+限制assistant(3条)+软上限")
    print("=" * 70)

    extra_rules = (
        "\n8. 【重要】每次发言必须带来新信息、新疑问或新观点。"
        "不要重复你或别人已经说过的话。如果没有新内容，就用一两个字回应即可。"
    )

    history = [dict(m) for m in SEED_HISTORY]
    all_replies: dict[str, list[str]] = {name: [] for name in CHARACTERS}

    for turn in range(NUM_ROUNDS):
        char_name = TURN_ORDER[turn % len(TURN_ORDER)]
        system_prompt = build_system_prompt(char_name, extra_rules=extra_rules)
        ctx = build_context_plan_a(history, char_name)
        raw_reply = await generate_reply(system_prompt, ctx)
        reply = post_process_reply(raw_reply, char_name)
        if not reply:
            reply = "……"

        all_replies[char_name].append(reply)
        print(f"  [{turn + 1:2d}] {char_name}: {reply}")

        history.append({"sender": char_name, "content": reply})

    scores = compute_scores(all_replies)
    print_scores(scores)
    return scores


# ── Phase 2: Plan B — summary + 5-msg sliding window ────────

async def phase_2_plan_b() -> dict:
    print("\n" + "=" * 70)
    print("Phase 2: 方案B — 概括+5条滑窗")
    print("=" * 70)

    history = [dict(m) for m in SEED_HISTORY]
    all_replies: dict[str, list[str]] = {name: [] for name in CHARACTERS}

    for turn in range(NUM_ROUNDS):
        char_name = TURN_ORDER[turn % len(TURN_ORDER)]
        system_prompt = build_system_prompt(char_name)
        ctx = await build_context_plan_b(history, char_name)
        raw_reply = await generate_reply(system_prompt, ctx)
        reply = post_process_reply(raw_reply, char_name)
        if not reply:
            reply = "……"

        all_replies[char_name].append(reply)
        print(f"  [{turn + 1:2d}] {char_name}: {reply}")

        history.append({"sender": char_name, "content": reply})

    scores = compute_scores(all_replies)
    print_scores(scores)
    return scores


# ── Main ─────────────────────────────────────────────────────

async def main():
    print("=" * 70)
    print("剧本杀多角色讨论重复测试 (长版)")
    print(f"角色: {', '.join(TURN_ORDER)}")
    print(f"模型: {CHAT_MODEL} | 温度: {TEMPERATURE} | 轮数: {NUM_ROUNDS}")
    print(f"场景: {SCENE_CONTEXT[:50]}...")
    print("=" * 70)

    t0 = time.time()

    s0 = await phase_0_baseline()
    s1 = await phase_1_plan_a()
    s2 = await phase_2_plan_b()

    elapsed = time.time() - t0

    # ── Final comparison table ──
    print("\n" + "=" * 70)
    print("最终对比")
    print("=" * 70)
    print(f"{'方案':<30} {'平均重复率':>10} {'话题多样性':>10} {'角色混乱':>8} {'总分':>8}")
    print("-" * 70)
    print(f"{'Baseline (当前引擎)':<30} {s0['avg_bigram_overlap']:>9.1%} {s0['total_topics']:>10} {s0['total_leaks']:>8} {s0['score']:>6}/100")
    print(f"{'方案A (提示词+限assistant)':<30} {s1['avg_bigram_overlap']:>9.1%} {s1['total_topics']:>10} {s1['total_leaks']:>8} {s1['score']:>6}/100")
    print(f"{'方案B (概括+5条滑窗)':<30} {s2['avg_bigram_overlap']:>9.1%} {s2['total_topics']:>10} {s2['total_leaks']:>8} {s2['score']:>6}/100")
    print(f"\n耗时: {elapsed:.1f}s")

    # ── Winner ──
    results = [(s0['score'], "Baseline"), (s1['score'], "方案A"), (s2['score'], "方案B")]
    results.sort(key=lambda x: x[0], reverse=True)
    print(f"\n排名:")
    for i, (sc, name) in enumerate(results, 1):
        print(f"  {i}. {name} ({sc}/100)")


if __name__ == "__main__":
    asyncio.run(main())
