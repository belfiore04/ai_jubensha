import { useEffect, useState, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useGame } from "../hooks/useGameStore";
import {
  getGame,
  playerAction,
  connectGameStream,
} from "../api";
import type { ChatMessage, Clue } from "../types";
import Header from "../components/Header";
import AvatarRow from "../components/AvatarRow";
import ChatArea from "../components/ChatArea";
import InputBar from "../components/InputBar";
import CluePanel from "../components/CluePanel";
import LoadingOverlay from "../components/LoadingOverlay";
import "./GameRoomPage.css";

/**
 * Messages that need the player to click "下一条" before showing the next one.
 * Only DM narration (after the first one), clues, and choices are paced.
 * System messages and character/player messages auto-show.
 */
const PACED_TYPES = new Set(["dm_narration", "clue", "choice"]);

export default function GameRoomPage() {
  const { id: gameId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { state, dispatch } = useGame();

  const [clueOpen, setClueOpen] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // ── Message pacing ──────────────────────────────────
  // Buffer holds all received messages; visibleCount controls how many are shown.
  const [messageBuffer, setMessageBuffer] = useState<ChatMessage[]>([]);
  const [visibleCount, setVisibleCount] = useState(0);
  // Whether there's a pending choice that must be answered before continuing
  const [waitingForChoice, setWaitingForChoice] = useState(false);

  const visibleMessages = messageBuffer.slice(0, visibleCount);

  // Check if there are more buffered messages to show
  const hasMore = visibleCount < messageBuffer.length;

  // The last visible message — used to decide if we show "下一条" or block on choice
  const lastVisible = visibleMessages[visibleMessages.length - 1];
  const lastVisibleIsChoice = lastVisible?.type === "choice";

  // Show "下一条" button when: there are more messages AND the last one isn't an unanswered choice
  const showNextButton = hasMore && !lastVisibleIsChoice && !waitingForChoice;

  // Count how many DM narrations are already visible (to know if prologue has been shown)
  const dmNarrationCount = visibleMessages.filter(
    (m) => m.type === "dm_narration"
  ).length;

  // Auto-advance logic: show next message automatically if it's not a "paced" type,
  // OR if it's the first DM narration (prologue)
  useEffect(() => {
    if (visibleCount >= messageBuffer.length) return;
    const nextMsg = messageBuffer[visibleCount];
    if (!nextMsg) return;

    const isPaced = PACED_TYPES.has(nextMsg.type);
    const isFirstDM = nextMsg.type === "dm_narration" && dmNarrationCount === 0;

    if (!isPaced || isFirstDM) {
      // Auto-advance: system msgs, player/character msgs, and the first DM (prologue)
      setVisibleCount((c) => c + 1);
    }
  }, [messageBuffer, visibleCount, dmNarrationCount]);

  function handleNextMessage() {
    if (visibleCount < messageBuffer.length) {
      const nextMsg = messageBuffer[visibleCount];
      setVisibleCount((c) => c + 1);
      // If the message we just revealed is a choice, block further advancement
      if (nextMsg?.type === "choice") {
        setWaitingForChoice(true);
      }
    }
  }

  // ── Fetch game state on mount ─────────────────────
  useEffect(() => {
    if (!gameId) return;

    async function fetchAndStart() {
      try {
        dispatch({ type: "SET_LOADING", payload: true });

        const session = await getGame(gameId!);
        dispatch({ type: "SET_SESSION", payload: session });

        // Load existing messages into buffer (they may have been generated before SSE connected)
        if (session.messages?.length) {
          setMessageBuffer((prev) => {
            const existingIds = new Set(prev.map((m) => m.id));
            const newMsgs = session.messages.filter((m: ChatMessage) => !existingIds.has(m.id));
            return [...prev, ...newMsgs];
          });
        }

        dispatch({ type: "SET_LOADING", payload: false });

        // If no messages yet (start_game still running), poll until they arrive
        console.log("[POLL] session.messages:", session.messages?.length ?? 0);
        if (!session.messages?.length) {
          const poll = setInterval(async () => {
            try {
              const s = await getGame(gameId!);
              console.log("[POLL] check:", s.messages?.length ?? 0, "msgs");
              if (s.messages?.length) {
                console.log("[POLL] got messages, filling buffer");
                setMessageBuffer((prev) => {
                  const existingIds = new Set(prev.map((m) => m.id));
                  const newMsgs = s.messages.filter((m: ChatMessage) => !existingIds.has(m.id));
                  return newMsgs.length > 0 ? [...prev, ...newMsgs] : prev;
                });
                dispatch({ type: "SET_SESSION", payload: s });
                clearInterval(poll);
              }
            } catch { /* ignore */ }
          }, 3000);
          // cleanup
          setTimeout(() => clearInterval(poll), 120000);
        }
      } catch (err) {
        dispatch({
          type: "SET_ERROR",
          payload: err instanceof Error ? err.message : "加载游戏失败",
        });
      }
    }

    fetchAndStart();
  }, [gameId, dispatch]);

  // ── SSE stream ────────────────────────────────────
  useEffect(() => {
    if (!gameId) return;

    const es = connectGameStream(
      gameId,
      (data: string) => {
        try {
          const msg: ChatMessage = JSON.parse(data);
          console.log("[SSE]", msg.type, msg.content?.slice(0, 40));
          // Skip player_speak from SSE (already added locally)
          if (msg.type === "player_speak") return;
          // Add to buffer (dedup by id)
          setMessageBuffer((prev) => {
            if (prev.some((m) => m.id === msg.id)) return prev;
            console.log("[BUFFER] added", msg.type, "total:", prev.length + 1);
            return [...prev, msg];
          });
          // Show thinking indicator when waiting for act generation
          if (msg.type === "system" && msg.content.includes("正在生成第")) {
            setIsThinking(true);
          } else {
            setIsThinking(false);
          }

          // Refresh game state on phase-changing messages
          if (
            (msg.type === "dm_narration" && msg.content.includes("选出凶手")) ||
            (msg.type === "system" && msg.content.includes("游戏结束"))
          ) {
            getGame(gameId).then((s) => dispatch({ type: "SET_SESSION", payload: s })).catch(() => {});
          }

          if (msg.type === "system" && msg.content.includes("游戏结束")) {
            setTimeout(() => navigate("/ending"), 1500);
          }
        } catch {
          // ignore
        }
      },
      () => {}
    );

    esRef.current = es;
    return () => {
      es.close();
      esRef.current = null;
    };
  }, [gameId, navigate]);

  // Auto-reveal first DM message immediately (no click needed)
  useEffect(() => {
    if (messageBuffer.length > 0 && visibleCount === 0) {
      // Show the first message automatically
      setVisibleCount(1);
      // If first message is a DM narration, also auto-advance through
      // any immediately following non-choice paced messages (up to 1 more)
      // so the opening feels natural
    }
  }, [messageBuffer.length, visibleCount]);

  // Sync visible messages to global state (for other components)
  useEffect(() => {
    dispatch({ type: "SET_MESSAGES_DIRECT", payload: visibleMessages });
  }, [visibleMessages.length, dispatch]);

  // Timeout: if no messages after 120s, show error
  useEffect(() => {
    if (messageBuffer.length > 0) return; // already got messages
    const timer = setTimeout(() => {
      if (messageBuffer.length === 0) {
        dispatch({
          type: "SET_ERROR",
          payload: "生成超时，请返回重试",
        });
      }
    }, 120000);
    return () => clearTimeout(timer);
  }, [messageBuffer.length, dispatch]);

  // ── BGM ───────────────────────────────────────────
  useEffect(() => {
    audioRef.current = new Audio("/bgm.mp3");
    audioRef.current.loop = true;
    audioRef.current.volume = 0.3;
    return () => {
      audioRef.current?.pause();
      audioRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!audioRef.current?.src) return;
    if (state.bgmPlaying) {
      audioRef.current.play().catch(() => {});
    } else {
      audioRef.current.pause();
    }
  }, [state.bgmPlaying]);

  /* ── Handlers ─────────────────────────────────────── */

  const handleSend = useCallback(
    async (text: string) => {
      if (!gameId) return;

      const playerMsg: ChatMessage = {
        id: `local-${Date.now()}`,
        type: "player_speak",
        sender_id: state.playerCharacterId || "",
        sender_name: "你",
        content: text,
        choices: null,
        timestamp: Date.now() / 1000,
      };
      // Add directly to buffer and make visible immediately
      setMessageBuffer((prev) => [...prev, playerMsg]);
      setVisibleCount((c) => c + 1);
      setIsThinking(true);

      try {
        await playerAction(gameId, "speak", text);
        // Responses arrive via SSE
      } catch {
        setIsThinking(false);
      }
    },
    [gameId, state.playerCharacterId]
  );

  const handleChoiceSelect = useCallback(
    async (questionId: string, optionId: string) => {
      if (!gameId) return;
      setIsThinking(true);
      setWaitingForChoice(false); // unlock pacing

      try {
        await playerAction(gameId, "choice", optionId);
        // Responses (correct/wrong + next content) arrive via SSE
      } catch {
        setIsThinking(false);
      }
    },
    [gameId]
  );

  const handleVote = useCallback(
    async (roleId: string) => {
      if (!gameId) return;
      setIsThinking(true);

      try {
        await playerAction(gameId, "vote", roleId);
      } catch {
        setIsThinking(false);
      }
    },
    [gameId]
  );

  const handleBgmToggle = useCallback(() => {
    dispatch({ type: "TOGGLE_BGM" });
  }, [dispatch]);

  /* ── Derived data ─────────────────────────────────── */

  const title = state.session?.script?.title || "AI 剧本杀";
  // Detect voting phase from messages (more reliable than phase state)
  const isVoting =
    state.phase === "voting" ||
    visibleMessages.some(
      (m) => m.type === "dm_narration" && m.content.includes("选出凶手")
    );
  const isGenerating = state.phase === "generating";

  const allClues: Clue[] =
    state.session?.script?.acts.flatMap((a) => a.clues) ?? [];

  const lastMsg = visibleMessages[visibleMessages.length - 1];
  const currentSpeakerId = lastMsg?.sender_id || undefined;

  const voteOptions = (state.session?.script?.roles ?? [])
    .filter((r) => {
      const playerMapping = state.session?.mappings?.find(
        (m) => m.character_id === state.playerCharacterId
      );
      return r.id !== playerMapping?.role_id;
    })
    .map((r) => ({ id: r.id, name: r.name }));

  return (
    <div className="page game-page">
      <Header
        title={title}
        showBack
        onClueClick={() => setClueOpen(true)}
        bgmPlaying={state.bgmPlaying}
        onBgmToggle={handleBgmToggle}
      />

      {state.characters.length > 0 && (
        <AvatarRow
          characters={state.characters}
          mappings={state.session?.mappings}
          roles={state.session?.script?.roles}
          playerCharacterId={state.playerCharacterId}
          currentSpeakerId={currentSpeakerId}
        />
      )}

      <ChatArea
        messages={visibleMessages}
        characters={state.characters}
        playerCharacterId={state.playerCharacterId}
        isThinking={isThinking}
        onChoiceSelect={handleChoiceSelect}
      />

      {/* "下一条" button — hide during voting */}
      {showNextButton && !isVoting && (
        <div className="next-message-bar">
          <button className="next-message-btn" onClick={handleNextMessage}>
            下一条 ▼
          </button>
        </div>
      )}

      <InputBar
        onSend={handleSend}
        disabled={isThinking || isGenerating || waitingForChoice}
        votingMode={isVoting}
        voteOptions={voteOptions}
        onVote={handleVote}
      />

      <CluePanel
        clues={allClues}
        open={clueOpen}
        onClose={() => setClueOpen(false)}
      />

      <LoadingOverlay visible={visibleMessages.length === 0} stage="game" />
    </div>
  );
}
