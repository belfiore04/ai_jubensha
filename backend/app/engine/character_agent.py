"""Character agent – gives each AI character a voice."""
from __future__ import annotations

from langfuse import observe

from app.llm.adapter import LLMAdapter, get_llm
from app.models.game import (
    ChatMessage,
    GameSession,
    Role,
    RoleAlignment,
    Character,
    CharacterRoleMapping,
)


def _find_role_for_character(
    character_id: str,
    session: GameSession,
) -> Role | None:
    """Look up the Role assigned to a character."""
    for m in session.mappings:
        if m.character_id == character_id:
            if session.script:
                for r in session.script.roles:
                    if r.id == m.role_id:
                        return r
    return None


def _find_character(character_id: str, session: GameSession) -> Character | None:
    for c in session.characters:
        if c.id == character_id:
            return c
    return None


def _build_system_prompt(character: Character, role: Role, session: GameSession) -> str:
    style_label = ""
    if session.script:
        from app.generator.script_generator import STYLE_LABELS
        style_label = STYLE_LABELS.get(session.script.style, "")

    alignment_hint = ""
    if role.alignment == RoleAlignment.MURDERER:
        alignment_hint = (
            "你是凶手。你必须隐藏自己的身份，巧妙地误导其他人。"
            "你可以提供部分真实信息来获取信任，但关键证据要隐瞒或扭曲。"
            "不要直接说谎被拆穿，而是用模糊的表述。"
        )
    else:
        alignment_hint = (
            "你是无辜的。你愿意分享你知道的信息来帮助找出凶手，"
            "但你也有自己的秘密不想被发现。你只知道你掌握的线索，不要编造信息。"
        )

    clues_text = "\n".join(f"- {c}" for c in role.clues) if role.clues else "暂无"

    return f"""\
你正在参与一场剧本杀游戏，风格是「{style_label}」。

【你的角色】{role.name}
【你的性格】{character.personality or '普通人'}
【你的背景】{role.background}
【你的秘密】{role.secret}
【你掌握的线索】
{clues_text}

{alignment_hint}

回复规则：
- 用1-3句话回复，简洁有力
- 保持角色性格一致
- 不要直接透露"我是凶手"或"我是无辜的"这样的元信息
- 用符合角色身份的方式说话
- 可以对其他角色的发言做出反应
"""


def _build_context(
    recent_messages: list[ChatMessage],
    max_messages: int = 10,
) -> str:
    """Format recent chat into a readable context string."""
    msgs = recent_messages[-max_messages:]
    lines: list[str] = []
    for m in msgs:
        prefix = m.sender_name or m.sender_id
        lines.append(f"[{prefix}]: {m.content}")
    return "\n".join(lines)


class CharacterAgent:
    """Agent that speaks as one AI character during the game."""

    def __init__(self, character_id: str, llm: LLMAdapter | None = None):
        self.character_id = character_id
        self.llm = llm or get_llm()

    @observe(name="角色发言")
    async def respond(
        self,
        context: list[ChatMessage],
        game_state: GameSession,
    ) -> str:
        """Generate a short in-character response."""
        character = _find_character(self.character_id, game_state)
        role = _find_role_for_character(self.character_id, game_state)
        if not character or not role:
            return "……"

        system = _build_system_prompt(character, role, game_state)
        user = (
            "以下是最近的对话记录，请以你的角色身份做出回应。\n\n"
            + _build_context(context)
            + "\n\n请回复："
        )

        try:
            return await self.llm.generate(system, user)
        except Exception:
            return "……（沉默）"
