"""Discussion engine — multi-turn LLM-routed discussion for murder mystery.

Ported from forget-me-not group chat's sequential discussion mechanism:
  LLM picks who speaks -> sequential generation -> multi-round continuation
  -> natural termination when selector returns []

Each character has context isolation: own messages = assistant,
others' messages = user with <msg from="name"> wrapping.
"""
from __future__ import annotations

import json
import random
import re
from typing import Callable, Awaitable

from langfuse import observe

from app.llm.adapter import LLMAdapter
from app.models.game import (
    Character,
    CharacterRoleMapping,
    ChatMessage,
    Clue,
    MessageType,
    Role,
    RoleAlignment,
    uid,
)

MAX_AI_ROUNDS = 10  # safety valve, not a real limit


def _clean_response(text: str) -> str:
    """Strip markdown formatting and action descriptions."""
    text = re.sub(r'\*[^*]+\*', '', text)
    text = re.sub(r'[（(][^）)]{1,10}[）)]', '', text)
    text = re.sub(r'^#+\s+.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'^[-*]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{2,}', '\n', text)
    return text.strip()


def _post_process_reply(reply: str, char_name: str, all_names: list[str]) -> str:
    """Remove name prefixes, leaked <msg> tags, action descriptions."""
    # Only strip self name prefix at the start of the reply
    reply = re.sub(r'^\[?' + re.escape(char_name) + r'\]?\s*[:：]\s*', '', reply)
    # Remove leaked <msg> tags (AI speaking as another character)
    for name in all_names:
        reply = re.sub(r'<msg\s+from="' + re.escape(name) + r'">.*?</msg>', '', reply, flags=re.DOTALL)
    # Only strip other character name prefixes at line start (not mid-sentence)
    for name in all_names:
        reply = re.sub(r'^\[' + re.escape(name) + r'\]\s*[:：]\s*', '', reply, flags=re.MULTILINE)
    reply = _clean_response(reply)
    return reply.strip()


class DiscussionEngine:
    """Multi-turn discussion engine for murder mystery games.

    Usage (from play.py):
        engine = DiscussionEngine(characters, roles, mappings, player_char_id, llm, context)
        await engine.run_discussion(clues, on_message=print_callback)
    """

    def __init__(
        self,
        characters: list[Character],
        roles: list[Role],
        mappings: list[CharacterRoleMapping],
        player_character_id: str,
        llm: LLMAdapter,
        script_context: str = "",
    ):
        self.characters = characters
        self.roles = roles
        self.mappings = mappings
        self.player_character_id = player_character_id
        self.llm = llm
        self.script_context = script_context

        # Build lookup tables
        self._char_by_id = {c.id: c for c in characters}
        self._role_by_id = {r.id: r for r in roles}
        self._mapping_by_char = {m.character_id: m for m in mappings}

        # AI character ids (exclude player)
        self.ai_char_ids = [
            m.character_id for m in mappings if m.character_id != player_character_id
        ]

    def _get_role(self, character_id: str) -> Role | None:
        m = self._mapping_by_char.get(character_id)
        if m:
            return self._role_by_id.get(m.role_id)
        return None

    def _get_char(self, character_id: str) -> Character | None:
        return self._char_by_id.get(character_id)

    def _role_name(self, character_id: str) -> str:
        role = self._get_role(character_id)
        return role.name if role else "?"

    def _char_name(self, character_id: str) -> str:
        char = self._get_char(character_id)
        return char.name if char else "?"

    # ── System prompt (jubensha-specific) ────────────────

    def _build_system_prompt(self, character: Character, role: Role) -> str:
        if role.alignment == RoleAlignment.MURDERER:
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

        clues_text = "\n".join(f"- {c}" for c in role.clues) if role.clues else "暂无"
        goal_text = f"\n【你的隐藏目标】{role.goal}" if role.goal else ""

        return f"""\
你正在参与一场剧本杀游戏的自由讨论环节。{self.script_context}

【你的角色】{role.name}
【你的性格】{character.personality or '普通人'}
【你的背景】{role.background}
【你的秘密】{role.secret}{goal_text}
【你掌握的线索】
{clues_text}

{alignment_hint}

<对话历史格式说明>
其他角色的消息以 <msg from="名字">内容</msg> 格式出现。
你之前说过的话以纯文本出现（role=assistant）。
</对话历史格式说明>

<严格规则>
1. 你只扮演「{role.name}」，用 TA 的口吻说话
2. 回复简短自然，1-3句话，不超过80字
3. 你可以回应任何人的话，提出疑问，或分享你的看法
4. 【重要】只输出你要说的话，不要替其他角色说话
5. 【重要】不要加前缀如 [{role.name}]: 或 <msg> 标签，直接输出纯文本
6. 【禁止】不要用括号描述动作，用语言表达情绪
7. 围绕你的隐藏目标行动，但不要直白地暴露目标本身
</严格规则>"""

    # ── Context isolation ────────────────────────────────

    def _build_chat_messages(
        self, character_id: str, history: list[ChatMessage],
    ) -> list[dict[str, str]]:
        """Build message list with context isolation.

        Own messages -> role=assistant
        Others' messages -> role=user with <msg from="name"> wrapping
        """
        result: list[dict[str, str]] = []
        for msg in history[-20:]:  # keep recent context manageable
            if msg.sender_id == character_id:
                result.append({"role": "assistant", "content": msg.content})
            else:
                sender = msg.sender_name or msg.sender_id
                result.append({
                    "role": "user",
                    "content": f'<msg from="{sender}">{msg.content}</msg>',
                })
        return result

    # ── Responder selection ──────────────────────────────

    @observe(name="讨论选人")
    async def _select_responders(
        self,
        history: list[ChatMessage],
        trigger_sender: str,
        trigger_message: str,
        exclude_ids: list[str] | None = None,
        is_ai_round: bool = False,
    ) -> list[str]:
        """Use LLM to decide which AI characters should speak next.

        Returns list of character_ids, or [] to stop the round.
        """
        exclude_ids = exclude_ids or []
        available = [
            cid for cid in self.ai_char_ids if cid not in exclude_ids
        ]
        if not available:
            return []

        # Build character descriptions
        char_descs = []
        for cid in available:
            char = self._get_char(cid)
            role = self._get_role(cid)
            if char and role:
                char_descs.append(f"- {role.name}：{role.background[:50]}")

        # Recent context
        recent = history[-6:]
        recent_lines = []
        for m in recent:
            sender = m.sender_name or m.sender_id
            recent_lines.append(f"[{sender}]: {m.content}")
        recent_context = "\n".join(recent_lines)

        ai_round_rule = ""
        if is_ai_round:
            ai_round_rule = (
                "\n6. 【重要】这是 AI 互动轮（不是玩家发起的），要更严格："
                "只有当某个角色确实有话要接、有新信息要补充时才让 TA 回复。"
                "闲聊接茬、重复附和不算。大部分情况应该返回 []。"
            )

        available_names = [self._role_name(cid) for cid in available]
        names_str = "、".join(available_names)

        prompt = f"""根据对话上下文，从可选角色中选出应该回复的角色。直接返回JSON数组。

可选角色：
{chr(10).join(char_descs)}

最近对话：
{recent_context}

最新消息来自「{trigger_sender}」: {trigger_message}

规则：选1-2个最相关的角色回复。对话自然结束则返回[]。{ai_round_rule}

示例输出: ["{available_names[0]}"] 或 ["{available_names[0]}", "{available_names[-1]}"] 或 []

请直接输出JSON数组，不要输出任何其他文字："""

        # Map role names -> character ids (used after LLM response)
        role_to_char = {}
        for cid in available:
            role = self._get_role(cid)
            if role:
                role_to_char[role.name] = cid

        # Retry up to 2 times on empty/malformed response
        for attempt in range(2):
            try:
                raw = await self.llm.generate_chat(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=100,
                    temperature=0.2,
                )
                if not raw or not raw.strip():
                    if attempt == 0:
                        print(f"[Discussion] 选人返回空，重试...")
                        continue
                    # Second empty = treat as no responders
                    break

                match = re.search(r'\[.*?\]', raw, re.DOTALL)
                if match:
                    names = json.loads(match.group())
                else:
                    names = json.loads(raw)

                selected = [role_to_char[n] for n in names if n in role_to_char]

                # Fallback: non-AI round, nothing selected -> random pick
                if not selected and not is_ai_round:
                    selected = [random.choice(available)]

                return selected

            except Exception as e:
                if attempt == 0:
                    print(f"[Discussion] 选人解析失败({e})，重试...")
                    continue
                print(f"[Discussion] LLM 选人失败: {e}")

        # Final fallback after all retries exhausted
        if is_ai_round:
            return []
        return [random.choice(available)] if available else []

    # ── Reply generation ─────────────────────────────────

    @observe(name="讨论回复")
    async def _generate_reply(
        self, character_id: str, history: list[ChatMessage],
    ) -> str:
        """Generate one character's reply with full context isolation."""
        char = self._get_char(character_id)
        role = self._get_role(character_id)
        if not char or not role:
            return "……"

        system_prompt = self._build_system_prompt(char, role)
        chat_history = self._build_chat_messages(character_id, history)
        messages = [{"role": "system", "content": system_prompt}] + chat_history

        try:
            raw = await self.llm.generate_chat(
                messages=messages,
                max_tokens=200,
                temperature=0.8,
            )
            all_names = [self._role_name(cid) for cid in self.ai_char_ids]
            player_role = self._get_role(self.player_character_id)
            if player_role:
                all_names.append(player_role.name)
            return _post_process_reply(raw, role.name, all_names)
        except Exception as e:
            print(f"[Discussion] 回复生成失败 ({char.name}): {e}")
            return "……"

    # ── Multi-round AI discussion ────────────────────────

    async def _ai_multi_round(
        self,
        history: list[ChatMessage],
        trigger_sender: str,
        trigger_message: str,
        on_message: Callable[[str, str, str], Awaitable[None] | None],
    ) -> None:
        """Run multiple AI discussion rounds until natural termination.

        Each round: select responders -> generate replies sequentially
        -> next round triggered by last speaker (excluded from selection).
        Stops when selector returns [] or MAX_AI_ROUNDS reached.
        """
        current_trigger_sender = trigger_sender
        current_trigger_message = trigger_message
        exclude_ids: list[str] = []

        for round_num in range(MAX_AI_ROUNDS):
            is_ai_round = round_num > 0

            responder_ids = await self._select_responders(
                history,
                trigger_sender=current_trigger_sender,
                trigger_message=current_trigger_message,
                exclude_ids=exclude_ids if is_ai_round else None,
                is_ai_round=is_ai_round,
            )

            if not responder_ids:
                break

            last_speaker_id = None
            for cid in responder_ids:
                reply = await self._generate_reply(cid, history)
                if not reply or reply == "……":
                    continue

                role = self._get_role(cid)
                char = self._get_char(cid)
                role_name = role.name if role else "?"
                char_name = char.name if char else "?"

                msg = ChatMessage(
                    id=uid(),
                    type=MessageType.CHARACTER_SPEAK,
                    sender_id=cid,
                    sender_name=f"{char_name}({role_name})",
                    content=reply,
                    timestamp=0,
                )
                history.append(msg)
                last_speaker_id = cid

                # Notify caller
                result = on_message(char_name, role_name, reply)
                if hasattr(result, '__await__'):
                    await result

            if not last_speaker_id:
                break

            # Next round: triggered by last speaker, exclude them
            last_role = self._get_role(last_speaker_id)
            current_trigger_sender = last_role.name if last_role else "?"
            current_trigger_message = history[-1].content
            exclude_ids = [last_speaker_id]

    # ── Main API ─────────────────────────────────────────

    async def run_discussion(
        self,
        clues: list[Clue],
        on_message: Callable[[str, str, str], Awaitable[None] | None],
        get_player_input: Callable[[], str] | None = None,
    ) -> list[ChatMessage]:
        """Run the full discussion phase.

        Args:
            clues: Clues to inject at the start
            on_message: Callback(char_name, role_name, content) for each AI message
            get_player_input: Function that returns player text input (empty = end).
                              If None, uses built-in input().

        Returns:
            Full discussion history
        """
        if get_player_input is None:
            get_player_input = lambda: input().strip()

        history: list[ChatMessage] = []

        # Inject clue context as a system-like message for the AI to reference
        if clues:
            clue_text = "本轮发现的线索：\n" + "\n".join(
                f"- 【{cl.title}】{cl.content}" for cl in clues
            )
            clue_msg = ChatMessage(
                id=uid(),
                type=MessageType.SYSTEM,
                sender_id="system",
                sender_name="系统",
                content=clue_text,
                timestamp=0,
            )
            history.append(clue_msg)

        # Initial AI round: triggered by clue discovery
        initial_trigger = (
            clue_text if clues
            else "讨论开始，请各位发表看法。"
        )

        await self._ai_multi_round(
            history,
            trigger_sender="系统",
            trigger_message=initial_trigger,
            on_message=on_message,
        )

        # Player input loop
        while True:
            player_text = get_player_input()
            if not player_text:
                break

            # Record player message
            player_role = self._get_role(self.player_character_id)
            player_char = self._get_char(self.player_character_id)
            player_role_name = player_role.name if player_role else "玩家"
            player_char_name = player_char.name if player_char else "玩家"

            player_msg = ChatMessage(
                id=uid(),
                type=MessageType.PLAYER_SPEAK,
                sender_id=self.player_character_id,
                sender_name=f"{player_char_name}({player_role_name})",
                content=player_text,
                timestamp=0,
            )
            history.append(player_msg)

            # AI responds to player
            await self._ai_multi_round(
                history,
                trigger_sender=player_role_name,
                trigger_message=player_text,
                on_message=on_message,
            )

        return history
