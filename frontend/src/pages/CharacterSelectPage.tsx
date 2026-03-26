import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useGame } from "../hooks/useGameStore";
import { DEMO_CHARACTERS } from "../data";
import { setCharacters } from "../api";
import Avatar from "../components/Avatar";
import Header from "../components/Header";
import LoadingOverlay from "../components/LoadingOverlay";
import "./CharacterSelectPage.css";

export default function CharacterSelectPage() {
  const navigate = useNavigate();
  const { state, dispatch } = useGame();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  async function handleStart() {
    if (!selectedId || !state.gameId) return;

    try {
      dispatch({ type: "SET_LOADING", payload: true });
      dispatch({ type: "SET_PLAYER_CHARACTER", payload: selectedId });

      // Send all 4 characters to the backend; selected one is the player
      const chars = DEMO_CHARACTERS.map((c) => ({
        ...c,
      }));

      const updated = await setCharacters(state.gameId, chars);
      dispatch({ type: "SET_SESSION", payload: updated });

      // Navigate to game room
      navigate(`/game/${state.gameId}`);
    } catch (err) {
      dispatch({
        type: "SET_ERROR",
        payload: err instanceof Error ? err.message : "开始游戏失败",
      });
    }
  }

  return (
    <div className="page character-page">
      <Header title="选择角色" showBack />

      <div className="character-page-body">
        <p className="character-page-hint">
          选择一个你想扮演的角色，其余由 AI 控制
        </p>

        <div className="character-list">
          {DEMO_CHARACTERS.map((char) => {
            const isSelected = selectedId === char.id;
            return (
              <button
                key={char.id}
                className={`character-card ${
                  isSelected ? "character-card--selected" : ""
                }`}
                onClick={() => setSelectedId(char.id)}
              >
                <Avatar
                  id={char.id}
                  name={char.name}
                  size={56}
                  active={isSelected}
                />
                <div className="character-card-info">
                  <div className="character-card-name">{char.name}</div>
                  <div className="character-card-desc">{char.description}</div>
                  <div className="character-card-personality">
                    {char.personality}
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
          disabled={!selectedId || state.loading}
          onClick={handleStart}
        >
          {state.loading ? "准备中..." : "开始游戏"}
        </button>

        {state.error && <p className="error-text">{state.error}</p>}
      </div>

      <LoadingOverlay visible={state.loading} />
    </div>
  );
}
