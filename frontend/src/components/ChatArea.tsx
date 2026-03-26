import { useEffect, useRef, useState } from "react";
import type { ChatMessage, Character, ChoiceQuestion } from "../types";
import Avatar from "./Avatar";
import "./ChatArea.css";

interface ChatAreaProps {
  messages: ChatMessage[];
  characters: Character[];
  playerCharacterId: string | null;
  isThinking: boolean;
  onChoiceSelect?: (questionId: string, optionId: string) => void;
}

export default function ChatArea({
  messages,
  characters,
  playerCharacterId,
  isThinking,
  onChoiceSelect,
}: ChatAreaProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isThinking]);

  function findCharacter(id: string): Character | undefined {
    return characters.find((c) => c.id === id);
  }

  function renderMessage(msg: ChatMessage, index: number) {
    switch (msg.type) {
      case "dm_narration": {
        // Check if this is an act header (contains 【第X幕】)
        const actMatch = msg.content.match(/【第[一二三]幕[：:]/);
        return (
          <div key={msg.id || index}>
            {actMatch && (
              <div className="act-separator">
                <span className="act-separator-line" />
                <span className="act-separator-text">{actMatch[0].replace(/[【：:]/g, '')}</span>
                <span className="act-separator-line" />
              </div>
            )}
            <div className="msg msg-dm animate-in">
              <div className="msg-dm-label">DM</div>
              <div className="msg-dm-content">{msg.content}</div>
            </div>
          </div>
        );
      }

      case "system": {
        const isLoading = msg.content.includes("正在生成") || msg.content.includes("正在进入") || msg.content.includes("即将进入");
        const isLast = index === messages.length - 1;
        // Show progress only on loading messages. If it's the last message, it's active.
        // If it's NOT the last message, generation is done — show completed state briefly.
        const showProgress = isLoading;
        const isCompleted = isLoading && !isLast;
        return (
          <div key={msg.id || index} className="msg msg-system animate-in">
            {msg.content}
            {showProgress && <InlineProgress duration={35} completed={isCompleted} />}
          </div>
        );
      }

      case "clue":
        return (
          <div key={msg.id || index} className="msg msg-clue animate-in">
            <div className="clue-card">
              <div className="clue-card-header">
                <span className="clue-icon">&#128270;</span>
                <span>线索发现</span>
              </div>
              <div className="clue-card-body">{msg.content}</div>
            </div>
          </div>
        );

      case "choice":
        return (
          <div key={msg.id || index} className="msg msg-choice animate-in">
            {msg.choices && (
              <ChoiceCard
                question={msg.choices}
                onSelect={(optId) =>
                  onChoiceSelect?.(msg.choices!.id, optId)
                }
              />
            )}
          </div>
        );

      case "player_speak":
        return (
          <div key={msg.id || index} className="msg msg-player animate-in">
            <div className="msg-bubble msg-bubble-player">
              {msg.content}
            </div>
            <Avatar
              id={playerCharacterId || "player"}
              name={msg.sender_name || "你"}
              size={32}
            />
          </div>
        );

      case "character_speak":
      default: {
        const char = findCharacter(msg.sender_id);
        return (
          <div key={msg.id || index} className="msg msg-character animate-in">
            <Avatar
              id={msg.sender_id}
              name={msg.sender_name || "???"}
              avatar={char?.avatar || undefined}
              size={32}
            />
            <div className="msg-character-body">
              <span className="msg-sender-name">{msg.sender_name}</span>
              <div className="msg-bubble msg-bubble-character">
                {msg.content}
              </div>
            </div>
          </div>
        );
      }
    }
  }

  return (
    <div className="chat-area">
      {messages.map(renderMessage)}

      {isThinking && (
        <div className="msg msg-character animate-in">
          <Avatar id="dm" name="DM" size={32} />
          <div className="msg-character-body">
            <div className="msg-bubble msg-bubble-character">
              <span className="typing-dots">
                <span className="dot" />
                <span className="dot" />
                <span className="dot" />
              </span>
            </div>
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}

/* ── ChoiceCard sub-component ─────────────────────── */

function ChoiceCard({
  question,
  onSelect,
}: {
  question: ChoiceQuestion;
  onSelect: (optionId: string) => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  function handleClick(optId: string) {
    if (selectedId) return; // already answered
    setSelectedId(optId);
    onSelect(optId);
  }

  return (
    <div className="choice-card">
      <div className="choice-question">{question.question}</div>
      <div className="choice-options">
        {(question.options ?? []).map((opt) => (
          <button
            key={opt.id}
            className={`choice-option-btn ${
              selectedId === opt.id ? "choice-option-btn--selected" : ""
            } ${selectedId && selectedId !== opt.id ? "choice-option-btn--disabled" : ""}`}
            onClick={() => handleClick(opt.id)}
            disabled={!!selectedId}
          >
            {opt.text}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ── InlineProgress sub-component ────────────────── */

function InlineProgress({
  duration,
  completed = false,
}: {
  duration: number;
  completed?: boolean;
}) {
  const [elapsed, setElapsed] = useState(0);
  const [hidden, setHidden] = useState(false);
  const startRef = useRef(Date.now());

  useEffect(() => {
    if (completed) return; // stop ticking when completed
    const timer = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startRef.current) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, [completed]);

  // When completed, animate to 100% then hide after a short delay
  useEffect(() => {
    if (!completed) return;
    const timer = setTimeout(() => setHidden(true), 800);
    return () => clearTimeout(timer);
  }, [completed]);

  if (hidden) return null;

  const progress = completed ? 100 : Math.min((elapsed / duration) * 95, 95);

  return (
    <div className="inline-progress">
      <div className="inline-progress-bar">
        <div
          className="inline-progress-fill"
          style={{ width: `${progress}%` }}
        />
      </div>
      <span className="inline-progress-text">
        {completed ? "✓" : `${elapsed}s`}
      </span>
    </div>
  );
}
