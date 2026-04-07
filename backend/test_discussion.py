#!/usr/bin/env python3
"""Automated test for the discussion engine — no interactive input needed.

Tests:
1. Role model has goal field
2. Script generation produces goals for each role
3. LLMAdapter.generate_chat works with multi-message input
4. DiscussionEngine: responder selection, reply generation, context isolation
5. Full discussion flow: clue injection -> AI multi-round -> player input -> AI response -> end

Scoring: each test section is worth points, total 100.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback

from dotenv import load_dotenv
load_dotenv()

import openai
from langfuse.openai import AsyncOpenAI as LangfuseAsyncOpenAI
openai.AsyncOpenAI = LangfuseAsyncOpenAI  # type: ignore[misc]

from app.models.game import (
    Character, CharacterRoleMapping, ChatMessage, Clue,
    GamePhase, GameSession, MessageType, Role, RoleAlignment, Script, ScriptStyle, uid,
)
from app.llm.adapter import LLMAdapter
from app.generator.script_generator import generate_outline, STYLE_LABELS
from app.engine.discussion_engine import DiscussionEngine

# ── Scoring ──────────────────────────────────────────

scores: dict[str, tuple[int, int, str]] = {}  # name -> (earned, max, notes)

def record(name: str, earned: int, max_pts: int, notes: str = ""):
    scores[name] = (earned, max_pts, notes)
    status = "PASS" if earned == max_pts else ("PARTIAL" if earned > 0 else "FAIL")
    print(f"  [{status}] {name}: {earned}/{max_pts}" + (f" — {notes}" if notes else ""))


def print_report():
    print("\n" + "=" * 60)
    print("  DISCUSSION ENGINE TEST REPORT")
    print("=" * 60)
    total_earned = sum(v[0] for v in scores.values())
    total_max = sum(v[1] for v in scores.values())
    for name, (earned, max_pts, notes) in scores.items():
        status = "PASS" if earned == max_pts else ("PARTIAL" if earned > 0 else "FAIL")
        line = f"  [{status}] {name}: {earned}/{max_pts}"
        if notes:
            line += f" — {notes}"
        print(line)
    print("-" * 60)
    pct = (total_earned / total_max * 100) if total_max > 0 else 0
    print(f"  TOTAL: {total_earned}/{total_max} ({pct:.0f}%)")
    grade = "A" if pct >= 90 else "B" if pct >= 75 else "C" if pct >= 60 else "D" if pct >= 40 else "F"
    print(f"  GRADE: {grade}")
    print("=" * 60)


# ── Test fixtures ────────────────────────────────────

def make_test_session():
    """Create a minimal test session without LLM."""
    roles = [
        Role(id="r1", name="陈医生", alignment=RoleAlignment.INNOCENT,
             background="医院急诊科主任", secret="曾经误诊导致患者死亡",
             goal="查明真相洗清自己的嫌疑", clues=["死者生前来过急诊"]),
        Role(id="r2", name="王秘书", alignment=RoleAlignment.MURDERER,
             background="公司董事长秘书", secret="因被威胁泄露丑闻而杀人",
             goal="引导众人怀疑陈医生", clues=["董事长的日程表有异常"]),
        Role(id="r3", name="李记者", alignment=RoleAlignment.INNOCENT,
             background="调查记者", secret="正在暗中调查公司财务造假",
             goal="收集更多证据揭露公司黑幕", clues=["公司最近有大额资金转移"]),
        Role(id="r4", name="赵保安", alignment=RoleAlignment.INNOCENT,
             background="大楼保安队长", secret="当晚擅离职守去赌博",
             goal="隐瞒自己当晚不在岗的事实", clues=["监控在凌晨2点被关闭"]),
    ]
    characters = [
        Character(id="c1", name="张山", personality="正直认真"),
        Character(id="c2", name="酷鹅", personality="圆滑世故"),
        Character(id="c3", name="胡一菲", personality="热情好奇"),
        Character(id="c4", name="豆几", personality="憨厚老实"),
    ]
    mappings = [
        CharacterRoleMapping(character_id="c1", role_id="r1", is_player=True),
        CharacterRoleMapping(character_id="c2", role_id="r2", is_player=False),
        CharacterRoleMapping(character_id="c3", role_id="r3", is_player=False),
        CharacterRoleMapping(character_id="c4", role_id="r4", is_player=False),
    ]
    clues = [
        Clue(id="cl1", title="血迹", content="办公室地毯上有清洗过的血迹", act=1),
        Clue(id="cl2", title="通话记录", content="死者手机最后通话是给王秘书的", act=1),
    ]
    return characters, roles, mappings, clues


# ── Tests ────────────────────────────────────────────

async def test_1_role_goal_field():
    """Test: Role model has goal field and it works."""
    print("\n── Test 1: Role.goal field ──")
    try:
        r = Role(id="t", name="test", alignment=RoleAlignment.INNOCENT, goal="测试目标")
        assert r.goal == "测试目标", f"Expected '测试目标', got '{r.goal}'"
        r2 = Role(id="t2", name="test2", alignment=RoleAlignment.INNOCENT)
        assert r2.goal == "", f"Default should be '', got '{r2.goal}'"
        record("1. Role.goal field", 5, 5)
    except Exception as e:
        record("1. Role.goal field", 0, 5, str(e))


async def test_2_generate_chat():
    """Test: LLMAdapter.generate_chat works."""
    print("\n── Test 2: LLMAdapter.generate_chat ──")
    llm = LLMAdapter()
    try:
        result = await llm.generate_chat(
            messages=[
                {"role": "system", "content": "你是一个测试助手。只回复'OK'两个字。"},
                {"role": "user", "content": "测试"},
            ],
            max_tokens=50,
            temperature=0.1,
        )
        assert isinstance(result, str), f"Expected str, got {type(result)}"
        assert len(result) > 0, "Empty response"
        record("2. generate_chat API", 10, 10, f"response: '{result[:30]}'")
    except Exception as e:
        record("2. generate_chat API", 0, 10, str(e))


async def test_3_script_generation_with_goals():
    """Test: generate_outline produces roles with goal field."""
    print("\n── Test 3: Script generation with goals ──")
    llm = LLMAdapter()
    try:
        script, _ = await generate_outline(ScriptStyle.DETECTIVE, llm=llm)
        assert len(script.roles) == 4, f"Expected 4 roles, got {len(script.roles)}"
        goals_found = sum(1 for r in script.roles if r.goal)
        notes = f"title='{script.title}', goals: {goals_found}/4"
        for r in script.roles:
            notes += f"\n    {r.name}({r.alignment.value}): goal='{r.goal[:30]}'" if r.goal else f"\n    {r.name}: NO GOAL"
        if goals_found == 4:
            record("3. Script goals generation", 15, 15, notes)
        elif goals_found >= 2:
            record("3. Script goals generation", 10, 15, notes)
        elif goals_found >= 1:
            record("3. Script goals generation", 5, 15, notes)
        else:
            record("3. Script goals generation", 0, 15, notes)
        return script
    except Exception as e:
        record("3. Script goals generation", 0, 15, traceback.format_exc()[-200:])
        return None


async def test_4_context_isolation():
    """Test: _build_chat_messages produces correct context isolation."""
    print("\n── Test 4: Context isolation ──")
    characters, roles, mappings, clues = make_test_session()
    llm = LLMAdapter()
    engine = DiscussionEngine(characters, roles, mappings, "c1", llm)

    history = [
        ChatMessage(id="m1", type=MessageType.CHARACTER_SPEAK, sender_id="c2",
                    sender_name="酷鹅(王秘书)", content="我觉得这个线索很可疑"),
        ChatMessage(id="m2", type=MessageType.CHARACTER_SPEAK, sender_id="c3",
                    sender_name="胡一菲(李记者)", content="我同意，我们应该深入调查"),
        ChatMessage(id="m3", type=MessageType.PLAYER_SPEAK, sender_id="c1",
                    sender_name="张山(陈医生)", content="让我看看通话记录"),
    ]

    try:
        # From c2's perspective: own msg = assistant, others = user with <msg>
        msgs_c2 = engine._build_chat_messages("c2", history)
        assert msgs_c2[0]["role"] == "assistant", f"Own msg should be assistant, got {msgs_c2[0]['role']}"
        assert msgs_c2[1]["role"] == "user", f"Other msg should be user, got {msgs_c2[1]['role']}"
        assert '<msg from="' in msgs_c2[1]["content"], "Missing <msg from> tag"
        assert msgs_c2[2]["role"] == "user", "Player msg should be user for AI char"

        # From c1 (player) perspective: own msg = assistant
        msgs_c1 = engine._build_chat_messages("c1", history)
        assert msgs_c1[2]["role"] == "assistant", "Player's own msg should be assistant"
        assert msgs_c1[0]["role"] == "user", "Other msg should be user for player"

        record("4. Context isolation", 10, 10)
    except Exception as e:
        record("4. Context isolation", 0, 10, str(e))


async def test_5_responder_selection():
    """Test: _select_responders returns valid character ids."""
    print("\n── Test 5: Responder selection ──")
    characters, roles, mappings, clues = make_test_session()
    llm = LLMAdapter()
    engine = DiscussionEngine(characters, roles, mappings, "c1", llm)

    history = [
        ChatMessage(id="m1", type=MessageType.SYSTEM, sender_id="system",
                    sender_name="系统", content="发现线索：办公室地毯上有血迹"),
    ]

    try:
        selected = await engine._select_responders(
            history, trigger_sender="系统", trigger_message="发现线索：办公室地毯上有血迹",
        )
        assert isinstance(selected, list), f"Expected list, got {type(selected)}"
        valid_ids = {"c2", "c3", "c4"}
        all_valid = all(cid in valid_ids for cid in selected)
        assert all_valid, f"Selected invalid ids: {selected}"
        assert len(selected) > 0, "No responders selected"

        role_names = [engine._role_name(cid) for cid in selected]
        record("5. Responder selection", 15, 15, f"selected: {role_names}")
    except Exception as e:
        record("5. Responder selection", 0, 15, traceback.format_exc()[-200:])


async def test_6_reply_generation():
    """Test: _generate_reply produces in-character response."""
    print("\n── Test 6: Reply generation ──")
    characters, roles, mappings, clues = make_test_session()
    llm = LLMAdapter()
    engine = DiscussionEngine(characters, roles, mappings, "c1", llm,
                               script_context="剧本「午夜凶案」，当前：第一幕")

    history = [
        ChatMessage(id="m1", type=MessageType.SYSTEM, sender_id="system",
                    sender_name="系统", content="发现线索：死者手机最后通话是给王秘书的"),
        ChatMessage(id="m2", type=MessageType.PLAYER_SPEAK, sender_id="c1",
                    sender_name="张山(陈医生)", content="王秘书，你能解释一下那通电话吗？"),
    ]

    try:
        # c2 = 酷鹅 = 王秘书 (murderer) — should deflect
        reply = await engine._generate_reply("c2", history)
        assert isinstance(reply, str), f"Expected str, got {type(reply)}"
        assert len(reply) > 0, "Empty reply"
        assert len(reply) <= 200, f"Reply too long: {len(reply)} chars"
        # Check no leaked formatting
        has_prefix = reply.startswith("[") or reply.startswith("王秘书:")
        has_msg_tag = "<msg" in reply
        pts = 15
        notes = f"reply: '{reply}'"
        if has_prefix:
            pts -= 3
            notes += " [WARN: has name prefix]"
        if has_msg_tag:
            pts -= 3
            notes += " [WARN: has <msg> tag]"
        if len(reply) > 120:
            pts -= 2
            notes += " [WARN: too long]"
        record("6. Reply generation", max(0, pts), 15, notes)
    except Exception as e:
        record("6. Reply generation", 0, 15, traceback.format_exc()[-200:])


async def test_7_full_discussion_flow():
    """Test: run_discussion with simulated player input."""
    print("\n── Test 7: Full discussion flow ──")
    characters, roles, mappings, clues = make_test_session()
    llm = LLMAdapter()
    engine = DiscussionEngine(characters, roles, mappings, "c1", llm,
                               script_context="剧本「午夜凶案」，第一幕「发现」")

    messages_log: list[tuple[str, str, str]] = []

    def on_message(char_name: str, role_name: str, content: str):
        messages_log.append((char_name, role_name, content))
        print(f"    【{char_name}({role_name})】{content}")

    # Simulate: player sends 1 message then ends
    player_inputs = iter(["通话记录显示死者最后联系的是王秘书，这很可疑啊", ""])
    def get_input() -> str:
        return next(player_inputs, "")

    try:
        t0 = time.time()
        history = await engine.run_discussion(
            clues=clues,
            on_message=on_message,
            get_player_input=get_input,
        )
        elapsed = time.time() - t0

        pts = 0
        notes_parts = []

        # Check: got some AI messages
        ai_msgs = [m for m in history if m.type == MessageType.CHARACTER_SPEAK]
        if len(ai_msgs) >= 1:
            pts += 5
        notes_parts.append(f"AI msgs: {len(ai_msgs)}")

        # Check: messages are sequential (different senders)
        if len(ai_msgs) >= 2:
            senders = [m.sender_id for m in ai_msgs]
            # At least 2 different senders
            if len(set(senders)) >= 2:
                pts += 5
                notes_parts.append("multi-character OK")
            else:
                notes_parts.append("WARN: only 1 character spoke")

        # Check: player message is in history
        player_msgs = [m for m in history if m.type == MessageType.PLAYER_SPEAK]
        if len(player_msgs) == 1:
            pts += 5
            notes_parts.append("player msg recorded")
        else:
            notes_parts.append(f"WARN: player msgs = {len(player_msgs)}")

        # Check: clue system message at start
        sys_msgs = [m for m in history if m.type == MessageType.SYSTEM]
        if sys_msgs and "线索" in sys_msgs[0].content:
            pts += 3
            notes_parts.append("clue injection OK")

        # Check: AI responded after player message
        player_idx = next((i for i, m in enumerate(history) if m.type == MessageType.PLAYER_SPEAK), -1)
        post_player_ai = [m for m in history[player_idx+1:] if m.type == MessageType.CHARACTER_SPEAK] if player_idx >= 0 else []
        if post_player_ai:
            pts += 7
            notes_parts.append(f"AI responded to player: {len(post_player_ai)} msgs")
        else:
            notes_parts.append("WARN: no AI response after player")

        # Check: context isolation in generated messages (no <msg> tags in content)
        leaked = [m for m in ai_msgs if "<msg" in m.content]
        if not leaked:
            pts += 5
            notes_parts.append("no leaked tags")
        else:
            notes_parts.append(f"WARN: {len(leaked)} msgs with leaked <msg> tags")

        notes_parts.append(f"time: {elapsed:.1f}s")
        record("7. Full discussion flow", min(pts, 30), 30, "; ".join(notes_parts))

    except Exception as e:
        record("7. Full discussion flow", 0, 30, traceback.format_exc()[-300:])


# ── Main ─────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("  DISCUSSION ENGINE AUTOMATED TEST")
    print("=" * 60)

    await test_1_role_goal_field()
    await test_2_generate_chat()
    await test_3_script_generation_with_goals()
    await test_4_context_isolation()
    await test_5_responder_selection()
    await test_6_reply_generation()
    await test_7_full_discussion_flow()

    print_report()


if __name__ == "__main__":
    asyncio.run(main())
