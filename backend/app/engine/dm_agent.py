"""DM (Dungeon Master) agent – narrates, reacts, and drives the story."""
from __future__ import annotations

import time
from typing import Optional

from langfuse import observe

from app.llm.adapter import LLMAdapter, get_llm
from app.models.game import (
    Act,
    ChatMessage,
    GameSession,
    MessageType,
    uid,
)


def _msg(content: str, msg_type: MessageType = MessageType.DM_NARRATION) -> ChatMessage:
    return ChatMessage(
        id=uid(),
        type=msg_type,
        sender_id="dm",
        sender_name="DM",
        content=content,
        timestamp=time.time(),
    )


def _system_msg(content: str) -> ChatMessage:
    return ChatMessage(
        id=uid(),
        type=MessageType.SYSTEM,
        sender_id="system",
        sender_name="系统",
        content=content,
        timestamp=time.time(),
    )


class DMAgent:
    """Controls game pacing, narrates, and orchestrates character responses."""

    def __init__(self, llm: LLMAdapter | None = None):
        self.llm = llm or get_llm()

    # ── react to player ────────────────────────────────

    @observe(name="DM反应")
    async def react(
        self,
        player_message: str,
        context: list[ChatMessage],
        session: GameSession,
    ) -> list[ChatMessage]:
        """
        After the player speaks, the DM decides:
        - whether to comment
        - which AI characters should respond
        Returns a list of ChatMessages (DM + character prompts).
        """
        if not session.script:
            return [_msg("请先开始游戏。")]

        style_label = ""
        from app.generator.script_generator import STYLE_LABELS
        style_label = STYLE_LABELS.get(session.script.style, "")

        # figure out which characters are AI (not the player)
        ai_character_ids: list[str] = []
        ai_names: list[str] = []
        for m in session.mappings:
            if not m.is_player:
                ai_character_ids.append(m.character_id)
                for c in session.characters:
                    if c.id == m.character_id:
                        ai_names.append(c.name)

        recent = "\n".join(
            f"[{m.sender_name}]: {m.content}" for m in context[-8:]
        )

        system = f"""\
你是一场剧本杀游戏的DM。风格：{style_label}。
剧本：{session.script.title}
当前阶段：{session.phase.value}

AI角色：{', '.join(ai_names)}

你需要判断在玩家说完话后：
1. 你作为DM是否需要简短回应（引导、评论、推进剧情）
2. 哪些AI角色应该回应

请直接返回你的DM回应（1-2句话）。如果不需要DM回应就返回空字符串。
"""

        user = f"最近对话：\n{recent}\n\n玩家刚才说：{player_message}"

        messages: list[ChatMessage] = []
        try:
            dm_response = await self.llm.generate(system, user, log_name="DM反应")
            dm_response = dm_response.strip()
            if dm_response and dm_response != '""' and dm_response != "''":
                messages.append(_msg(dm_response))
        except Exception:
            pass

        return messages

    # ── clue reveal ────────────────────────────────────

    def reveal_clues(self, act: Act) -> list[ChatMessage]:
        """Create messages for revealing clues in an act."""
        messages: list[ChatMessage] = []
        for clue in act.clues:
            if not clue.revealed:
                clue.revealed = True
                messages.append(
                    ChatMessage(
                        id=uid(),
                        type=MessageType.CLUE,
                        sender_id="dm",
                        sender_name="DM",
                        content=f"【{clue.title}】{clue.content}",
                        timestamp=time.time(),
                    )
                )
        return messages

    # ── choice question ────────────────────────────────

    def present_choice(self, act: Act, index: int = 0) -> Optional[ChatMessage]:
        """Return a choice-question message if available."""
        if index < len(act.choices):
            q = act.choices[index]
            return ChatMessage(
                id=uid(),
                type=MessageType.CHOICE,
                sender_id="dm",
                sender_name="DM",
                content=q.question,
                choices=q,
                timestamp=time.time(),
            )
        return None

    # ── voting phase ───────────────────────────────────

    def start_vote(self, session: GameSession) -> ChatMessage:
        """Prompt the player to vote for the murderer."""
        if not session.script:
            return _msg("投票环节开始！请选出你认为的凶手。")
        names = [r.name for r in session.script.roles]
        return _msg(
            "经过三幕的调查，是时候做出最终判断了。"
            f"请从以下角色中选出凶手：{', '.join(names)}"
        )

    def resolve_vote(self, voted_role_id: str, session: GameSession) -> list[ChatMessage]:
        """Check the vote and produce ending messages."""
        if not session.script:
            return [_msg("游戏出错了。")]

        correct = voted_role_id == session.script.murderer_role_id

        voted_name = voted_role_id
        murderer_name = ""
        for r in session.script.roles:
            if r.id == voted_role_id:
                voted_name = r.name
            if r.id == session.script.murderer_role_id:
                murderer_name = r.name

        messages: list[ChatMessage] = []
        if correct:
            messages.append(_msg(f"🎉 正确！{voted_name}就是凶手！"))
        else:
            messages.append(_msg(f"❌ 很遗憾，{voted_name}不是凶手。真正的凶手是{murderer_name}。"))

        messages.append(_msg(f"【真相揭晓】\n{session.script.truth}"))
        messages.append(
            _system_msg(f"游戏结束！最终得分：{session.score}分")
        )
        return messages
