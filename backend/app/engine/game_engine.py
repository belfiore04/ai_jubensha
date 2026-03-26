"""Game engine – orchestrates a full murder-mystery session."""
from __future__ import annotations

import asyncio
import random
import time
import uuid
from typing import Any

from app.engine.character_agent import CharacterAgent
from app.engine.dm_agent import DMAgent
from app.generator.script_generator import generate_act, generate_outline
from app.llm.adapter import LLMAdapter, get_llm
from app.models.game import (
    Act,
    Character,
    CharacterRoleMapping,
    ChatMessage,
    GamePhase,
    GameSession,
    MessageType,
    ScriptStyle,
)

# ── fixed platform characters ─────────────────────────
PLATFORM_CHARACTERS: list[Character] = [
    Character(
        id="char-zhangshan",
        name="张山",
        avatar="",
        personality="退伍军人出身的厨师，豪爽硬朗，有强烈的保护欲与求胜心，是团队里最可靠的物理担当",
        description="退伍老兵/厨师",
    ),
    Character(
        id="char-kue",
        name="酷鹅",
        avatar="",
        personality="穿着得体、礼貌周到但精神状态随时炸裂的毒舌担当，说话简短犀利，擅长阴阳怪气和高端嘲讽",
        description="毒舌南极监护人",
    ),
    Character(
        id="char-huyifei",
        name="胡一菲",
        avatar="",
        personality="彪悍的大学老师，身体是女人性格是半个男人，非常要强要面子，嘴上凶狠但内心有柔软的一面",
        description="彪悍女教师",
    ),
    Character(
        id="char-bbbb",
        name="豆几",
        avatar="",
        personality="18岁男团爱豆，幽默搞怪抽象，看着花心其实内心中二单纯，说话直白口语化，擅长调情逗人",
        description="搞怪男团爱豆",
    ),
]

# ── in-memory store ────────────────────────────────────
_store: dict[str, GameSession] = {}
# background generation tasks
_bg_tasks: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]
# message queues for SSE
_message_queues: dict[str, asyncio.Queue] = {}  # type: ignore[type-arg]
# debug log queues
_debug_queues: dict[str, asyncio.Queue] = {}  # type: ignore[type-arg]


def _debug(game_id: str, msg: str) -> None:
    """Push a debug message to the debug SSE stream."""
    import time as _t
    q = _debug_queues.get(game_id)
    if q:
        q.put_nowait({"ts": _t.time(), "msg": msg})


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> float:
    return time.time()


def _push(session: GameSession, msg: ChatMessage) -> None:
    """Append message to session and to the SSE queue."""
    session.messages.append(msg)
    q = _message_queues.get(session.id)
    if q:
        q.put_nowait(msg)


def _make_msg(
    content: str,
    msg_type: MessageType,
    sender_id: str = "system",
    sender_name: str = "系统",
    **kwargs: Any,
) -> ChatMessage:
    return ChatMessage(
        id=_uid(),
        type=msg_type,
        sender_id=sender_id,
        sender_name=sender_name,
        content=content,
        timestamp=_now(),
        **kwargs,
    )


class GameEngine:
    """Manages one game session end-to-end."""

    def __init__(self, llm: LLMAdapter | None = None):
        self.llm = llm or get_llm()
        self.dm = DMAgent(llm=self.llm)

    # ── helpers ────────────────────────────────────────

    def _get(self, game_id: str) -> GameSession:
        session = _store.get(game_id)
        if not session:
            raise ValueError(f"Game {game_id} not found")
        return session

    def _get_agent(self, character_id: str) -> CharacterAgent:
        return CharacterAgent(character_id, llm=self.llm)

    async def _ai_characters_discuss(
        self, session: GameSession, context_hint: str
    ) -> list[ChatMessage]:
        """Let all AI characters each say one line about the current situation."""
        messages: list[ChatMessage] = []
        ai_char_ids = [
            m.character_id for m in session.mappings if not m.is_player
        ]
        for cid in ai_char_ids:
            agent = self._get_agent(cid)
            # Find character name
            char_name = cid
            for c in session.characters:
                if c.id == cid:
                    char_name = c.name
                    break
            try:
                text = await agent.respond(session.messages, session)
                msg = _make_msg(
                    text,
                    MessageType.CHARACTER_SPEAK,
                    sender_id=cid,
                    sender_name=char_name,
                )
                _push(session, msg)
                messages.append(msg)
            except Exception:
                pass
        return messages

    # ── lifecycle ──────────────────────────────────────

    def create_game(self) -> GameSession:
        gid = uuid.uuid4().hex
        session = GameSession(id=gid)
        _store[gid] = session
        _message_queues[gid] = asyncio.Queue()
        _debug_queues[gid] = asyncio.Queue()
        return session

    async def set_style(self, game_id: str, style: ScriptStyle) -> GameSession:
        session = self._get(game_id)
        _debug(game_id, f"🎨 选择风格: {style.value}")
        session.style = style
        session.phase = GamePhase.GENERATING

        _push(
            session,
            _make_msg(f"已选择风格：{style.value}，正在生成剧本大纲……", MessageType.SYSTEM),
        )

        # generate outline (roles are created by the LLM)
        _debug(game_id, "🤖 LLM调用: generate_outline 开始...")
        try:
            script = await generate_outline(style, llm=self.llm)
        except Exception as e:
            _debug(game_id, f"❌ 大纲生成失败: {e}")
            raise
        _debug(game_id, f"✅ 大纲生成完成: {script.title}")
        session.script = script
        session.phase = GamePhase.ROLE_ASSIGN

        _push(
            session,
            _make_msg(
                f"剧本「{script.title}」已生成！请选择你想扮演的角色。",
                MessageType.SYSTEM,
            ),
        )
        return session

    async def start_game(
        self, game_id: str, player_role_id: str, player_character_id: str
    ) -> list[ChatMessage]:
        session = self._get(game_id)
        if not session.script:
            raise ValueError("Script not generated yet")

        # Assign the 4 fixed platform characters to the 4 roles randomly
        characters = list(PLATFORM_CHARACTERS)
        roles = list(session.script.roles)

        # Validate: player cannot pick the murderer role
        from app.models.game import RoleAlignment
        player_role = None
        for r in roles:
            if r.id == player_role_id:
                player_role = r
                break
        if player_role and player_role.alignment == RoleAlignment.MURDERER:
            # Silently reassign to first innocent role instead
            for r in roles:
                if r.alignment == RoleAlignment.INNOCENT:
                    player_role_id = r.id
                    break

        # Pull out the player's chosen character and role
        player_char = None
        for c in characters:
            if c.id == player_character_id:
                player_char = c
                break
        if not player_char:
            raise ValueError(f"Character {player_character_id} not found")

        # remaining characters and roles
        remaining_chars = [c for c in characters if c.id != player_character_id]
        remaining_roles = [r for r in roles if r.id != player_role_id]

        if len(remaining_chars) != 3 or len(remaining_roles) != 3:
            raise ValueError("Need exactly 4 characters and 4 roles")

        # shuffle remaining characters to assign to remaining roles randomly
        random.shuffle(remaining_chars)

        # build mappings
        mappings: list[CharacterRoleMapping] = [
            CharacterRoleMapping(
                character_id=player_character_id,
                role_id=player_role_id,
                is_player=True,
            )
        ]
        for i, role in enumerate(remaining_roles):
            mappings.append(
                CharacterRoleMapping(
                    character_id=remaining_chars[i].id,
                    role_id=role.id,
                    is_player=False,
                )
            )

        session.characters = characters
        session.mappings = mappings
        session.player_character_id = player_character_id

        session.phase = GamePhase.GENERATING
        _debug(game_id, "🎮 游戏启动，分配角色完成")
        _push(
            session,
            _make_msg("游戏开始！正在生成第一幕……", MessageType.SYSTEM),
        )

        # generate act 1
        _debug(game_id, "🤖 LLM调用: generate_act(1) 开始...")
        try:
            act1 = await generate_act(session.script, 1, [], llm=self.llm)
        except Exception as e:
            _debug(game_id, f"❌ 第一幕生成失败: {e}")
            raise
        _debug(game_id, f"✅ 第一幕生成完成: {act1.title}")
        session.script.acts.append(act1)
        session.current_act = 1
        session.phase = GamePhase.ACT_1

        # kick off background generation of acts 2 & 3
        _debug(game_id, "⏳ 后台生成第2、3幕...")
        _bg_tasks[game_id] = asyncio.create_task(
            self._generate_remaining_acts(game_id)
        )

        # produce opening messages
        messages: list[ChatMessage] = []

        # prologue (story background)
        prologue_msg = _make_msg(
            session.script.prologue,
            MessageType.DM_NARRATION,
            sender_id="dm",
            sender_name="DM",
        )
        _push(session, prologue_msg)
        messages.append(prologue_msg)

        # act 1 narration (use the act's own narration, not DM re-generate)
        if act1.narration:
            narr_msg = _make_msg(
                f"【第一幕：{act1.title}】\n{act1.narration}",
                MessageType.DM_NARRATION,
                sender_id="dm",
                sender_name="DM",
            )
            _push(session, narr_msg)
            messages.append(narr_msg)

        # reveal act 1 clues
        clue_msgs = self.dm.reveal_clues(act1)
        for cm in clue_msgs:
            _push(session, cm)
            messages.append(cm)

        # present first choice (only first one — wait for answer before next)
        choice_msg = self.dm.present_choice(act1, 0)
        if choice_msg:
            _push(session, choice_msg)
            messages.append(choice_msg)

        return messages

    async def _generate_remaining_acts(self, game_id: str) -> None:
        """Background task: generate acts 2 and 3."""
        try:
            session = self._get(game_id)
            if not session.script:
                return

            for act_num in (2, 3):
                # Skip if already generated (by on-demand generation)
                if any(a.act_number == act_num for a in session.script.acts):
                    continue
                prev = [a for a in session.script.acts if a.generated]
                act = await generate_act(
                    session.script, act_num, prev, llm=self.llm
                )
                # Double-check before appending (race condition guard)
                if not any(a.act_number == act_num for a in session.script.acts):
                    session.script.acts.append(act)
        except Exception:
            pass  # non-critical: we'll regenerate on demand if needed

    # ── player actions ─────────────────────────────────

    async def player_action(
        self,
        game_id: str,
        action_type: str,
        content: str,
    ) -> list[ChatMessage]:
        session = self._get(game_id)
        if not session.script:
            raise ValueError("Game not started")

        if action_type == "speak":
            return await self._handle_speak(session, content)
        elif action_type == "choice":
            return await self._handle_choice(session, content)
        elif action_type == "vote":
            return await self._handle_vote(session, content)
        else:
            raise ValueError(f"Unknown action type: {action_type}")

    async def _handle_speak(
        self, session: GameSession, content: str
    ) -> list[ChatMessage]:
        """Player speaks freely; DM + AI characters may respond."""
        # find player character name
        player_name = "玩家"
        for c in session.characters:
            if c.id == session.player_character_id:
                player_name = c.name
                break

        player_msg = _make_msg(
            content,
            MessageType.PLAYER_SPEAK,
            sender_id=session.player_character_id,
            sender_name=player_name,
        )
        _push(session, player_msg)

        result: list[ChatMessage] = [player_msg]

        # DM reacts
        dm_msgs = await self.dm.react(content, session.messages, session)
        for m in dm_msgs:
            _push(session, m)
            result.append(m)

        # AI characters respond (pick 1-2 randomly for brevity)
        ai_char_ids = [
            m.character_id for m in session.mappings if not m.is_player
        ]

        # let up to 2 characters respond
        responders = random.sample(ai_char_ids, min(2, len(ai_char_ids)))
        for cid in responders:
            agent = self._get_agent(cid)
            text = await agent.respond(session.messages, session)
            char_name = cid
            for c in session.characters:
                if c.id == cid:
                    char_name = c.name
                    break
            char_msg = _make_msg(
                text,
                MessageType.CHARACTER_SPEAK,
                sender_id=cid,
                sender_name=char_name,
            )
            _push(session, char_msg)
            result.append(char_msg)

        return result

    async def _handle_choice(
        self, session: GameSession, content: str
    ) -> list[ChatMessage]:
        """Player answers a choice question. content = option_id."""
        current_act = self._current_act(session)
        if not current_act:
            return [_make_msg("当前没有进行中的章节。", MessageType.SYSTEM)]

        result: list[ChatMessage] = []

        # find the question/option
        correct = False
        explanation = ""
        for q in current_act.choices:
            for opt in q.options:
                if opt.id == content:
                    correct = opt.is_correct
                    explanation = q.explanation
                    break

        if correct:
            session.score += 10
            resp = _make_msg(
                f"✅ 回答正确！+10分\n{explanation}",
                MessageType.SYSTEM,
            )
        else:
            resp = _make_msg(
                f"❌ 回答错误。\n{explanation}",
                MessageType.SYSTEM,
            )
        _push(session, resp)
        result.append(resp)

        # check if we should advance to next phase
        advance_msgs = await self._try_advance(session)
        result.extend(advance_msgs)

        return result

    async def _handle_vote(
        self, session: GameSession, content: str
    ) -> list[ChatMessage]:
        """Player votes for the murderer. content = role_id."""
        session.phase = GamePhase.ENDING
        msgs = self.dm.resolve_vote(content, session)
        result: list[ChatMessage] = []
        for m in msgs:
            _push(session, m)
            result.append(m)
        return result

    # ── phase management ───────────────────────────────

    def _current_act(self, session: GameSession) -> Act | None:
        if not session.script:
            return None
        for a in session.script.acts:
            if a.act_number == session.current_act:
                return a
        return None

    async def _try_advance(self, session: GameSession) -> list[ChatMessage]:
        """
        Check if all choices in current act are answered, then advance
        to the next act or to voting.
        """
        current = self._current_act(session)
        if not current:
            return []

        # Count answers for CURRENT act only:
        # Each choice message in the buffer is followed by a "回答正确/错误" system message.
        # Count how many answer-result messages appeared AFTER the current act started.
        # We find the act's first choice message index, then count answers after it.
        current_act_choices = len(current.choices)

        # Find where current act's content starts in messages
        act_marker = f"第{session.current_act}幕" if session.current_act > 1 else "第一幕"
        act_start_idx = 0
        for i, m in enumerate(session.messages):
            if m.type == MessageType.DM_NARRATION and act_marker in m.content:
                act_start_idx = i
                break

        # Count answers after act_start_idx
        act_answered = 0
        for m in session.messages[act_start_idx:]:
            if m.type == MessageType.SYSTEM and ("回答正确" in m.content or "回答错误" in m.content):
                act_answered += 1

        if act_answered < current_act_choices:
            # Still have unanswered questions in this act — present next one
            choice_msg = self.dm.present_choice(current, act_answered)
            if choice_msg:
                _push(session, choice_msg)
                return [choice_msg]
            return []

        # current act fully answered → advance
        result: list[ChatMessage] = []
        _debug(session.id, f"📊 第{session.current_act}幕完成(answered={act_answered}/{current_act_choices}), 推进中...")

        if session.current_act < 3:
            next_act_num = session.current_act + 1
            next_phase = {2: GamePhase.ACT_2, 3: GamePhase.ACT_3}[next_act_num]

            # wait for background generation if needed
            next_act = None
            if session.script:
                for a in session.script.acts:
                    if a.act_number == next_act_num:
                        next_act = a
            if not next_act:
                # Notify user we're generating
                loading_msg = _make_msg(
                    f"⏳ 正在生成第{next_act_num}幕...",
                    MessageType.SYSTEM,
                )
                _push(session, loading_msg)
                result.append(loading_msg)
                _debug(session.id, f"🤖 第{next_act_num}幕未预生成，按需生成中...")
                if session.script:
                    try:
                        prev = [a for a in session.script.acts if a.generated]
                        next_act = await generate_act(
                            session.script, next_act_num, prev, llm=self.llm
                        )
                        # Guard against duplicate (background task may have finished)
                        if not any(a.act_number == next_act_num for a in session.script.acts):
                            session.script.acts.append(next_act)
                        _debug(session.id, f"✅ 第{next_act_num}幕生成完成")
                    except Exception as e:
                        _debug(session.id, f"❌ 第{next_act_num}幕生成失败: {e}")
                        _push(session, _make_msg(f"第{next_act_num}幕生成失败，请重试。", MessageType.SYSTEM))
                        return result
            else:
                _debug(session.id, f"✅ 第{next_act_num}幕已预生成")

            if next_act:
                session.current_act = next_act_num
                session.phase = next_phase

                # Notify user we're entering next act
                entering_msg = _make_msg(
                    f"⏳ 正在进入第{next_act_num}幕...",
                    MessageType.SYSTEM,
                )
                _push(session, entering_msg)
                result.append(entering_msg)

                narration = await self.dm.narrate(next_phase, next_act, session)
                narr_msg = _make_msg(
                    narration,
                    MessageType.DM_NARRATION,
                    sender_id="dm",
                    sender_name="DM",
                )
                _push(session, narr_msg)
                result.append(narr_msg)

                clue_msgs = self.dm.reveal_clues(next_act)
                for cm in clue_msgs:
                    _push(session, cm)
                    result.append(cm)

                choice_msg = self.dm.present_choice(next_act, 0)
                if choice_msg:
                    _push(session, choice_msg)
                    result.append(choice_msg)
        else:
            session.phase = GamePhase.VOTING
            vote_msg = self.dm.start_vote(session)
            _push(session, vote_msg)
            result.append(vote_msg)

        return result

    # ── query ──────────────────────────────────────────

    def get_state(self, game_id: str) -> GameSession:
        return self._get(game_id)

    def get_debug_queue(self, game_id: str) -> asyncio.Queue:
        q = _debug_queues.get(game_id)
        if not q:
            q = asyncio.Queue()
            _debug_queues[game_id] = q
        return q

    def get_message_queue(self, game_id: str) -> asyncio.Queue:
        q = _message_queues.get(game_id)
        if not q:
            q = asyncio.Queue()
            _message_queues[game_id] = q
        return q
