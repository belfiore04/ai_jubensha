import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useGame } from "../hooks/useGameStore";
import { PLATFORM_CHARACTERS } from "../data";
import { startGame } from "../api";
import Header from "../components/Header";
import LoadingOverlay from "../components/LoadingOverlay";
import "./RoleSelectPage.css";

export default function RoleSelectPage() {
  const navigate = useNavigate();
  const { state, dispatch } = useGame();
  const [selectedRoleId, setSelectedRoleId] = useState<string | null>(null);

  const roles = state.session?.script?.roles ?? [];
  const isGenerating = state.session?.phase === "generating";

  // Pick a random default character for the player (first one)
  const playerCharacterId = PLATFORM_CHARACTERS[0].id;

  function handleStart() {
    if (!selectedRoleId || !state.gameId) return;

    // Fire-and-forget: start game in background, navigate immediately
    // GameRoom will pick up messages via SSE as they arrive
    startGame(state.gameId, selectedRoleId, playerCharacterId).catch(() => {});

    navigate(`/game/${state.gameId}`);
  }

  return (
    <div className="page character-page">
      <Header title="选择角色" showBack />

      <div className="character-page-body">
        {isGenerating ? (
          <p className="character-page-hint">正在生成剧本大纲，请稍候...</p>
        ) : roles.length === 0 ? (
          <p className="character-page-hint">暂无角色信息，请先选择风格</p>
        ) : (
          <>
            <p className="character-page-hint">
              选择一个你想扮演的剧本角色
            </p>

            <div className="character-list">
              {roles.map((role) => {
                const isSelected = selectedRoleId === role.id;
                return (
                  <button
                    key={role.id}
                    className={`character-card ${
                      isSelected ? "character-card--selected" : ""
                    }`}
                    onClick={() => setSelectedRoleId(role.id)}
                  >
                    <div className="role-icon">
                      {role.name.charAt(0)}
                    </div>
                    <div className="character-card-info">
                      <div className="character-card-name">{role.name}</div>
                      <div className="character-card-personality">
                        {role.background}
                      </div>
                    </div>
                    {isSelected && (
                      <span className="character-card-badge">我要扮演</span>
                    )}
                  </button>
                );
              })}
            </div>

            <button
              className="start-btn"
              disabled={!selectedRoleId || state.loading}
              onClick={handleStart}
            >
              {state.loading ? "准备中..." : "开始游戏"}
            </button>
          </>
        )}

        {state.error && <p className="error-text">{state.error}</p>}
      </div>

      <LoadingOverlay visible={isGenerating || state.loading} />
    </div>
  );
}
