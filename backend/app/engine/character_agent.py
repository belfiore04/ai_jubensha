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
)


def _find_role_for_character(
    character_id: str,
    session: GameSession,
) -> Role | None:
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


def _build_system_prompt(
    character: Character,
    role: Role,
    session: GameSession,
    mode: str = "discuss",
) -> str:
    style_label = ""
    if session.script:
        from app.generator.script_generator import STYLE_LABELS
        style_label = STYLE_LABELS.get(session.script.style, "")

    if role.alignment == RoleAlignment.MURDERER:
        alignment_hint = (
            "你是凶手，但绝不能暴露自己。你的策略：\n"
            "- 主动把话题引向其他嫌疑人，制造合理怀疑\n"
            "- 对指向你的证据轻描淡写地解释，不要长篇辩解（辩解越多越可疑）\n"
            "- 偶尔分享一些无关紧要的真实信息来建立信任\n"
            "- 表现得像一个积极参与推理的无辜者，而不是被质疑的嫌犯\n"
            "- 绝对不要用反问句连续为自己开脱"
        )
    else:
        alignment_hint = (
            "你是无辜的。你愿意分享你知道的线索来帮助找出凶手，"
            "但你也有自己的秘密不想被发现。你只说你确实知道的事，不编造信息。"
        )

    clues_text = "\n".join(f"- {c}" for c in role.clues) if role.clues else "暂无"

    mode_hint = ""
    if mode == "discuss":
        mode_hint = (
            "现在是自由讨论环节，你和其他角色在讨论刚刚发现的线索。"
            "你可以对其他人的发言做出反应，提出疑问，或分享你的看法。"
            "像真人一样自然地参与讨论。"
        )
    elif mode == "respond":
        mode_hint = "有人在和你说话，请以角色身份自然回应。"

    return f"""\
你正在参与一场剧本杀游戏，风格是「{style_label}」。

【你的角色】{role.name}
【你的性格】{character.personality or '普通人'}
【你的背景】{role.background}
【你的秘密】{role.secret}
【你掌握的线索】
{clues_text}

{alignment_hint}

{mode_hint}

回复规则（严格遵守）：
- 只说1-3句话，总共不超过80字，像真人聊天一样简短
- 只输出纯对话文字，禁止使用 *动作描写*、括号旁白、markdown格式（#、**、-）
- 保持{character.name}的性格：{character.personality}
- 不要说"我是凶手"或"我是无辜的"这种元信息
- 不要长篇大论地辩解或分析，说人话
"""


def _clean_response(text: str) -> str:
    """Strip markdown formatting and action descriptions from character response."""
    import re
    # Remove *action* descriptions
    text = re.sub(r'\*[^*]+\*', '', text)
    # Remove （action） descriptions
    text = re.sub(r'（[^）]+）', '', text)
    # Remove markdown headers
    text = re.sub(r'^#+\s+.*$', '', text, flags=re.MULTILINE)
    # Remove markdown bold
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    # Remove markdown list markers
    text = re.sub(r'^[-*]\s+', '', text, flags=re.MULTILINE)
    # Collapse whitespace
    text = re.sub(r'\n{2,}', '\n', text)
    return text.strip()


def _format_context(messages: list[ChatMessage], max_messages: int = 10) -> str:
    msgs = messages[-max_messages:]
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
        mode: str = "discuss",
        clue_context: str = "",
    ) -> str:
        """Generate a short in-character response.

        Args:
            context: Recent chat messages
            game_state: Current game session
            mode: "discuss" (group discussion) or "respond" (reply to player)
            clue_context: Description of current clues for discussion context
        """
        character = _find_character(self.character_id, game_state)
        role = _find_role_for_character(self.character_id, game_state)
        if not character or not role:
            return "……"

        system = _build_system_prompt(character, role, game_state, mode=mode)

        user_parts = []
        if clue_context:
            user_parts.append(f"刚刚发现的线索：\n{clue_context}\n")
        if context:
            user_parts.append(f"讨论记录：\n{_format_context(context)}\n")
        user_parts.append("请以你的角色身份发言：")

        user = "\n".join(user_parts)

        try:
            raw = await self.llm.generate(
                system, user,
                log_name=f"角色发言({character.name})",
            )
            return _clean_response(raw)
        except Exception:
            return "……"
