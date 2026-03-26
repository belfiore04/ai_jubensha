import { useNavigate } from "react-router-dom";
import { useGame } from "../hooks/useGameStore";
import { STYLES } from "../data";
import { createGame, setStyle } from "../api";
import type { ScriptStyle } from "../types";
import LoadingOverlay from "../components/LoadingOverlay";
import "./StyleSelectPage.css";

export default function StyleSelectPage() {
  const navigate = useNavigate();
  const { state, dispatch } = useGame();

  async function handleSelect(style: ScriptStyle) {
    try {
      dispatch({ type: "SET_LOADING", payload: true });

      // Create a new game if we don't have one yet
      let gameId = state.gameId;
      if (!gameId) {
        const session = await createGame();
        dispatch({ type: "SET_GAME_ID", payload: session.id });
        gameId = session.id;
      }

      // Set the style (triggers LLM outline generation — takes ~30-50s)
      // Keep loading=true throughout
      const updated = await setStyle(gameId, style);
      dispatch({ type: "SET_SESSION", payload: updated });

      navigate("/roles");
    } catch (err) {
      dispatch({
        type: "SET_ERROR",
        payload: err instanceof Error ? err.message : "选择风格失败",
      });
    }
  }

  function handleRandom() {
    const randomIndex = Math.floor(Math.random() * STYLES.length);
    handleSelect(STYLES[randomIndex].value);
  }

  return (
    <div className="page style-page">
      <div className="style-page-header">
        <h1 className="style-page-title">AI 剧本杀</h1>
        <p className="style-page-subtitle">选择你喜欢的剧本风格</p>
      </div>

      <div className="style-grid">
        {STYLES.map((s) => (
          <button
            key={s.value}
            className="style-card"
            onClick={() => handleSelect(s.value)}
            disabled={state.loading}
          >
            <span className="style-card-emoji">{s.emoji}</span>
            <span className="style-card-label">{s.label}</span>
            <span className="style-card-desc">{s.desc}</span>
          </button>
        ))}
      </div>

      <button
        className="random-btn"
        onClick={handleRandom}
        disabled={state.loading}
      >
        <span className="random-btn-emoji">&#127922;</span>
        <span>随机选择</span>
      </button>

      {state.error && <p className="error-text">{state.error}</p>}

      <LoadingOverlay visible={state.loading} stage="outline" />
    </div>
  );
}
