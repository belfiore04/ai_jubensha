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

  const session = state.session;
  const characters = session?.characters ?? [];
  const playerCharacterId = session?.player_character_id ?? null;

  const [clueOpen, setClueOpen] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // ── Message pacing ──────────────────────────────────
  const [messageBuffer, setMessageBuffer] = useState<ChatMessage[]>([]);
  const [visibleCount, setVisibleCount] = useState(0);
  const [waitingForChoice, setWaitingForChoice] = useState(false);

  const visibleMessages = messageBuffer.slice(0, visibleCount);
  const hasMore = visibleCount < messageBuffer.length;
  const lastVisible = visibleMessages[visibleMessages.length - 1];
  const lastVisibleIsChoice = lastVisible?.type === "choice";
  const showNextButton = hasMore && !lastVisibleIsChoice && !waitingForChoice;

  const dmNarrationCount = visibleMessages.filter(
    (m) => m.type === "dm_narration"
  ).length;

  // Auto-advance: system msgs, player/character msgs, and the first DM (prologue)
  useEffect(() => {
    if (visibleCount >= messageBuffer.length) return;
    const nextMsg = messageBuffer[visibleCount];
    if (!nextMsg) return;

    const isPaced = PACED_TYPES.has(nextMsg.type);
    const isFirstDM = nextMsg.type === "dm_narration" && dmNarrationCount === 0;

    if (!isPaced || isFirstDM) {
      setVisibleCount((c) => c + 1);
    }
  }, [messageBuffer, visibleCount, dmNarrationCount]);

  function handleNextMessage() {
    if (visibleCount < messageBuffer.length) {
      const nextMsg = messageBuffer[visibleCount];
      setVisibleCount((c) => c + 1);
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
        const sess = await getGame(gameId!);
        dispatch({ type: "SET_SESSION", payload: sess });

        if (sess.messages?.length) {
          setMessageBuffer((prev) => {
            const existingIds = new Set(prev.map((m) => m.id));
            const newMsgs = sess.messages.filter((m: ChatMessage) => !existingIds.has(m.id));
            return [...prev, ...newMsgs];
          });
        }

        // If no messages yet (start_game still running), poll until they arrive
        if (!sess.messages?.length) {
          const poll = setInterval(async () => {
            try {
              const s = await getGame(gameId!);
              if (s.messages?.length) {
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
          if (msg.type === "player_speak") return;
          setMessageBuffer((prev) => {
            if (prev.some((m) => m.id === msg.id)) return prev;
            return [...prev, msg];
          });
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
  }, [gameId, navigate, dispatch]);

  // Auto-reveal first message
  useEffect(() => {
    if (messageBuffer.length > 0 && visibleCount === 0) {
      setVisibleCount(1);
    }
  }, [messageBuffer.length, visibleCount]);

  // Timeout: if no messages after 120s, show error
  useEffect(() => {
    if (messageBuffer.length > 0) return;
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
        sender_id: playerCharacterId || "",
        sender_name: "你",
        content: text,
        choices: null,
        timestamp: Date.now() / 1000,
      };
      setMessageBuffer((prev) => [...prev, playerMsg]);
      setVisibleCount((c) => c + 1);
      setIsThinking(true);

      try {
        await playerAction(gameId, "speak", text);
      } catch {
        setIsThinking(false);
      }
    },
    [gameId, playerCharacterId]
  );

  const handleChoiceSelect = useCallback(
    async (questionId: string, optionId: string) => {
      if (!gameId) return;
      setIsThinking(true);
      setWaitingForChoice(false);

      try {
        await playerAction(gameId, "choice", optionId);
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

  const title = session?.script?.title || "AI 剧本杀";
  const phase = session?.phase;

  const isVoting =
    phase === "voting" ||
    visibleMessages.some(
      (m) => m.type === "dm_narration" && m.content.includes("选出凶手")
    );
  const isGenerating = phase === "generating";

  const allClues: Clue[] =
    session?.script?.acts.flatMap((a) => a.clues) ?? [];

  const lastMsg = visibleMessages[visibleMessages.length - 1];
  const currentSpeakerId = lastMsg?.sender_id || undefined;

  const voteOptions = (session?.script?.roles ?? [])
    .filter((r) => {
      const playerMapping = session?.mappings?.find(
        (m) => m.character_id === playerCharacterId
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

      {characters.length > 0 && (
        <AvatarRow
          characters={characters}
          mappings={session?.mappings}
          roles={session?.script?.roles}
          playerCharacterId={playerCharacterId}
          currentSpeakerId={currentSpeakerId}
        />
      )}

      <ChatArea
        messages={visibleMessages}
        characters={characters}
        playerCharacterId={playerCharacterId}
        isThinking={isThinking}
        onChoiceSelect={handleChoiceSelect}
      />

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
