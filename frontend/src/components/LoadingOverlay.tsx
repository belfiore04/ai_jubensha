import { useState, useEffect, useRef } from "react";
import "./LoadingOverlay.css";

/**
 * Loading stages with estimated durations (seconds).
 * The progress bar advances through stages based on elapsed time.
 */
interface LoadingStage {
  label: string;
  duration: number; // estimated seconds
}

const OUTLINE_STAGES: LoadingStage[] = [
  { label: "正在构思剧本世界观...", duration: 15 },
  { label: "创建角色与背景故事...", duration: 15 },
  { label: "设计核心诡计与线索...", duration: 10 },
  { label: "最后打磨中...", duration: 10 },
];

const GAME_STAGES: LoadingStage[] = [
  { label: "正在生成第一幕剧情...", duration: 15 },
  { label: "布置现场线索...", duration: 10 },
  { label: "准备推理题目...", duration: 10 },
  { label: "即将开始...", duration: 5 },
];

interface LoadingOverlayProps {
  visible: boolean;
  /** "outline" for style→roles, "game" for role→gameroom */
  stage?: "outline" | "game";
}

export default function LoadingOverlay({
  visible,
  stage = "outline",
}: LoadingOverlayProps) {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(Date.now());

  // Reset timer when visibility changes
  useEffect(() => {
    if (visible) {
      startRef.current = Date.now();
      setElapsed(0);
    }
  }, [visible]);

  // Tick every second
  useEffect(() => {
    if (!visible) return;
    const timer = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startRef.current) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, [visible]);

  if (!visible) return null;

  const stages = stage === "outline" ? OUTLINE_STAGES : GAME_STAGES;
  const totalDuration = stages.reduce((s, st) => s + st.duration, 0);

  // Calculate which stage we're in and overall progress
  let accum = 0;
  let currentStageIndex = stages.length - 1;
  for (let i = 0; i < stages.length; i++) {
    if (elapsed < accum + stages[i].duration) {
      currentStageIndex = i;
      break;
    }
    accum += stages[i].duration;
  }

  // Progress: 0-95% based on time (never hits 100 until actually done)
  const rawProgress = Math.min(elapsed / totalDuration, 1);
  const displayProgress = Math.min(rawProgress * 95, 95);

  const currentLabel = stages[currentStageIndex].label;

  return (
    <div className="loading-overlay">
      <div className="loading-content">
        <div className="loading-spinner">
          <div className="spinner-ring" />
          <div className="spinner-ring spinner-ring--delay" />
        </div>

        <p className="loading-text">{currentLabel}</p>

        <div className="progress-container">
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{ width: `${displayProgress}%` }}
            />
          </div>
          <div className="progress-info">
            <span className="progress-percent">
              {Math.round(displayProgress)}%
            </span>
            <span className="progress-time">{elapsed}s</span>
          </div>
        </div>

        <div className="stage-dots">
          {stages.map((_, i) => (
            <span
              key={i}
              className={`stage-dot ${
                i < currentStageIndex
                  ? "stage-dot--done"
                  : i === currentStageIndex
                  ? "stage-dot--active"
                  : ""
              }`}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
