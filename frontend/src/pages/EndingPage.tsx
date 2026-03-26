import { useNavigate } from "react-router-dom";
import { useGame } from "../hooks/useGameStore";
import "./EndingPage.css";

export default function EndingPage() {
  const navigate = useNavigate();
  const { state, dispatch } = useGame();

  const script = state.session?.script;
  const score = state.session?.score ?? 0;

  // Find the murderer role name
  const murdererRole = script?.roles.find(
    (r) => r.id === script.murderer_role_id
  );

  // Find the character mapped to the murderer role
  const murdererMapping = state.session?.mappings.find(
    (m) => m.role_id === script?.murderer_role_id
  );
  const murdererCharacter = state.characters.find(
    (c) => c.id === murdererMapping?.character_id
  );

  function handleReplay() {
    dispatch({ type: "RESET" });
    navigate("/style");
  }

  return (
    <div className="page ending-page">
      <div className="ending-content">
        <div className="ending-badge">~ 终幕 ~</div>

        <h1 className="ending-title">{script?.title || "游戏结束"}</h1>

        {script?.truth && (
          <div className="ending-section">
            <h2 className="ending-section-title">真相揭晓</h2>
            <p className="ending-truth">{script.truth}</p>
          </div>
        )}

        {murdererRole && (
          <div className="ending-section">
            <h2 className="ending-section-title">凶手</h2>
            <div className="ending-murderer">
              <span className="ending-murderer-icon">&#128128;</span>
              <div>
                <div className="ending-murderer-name">
                  {murdererCharacter?.name ?? "???"} ({murdererRole.name})
                </div>
                <div className="ending-murderer-bg">
                  {murdererRole.background}
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="ending-section">
          <h2 className="ending-section-title">你的得分</h2>
          <div className="ending-score">{score}</div>
        </div>

        <button className="replay-btn" onClick={handleReplay}>
          再来一局
        </button>
      </div>
    </div>
  );
}
