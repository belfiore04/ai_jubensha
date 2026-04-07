"""Game engine – orchestrates a full murder-mystery session."""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any

from app.engine.character_agent import CharacterAgent
from app.engine.discussion_engine import DiscussionEngine
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
    uid,
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
# discussion engine state
_disc_engines: dict[str, DiscussionEngine] = {}
_disc_histories: dict[str, list[ChatMessage]] = {}
_in_discussion: dict[str, bool] = {}


def _debug(game_id: str, msg: str) -> None:
    """Push a debug message to the debug SSE stream."""
    import time as _t
    q = _debug_queues.get(game_id)
    if q:
        q.put_nowait({"ts": _t.time(), "msg": msg})


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
        id=uid(),
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

    # ── discussion ────────────────────────────────────

    async def run_discussion_round(
        self, session: GameSession, clue_context: str, discussion_history: list[ChatMessage],
    ) -> list[ChatMessage]:
        """Run one round of AI discussion: all AI characters speak concurrently."""
        ai_chars = [
            (m.character_id, next((c.name for c in session.characters if c.id == m.character_id), m.character_id))
            for m in session.mappings if not m.is_player
        ]

        async def _one_response(cid: str) -> tuple[str, str]:
            agent = self._get_agent(cid)
            text = await agent.respond(
                context=discussion_history,
                game_state=session,
                mode="discuss",
                clue_context=clue_context,
            )
            return cid, text

        # Fire all AI characters concurrently
        results = await asyncio.gather(*[_one_response(cid) for cid, _ in ai_chars])

        round_msgs: list[ChatMessage] = []
        for cid, text in results:
            char_name = next((n for c, n in ai_chars if c == cid), cid)
            msg = _make_msg(
                text,
                MessageType.CHARACTER_SPEAK,
                sender_id=cid,
                sender_name=char_name,
            )
            _push(session, msg)
            round_msgs.append(msg)

        return round_msgs

    # ── lifecycle ──────────────────────────────────────

    def create_game(
        self,
        ai_characters: list[Character] | None = None,
        player_name: str = "玩家",
        player_avatar: str = "",
    ) -> GameSession:
        gid = uid() + uid()
        session = GameSession(id=gid)

        # Build player character
        player_char = Character(
            id="player",
            name=player_name,
            avatar=player_avatar,
            personality="",
            description="玩家",
        )

        # Use provided AI characters or fall back to platform defaults
        ai_chars = ai_characters if ai_characters else list(PLATFORM_CHARACTERS)
        # Ensure exactly 3 AI characters
        ai_chars = ai_chars[:3]

        session.characters = [player_char] + ai_chars
        session.player_character_id = player_char.id

        _store[gid] = session
        _message_queues[gid] = asyncio.Queue()
        _debug_queues[gid] = asyncio.Queue()
        return session

    async def set_style(self, game_id: str, style: ScriptStyle) -> GameSession:
        session = self._get(game_id)
        _debug(game_id, f"🎨 选择风格: {style.value}")
        session.style = style
        session.phase = GamePhase.GENERATING

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
        return session

    async def start_game(
        self, game_id: str, player_role_id: str
    ) -> list[ChatMessage]:
        session = self._get(game_id)
        if not session.script:
            raise ValueError("Script not generated yet")
        if len(session.characters) < 4:
            raise ValueError("Need at least 4 characters (set in create_game)")

        roles = list(session.script.roles)
        player_character_id = session.player_character_id

        # Validate: player cannot pick the murderer role
        from app.models.game import RoleAlignment
        player_role = next((r for r in roles if r.id == player_role_id), None)
        if player_role and player_role.alignment == RoleAlignment.MURDERER:
            player_role_id = next(
                r.id for r in roles if r.alignment == RoleAlignment.INNOCENT
            )

        # AI characters = everyone except the player
        ai_chars = [c for c in session.characters if c.id != player_character_id]
        remaining_roles = [r for r in roles if r.id != player_role_id]

        if len(ai_chars) < 3 or len(remaining_roles) != 3:
            raise ValueError("Need exactly 3 AI characters and 3 remaining roles")

        random.shuffle(ai_chars)

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
                    character_id=ai_chars[i].id,
                    role_id=role.id,
                    is_player=False,
                )
            )

        session.mappings = mappings

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

        # Start discussion phase (AI characters discuss clues)
        asyncio.create_task(self._start_discussion(session, act1))

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
        elif action_type == "end_discussion":
            return await self._handle_end_discussion(session)
        else:
            raise ValueError(f"Unknown action type: {action_type}")

    async def _handle_speak(
        self, session: GameSession, content: str
    ) -> list[ChatMessage]:
        """Player speaks freely; AI characters respond via discussion engine."""
        game_id = session.id

        # find player character name
        player_name = "玩家"
        player_role_name = ""
        for c in session.characters:
            if c.id == session.player_character_id:
                player_name = c.name
                break
        for m in session.mappings:
            if m.character_id == session.player_character_id and session.script:
                for r in session.script.roles:
                    if r.id == m.role_id:
                        player_role_name = r.name
                        break

        player_msg = _make_msg(
            content,
            MessageType.PLAYER_SPEAK,
            sender_id=session.player_character_id,
            sender_name=player_name,
        )
        _push(session, player_msg)
        result: list[ChatMessage] = [player_msg]

        # Use discussion engine if in discussion mode
        disc_engine = _disc_engines.get(game_id)
        disc_history = _disc_histories.get(game_id)

        if disc_engine and disc_history is not None and _in_discussion.get(game_id):
            # Add player message to discussion history
            disc_history.append(player_msg)
            _debug(game_id, f"💬 玩家发言: {content[:30]}...")

            # AI multi-round response via discussion engine
            def on_message(char_name: str, role_name: str, reply_content: str):
                msg = _make_msg(
                    reply_content,
                    MessageType.CHARACTER_SPEAK,
                    sender_id=next(
                        (c.id for c in session.characters if c.name == char_name),
                        char_name,
                    ),
                    sender_name=char_name,
                )
                _push(session, msg)
                disc_history.append(msg)
                result.append(msg)

            await disc_engine._ai_multi_round(
                disc_history,
                trigger_sender=player_role_name or player_name,
                trigger_message=content,
                on_message=on_message,
            )
        else:
            # Fallback: random AI responses (non-discussion mode)
            ai_char_ids = [
                m.character_id for m in session.mappings if not m.is_player
            ]
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

        session.act_answered += 1

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

    # ── discussion engine integration ─────────────────

    async def _start_discussion(self, session: GameSession, act: Act) -> None:
        """Start discussion phase: create engine, all AI speak, push to SSE."""
        game_id = session.id
        _debug(game_id, "💬 讨论阶段开始")

        # Create discussion engine for this game
        engine = DiscussionEngine(
            characters=session.characters,
            roles=session.script.roles if session.script else [],
            mappings=session.mappings,
            player_character_id=session.player_character_id,
            llm=self.llm,
            script_context=f"剧本「{session.script.title if session.script else ''}」",
            debug_fn=lambda msg: _debug(game_id, msg),
        )
        _disc_engines[game_id] = engine
        _disc_histories[game_id] = []
        _in_discussion[game_id] = True

        # Inject clue context into discussion history
        if act.clues:
            clue_text = "本轮发现的线索：\n" + "\n".join(
                f"- 【{cl.title}】{cl.content}" for cl in act.clues
            )
            clue_msg = _make_msg(clue_text, MessageType.SYSTEM)
            _disc_histories[game_id].append(clue_msg)

        # Signal discussion start to frontend
        start_msg = _make_msg("自由讨论开始，角色们正在发表看法……", MessageType.SYSTEM)
        _push(session, start_msg)

        # All AI characters speak (sequential, context-aware)
        def on_message(char_name: str, role_name: str, content: str):
            msg = _make_msg(
                content,
                MessageType.CHARACTER_SPEAK,
                sender_id=next(
                    (c.id for c in session.characters if c.name == char_name),
                    char_name,
                ),
                sender_name=char_name,
            )
            _push(session, msg)
            _disc_histories[game_id].append(msg)

        await engine._all_ai_speak(_disc_histories[game_id], on_message)

        # Signal that AI finished initial round
        hint_msg = _make_msg(
            "角色们已发表看法。你可以自由发言参与讨论，或点击「结束讨论」进入推理环节。",
            MessageType.SYSTEM,
        )
        _push(session, hint_msg)
        _debug(game_id, "💬 初始轮发言完毕，等待玩家")

    async def _handle_end_discussion(
        self, session: GameSession
    ) -> list[ChatMessage]:
        """End discussion, present first choice question."""
        game_id = session.id
        _in_discussion[game_id] = False
        _debug(game_id, "💬 讨论结束，进入选择题")

        result: list[ChatMessage] = []
        end_msg = _make_msg("讨论结束，进入推理环节。", MessageType.SYSTEM)
        _push(session, end_msg)
        result.append(end_msg)

        current = self._current_act(session)
        if current:
            choice_msg = self.dm.present_choice(current, session.act_answered)
            if choice_msg:
                _push(session, choice_msg)
                result.append(choice_msg)

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

        total_choices = len(current.choices)

        if session.act_answered < total_choices:
            # Still have unanswered questions in this act — present next one
            choice_msg = self.dm.present_choice(current, session.act_answered)
            if choice_msg:
                _push(session, choice_msg)
                return [choice_msg]
            return []

        # current act fully answered → advance
        result: list[ChatMessage] = []
        _debug(session.id, f"📊 第{session.current_act}幕完成(answered={session.act_answered}/{total_choices}), 推进中...")

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
                session.act_answered = 0
                session.phase = next_phase

                # Use the narration already generated by generate_act (no extra LLM call)
                act_label = {2: "二", 3: "三"}.get(next_act_num, str(next_act_num))
                narr_msg = _make_msg(
                    f"【第{act_label}幕：{next_act.title}】\n{next_act.narration}",
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

                # Start discussion for next act (runs in background, pushes to SSE)
                asyncio.create_task(self._start_discussion(session, next_act))
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
