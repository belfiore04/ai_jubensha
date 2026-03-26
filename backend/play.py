#!/usr/bin/env python3
"""Terminal-based murder mystery game — for tuning game flow and script quality."""
from __future__ import annotations

import asyncio
import sys

# Load env BEFORE any app imports (langfuse monkey-patch needs it)
from dotenv import load_dotenv
load_dotenv()

import openai
from langfuse.openai import AsyncOpenAI as LangfuseAsyncOpenAI
openai.AsyncOpenAI = LangfuseAsyncOpenAI  # type: ignore[misc]

from app.engine.game_engine import GameEngine, PLATFORM_CHARACTERS, _make_msg, _push
from app.generator.script_generator import generate_outline, generate_act, STYLE_LABELS
from app.llm.adapter import LLMAdapter
from app.logger import GameLogger, C
from app.models.game import (
    Act,
    CharacterRoleMapping,
    ChatMessage,
    GamePhase,
    GameSession,
    MessageType,
    RoleAlignment,
    ScriptStyle,
    uid,
)

import random
import uuid


# ── helpers ───────────────────────────────────────────

def input_choice(prompt: str, options: list[str]) -> int:
    """Show numbered options and get user choice. Returns 0-based index."""
    for i, opt in enumerate(options, 1):
        print(f"  {C.BOLD}{i}{C.RESET}. {opt}")
    while True:
        try:
            print(f"\n{prompt} > ", end="", flush=True)
            raw = input().strip()
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return idx
        except (ValueError, EOFError):
            pass
        print(f"  请输入 1-{len(options)} 的数字")


def input_text(prompt: str) -> str:
    """Get free text input. Empty string means skip."""
    try:
        # Print prompt separately to avoid ANSI codes in readline prompt
        # (ANSI in input() prompt breaks cursor positioning with CJK chars)
        print(prompt, end="", flush=True)
        return input().strip()
    except EOFError:
        return ""


# ── main game loop ────────────────────────────────────

async def main():
    game_id = uuid.uuid4().hex[:8]
    logger = GameLogger(game_id)

    # Create LLM with logger
    llm = LLMAdapter(logger=logger)

    print(f"\n{C.BOLD}{C.MAGENTA}{'═' * 40}{C.RESET}")
    print(f"{C.BOLD}{C.MAGENTA}   AI 剧本杀 — 终端 Demo{C.RESET}")
    print(f"{C.BOLD}{C.MAGENTA}{'═' * 40}{C.RESET}")

    # ── 1. Select style ──────────────────────────────
    logger.section("选择风格")
    styles = list(ScriptStyle)
    style_labels = [f"{STYLE_LABELS[s]}" for s in styles]
    style_idx = input_choice("选择风格", style_labels)
    style = styles[style_idx]
    logger.event("style_selected", style=style.value)

    # ── 2. Generate outline ──────────────────────────
    logger.section("生成剧本大纲")
    logger.system(f"风格: {STYLE_LABELS[style]}，正在生成...")
    try:
        script = await generate_outline(style, llm=llm)
    except Exception as e:
        logger.error(e, "大纲生成失败")
        return
    logger.event("outline_generated", title=script.title)
    logger.system(f"剧本「{script.title}」生成完成！")
    print(f"\n  {C.BOLD}剧本：{script.title}{C.RESET}")
    print(f"  {C.DIM}{script.prologue}{C.RESET}")

    # ── 3. Select role ───────────────────────────────
    logger.section("选择角色")
    role_labels = []
    for r in script.roles:
        tag = ""
        if r.alignment == RoleAlignment.MURDERER:
            tag = f" {C.DIM}(凶手 - 选了会被重分配){C.RESET}"
        role_labels.append(f"{r.name} — {r.background}{tag}")
    role_idx = input_choice("选择你要扮演的角色", role_labels)
    player_role = script.roles[role_idx]

    # If player picked murderer, reassign
    if player_role.alignment == RoleAlignment.MURDERER:
        for r in script.roles:
            if r.alignment == RoleAlignment.INNOCENT:
                player_role = r
                logger.system(f"凶手不能由玩家扮演，已自动分配为 {player_role.name}")
                break

    # Assign platform characters to roles
    player_char = PLATFORM_CHARACTERS[0]  # 张山 for player
    remaining_chars = list(PLATFORM_CHARACTERS[1:])
    remaining_roles = [r for r in script.roles if r.id != player_role.id]
    random.shuffle(remaining_chars)

    mappings = [
        CharacterRoleMapping(character_id=player_char.id, role_id=player_role.id, is_player=True)
    ]
    for i, role in enumerate(remaining_roles):
        mappings.append(
            CharacterRoleMapping(character_id=remaining_chars[i].id, role_id=role.id, is_player=False)
        )

    # Build session
    session = GameSession(
        id=game_id,
        phase=GamePhase.ACT_1,
        style=style,
        characters=list(PLATFORM_CHARACTERS),
        mappings=mappings,
        script=script,
        player_character_id=player_char.id,
    )

    # Print role assignments
    logger.section("角色分配")
    for m in mappings:
        char = next(c for c in session.characters if c.id == m.character_id)
        role = next(r for r in script.roles if r.id == m.role_id)
        tag = " ← 你" if m.is_player else ""
        align_tag = f" {C.RED}[凶手]{C.RESET}" if role.alignment == RoleAlignment.MURDERER else ""
        logger.system(f"{char.name} → {role.name}{align_tag}{tag}")
    logger.event("roles_assigned", mappings=[m.model_dump() for m in mappings])

    # ── 4. Prologue ──────────────────────────────────
    logger.section("序章")
    logger.dm_narration(script.prologue)

    # ── 5. Play 3 acts ───────────────────────────────
    engine = GameEngine(llm=llm)
    total_choices = 0
    score = 0

    for act_num in range(1, 4):
        act_label = {1: "一", 2: "二", 3: "三"}[act_num]
        logger.section(f"第{act_label}幕")

        # Generate act
        logger.system(f"正在生成第{act_label}幕...")
        try:
            prev_acts = [a for a in script.acts if a.generated]
            act = await generate_act(script, act_num, prev_acts, llm=llm)
            script.acts.append(act)
        except Exception as e:
            logger.error(e, f"第{act_num}幕生成失败")
            return
        logger.event("act_generated", act_number=act_num, title=act.title)

        # DM narration
        logger.dm_narration(f"【第{act_label}幕：{act.title}】\n{act.narration}")

        # Clues
        if act.clues:
            print()
            for clue in act.clues:
                logger.clue(f"【{clue.title}】{clue.content}")

        # ── Discussion phase ─────────────────────────
        logger.section(f"第{act_label}幕 — 自由讨论")
        print(f"\n  {C.DIM}角色们开始讨论线索。你可以随时输入发言参与讨论。{C.RESET}")
        print(f"  {C.DIM}按回车跳过/结束讨论。最多 3 轮。{C.RESET}\n")

        clue_text = "\n".join(f"- 【{cl.title}】{cl.content}" for cl in act.clues)
        discussion_history: list[ChatMessage] = []

        for round_num in range(1, 4):
            print(f"  {C.DIM}── 讨论轮次 {round_num} ──{C.RESET}")

            # AI characters speak concurrently
            ai_chars = [
                (m.character_id, next((c.name for c in session.characters if c.id == m.character_id), "?"))
                for m in mappings if not m.is_player
            ]

            async def _one_response(cid: str, char_name: str) -> tuple[str, str, str]:
                from app.engine.character_agent import CharacterAgent
                agent = CharacterAgent(cid, llm=llm)
                role = next((r for r in script.roles for m in mappings if m.character_id == cid and m.role_id == r.id), None)
                role_name = role.name if role else "?"
                text = await agent.respond(
                    context=discussion_history,
                    game_state=session,
                    mode="discuss",
                    clue_context=clue_text,
                )
                return char_name, role_name, text

            results = await asyncio.gather(*[_one_response(cid, name) for cid, name in ai_chars])

            for char_name, role_name, text in results:
                logger.character_speak(char_name, role_name, text)
                discussion_history.append(ChatMessage(
                    id=uid(), type=MessageType.CHARACTER_SPEAK,
                    sender_id=char_name, sender_name=f"{char_name}({role_name})",
                    content=text, timestamp=0,
                ))

            # Player input
            print()
            player_input = input_text(f"  {C.WHITE}{C.BOLD}> {C.RESET}")
            if player_input:
                role_name = player_role.name
                logger.player_speak(player_char.name, role_name, player_input)
                discussion_history.append(ChatMessage(
                    id=uid(), type=MessageType.PLAYER_SPEAK,
                    sender_id=player_char.id, sender_name=f"{player_char.name}({role_name})",
                    content=player_input, timestamp=0,
                ))
            else:
                # Empty input = end discussion
                if round_num < 3:
                    logger.system("讨论结束，进入选择题。")
                break

        logger.event("discussion_ended", act=act_num, rounds=round_num)

        # ── Choice questions ─────────────────────────
        if act.choices:
            logger.section(f"第{act_label}幕 — 选择题")
            for qi, q in enumerate(act.choices):
                total_choices += 1
                print(f"\n  {C.BOLD}问题 {qi + 1}：{q.question}{C.RESET}")
                option_labels = [opt.text for opt in q.options]
                ans_idx = input_choice("你的答案", option_labels)
                chosen = q.options[ans_idx]

                if chosen.is_correct:
                    score += 10
                    logger.choice_result(True, q.explanation, score)
                else:
                    logger.choice_result(False, q.explanation, score)
                logger.event("choice_answered", act=act_num, question=qi, correct=chosen.is_correct)

        session.current_act = act_num
        print()

    # ── 6. Voting ────────────────────────────────────
    logger.section("投票")
    logger.dm_narration("经过三幕的调查，是时候做出最终判断了。请选出你认为的凶手。")

    vote_options = [r for r in script.roles if r.id != player_role.id]
    vote_labels = [f"{r.name} — {r.background}" for r in vote_options]
    vote_idx = input_choice("你认为凶手是", vote_labels)
    voted_role = vote_options[vote_idx]
    logger.event("vote_cast", voted_role=voted_role.name)

    # ── 7. Ending ────────────────────────────────────
    logger.section("结局")
    murderer_role = next(r for r in script.roles if r.id == script.murderer_role_id)
    murderer_char = next(
        (next(c for c in session.characters if c.id == m.character_id)
         for m in mappings if m.role_id == script.murderer_role_id),
        None
    )

    if voted_role.id == script.murderer_role_id:
        logger.dm_narration(f"🎉 正确！{voted_role.name}就是凶手！")
    else:
        logger.dm_narration(
            f"❌ 很遗憾，{voted_role.name}不是凶手。"
            f"真正的凶手是{murderer_role.name}"
            f"（{murderer_char.name if murderer_char else '?'}扮演）。"
        )

    logger.dm_narration(f"【真相揭晓】\n{script.truth}")
    logger.system(f"最终得分：{score}/{total_choices * 10}")

    # ── 8. Summary ───────────────────────────────────
    logger.summary(score, total_choices)
    logger.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{C.DIM}游戏中断{C.RESET}")
        sys.exit(0)
