import type { Clue } from "../types";
import "./CluePanel.css";

interface CluePanelProps {
  clues: Clue[];
  open: boolean;
  onClose: () => void;
}

export default function CluePanel({ clues, open, onClose }: CluePanelProps) {
  const revealedClues = clues.filter((c) => c.revealed);

  return (
    <>
      {open && <div className="clue-overlay" onClick={onClose} />}
      <div className={`clue-panel ${open ? "clue-panel--open" : ""}`}>
        <div className="clue-panel-header">
          <h2 className="clue-panel-title">已收集线索</h2>
          <button className="clue-panel-close" onClick={onClose}>
            &times;
          </button>
        </div>

        <div className="clue-panel-body">
          {revealedClues.length === 0 ? (
            <div className="clue-panel-empty">
              <span className="clue-panel-empty-icon">&#128270;</span>
              <p>暂未收集到线索</p>
              <p className="clue-panel-empty-hint">
                随着剧情推进，线索会逐步出现
              </p>
            </div>
          ) : (
            <div className="clue-list">
              {revealedClues.map((clue) => (
                <div key={clue.id} className="clue-item">
                  <div className="clue-item-act">第{clue.act}幕</div>
                  <div className="clue-item-title">{clue.title}</div>
                  <div className="clue-item-content">{clue.content}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
