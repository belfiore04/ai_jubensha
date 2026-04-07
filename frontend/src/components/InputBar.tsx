import { useState, type FormEvent } from "react";
import "./InputBar.css";

interface InputBarProps {
  onSend: (text: string) => void;
  disabled?: boolean;
  placeholder?: string;
  votingMode?: boolean;
  voteOptions?: { id: string; name: string }[];
  onVote?: (characterId: string) => void;
  discussionMode?: boolean;
  onEndDiscussion?: () => void;
}

export default function InputBar({
  onSend,
  disabled = false,
  placeholder = "输入你想说的话...",
  votingMode = false,
  voteOptions = [],
  onVote,
  discussionMode = false,
  onEndDiscussion,
}: InputBarProps) {
  const [text, setText] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
  }

  if (votingMode && voteOptions.length > 0) {
    return (
      <div className="input-bar input-bar--voting">
        <span className="vote-label">投票选出凶手：</span>
        <div className="vote-buttons">
          {voteOptions.map((opt) => (
            <button
              key={opt.id}
              className="vote-btn"
              onClick={() => onVote?.(opt.id)}
            >
              {opt.name}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <form className="input-bar" onSubmit={handleSubmit}>
      <input
        className="input-field"
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={discussionMode ? "参与讨论，或结束讨论进入推理..." : placeholder}
        disabled={disabled}
      />
      {discussionMode && (
        <button
          className="end-discussion-btn"
          type="button"
          onClick={onEndDiscussion}
          disabled={disabled}
        >
          结束讨论
        </button>
      )}
      <button
        className="send-btn"
        type="submit"
        disabled={disabled || !text.trim()}
      >
        发送
      </button>
    </form>
  );
}
