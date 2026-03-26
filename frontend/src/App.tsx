import { useReducer } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import {
  GameContext,
  gameReducer,
  initialGameState,
} from "./hooks/useGameStore";
import StyleSelectPage from "./pages/StyleSelectPage";
import RoleSelectPage from "./pages/RoleSelectPage";
import GameRoomPage from "./pages/GameRoomPage";
import EndingPage from "./pages/EndingPage";
import DebugPanel from "./components/DebugPanel";

export default function App() {
  const [state, dispatch] = useReducer(gameReducer, initialGameState);

  return (
    <GameContext.Provider value={{ state, dispatch }}>
      <BrowserRouter>
        <div className="app-shell">
          <Routes>
            <Route path="/style" element={<StyleSelectPage />} />
            <Route path="/roles" element={<RoleSelectPage />} />
            <Route path="/game/:id" element={<GameRoomPage />} />
            <Route path="/ending" element={<EndingPage />} />
            <Route path="*" element={<Navigate to="/style" replace />} />
          </Routes>
          <DebugPanel gameId={state.gameId} />
        </div>
      </BrowserRouter>
    </GameContext.Provider>
  );
}
