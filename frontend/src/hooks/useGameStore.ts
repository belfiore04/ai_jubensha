/**
 * Minimal global game store — session is the single source of truth.
 */
import { createContext, useContext } from "react";
import type { GameSession } from "../types";

/* ── State ────────────────────────────────────────── */

export interface GameState {
  gameId: string | null;
  session: GameSession | null;
  loading: boolean;
  error: string | null;
  bgmPlaying: boolean;
}

export const initialGameState: GameState = {
  gameId: null,
  session: null,
  loading: false,
  error: null,
  bgmPlaying: false,
};

/* ── Actions ──────────────────────────────────────── */

export type GameAction =
  | { type: "SET_LOADING"; payload: boolean }
  | { type: "SET_ERROR"; payload: string | null }
  | { type: "SET_SESSION"; payload: GameSession }
  | { type: "SET_GAME_ID"; payload: string }
  | { type: "TOGGLE_BGM" }
  | { type: "RESET" };

export function gameReducer(state: GameState, action: GameAction): GameState {
  switch (action.type) {
    case "SET_LOADING":
      return { ...state, loading: action.payload };
    case "SET_ERROR":
      return { ...state, error: action.payload, loading: false };
    case "SET_SESSION":
      return {
        ...state,
        session: action.payload,
        gameId: action.payload.id,
        loading: false,
      };
    case "SET_GAME_ID":
      return { ...state, gameId: action.payload };
    case "TOGGLE_BGM":
      return { ...state, bgmPlaying: !state.bgmPlaying };
    case "RESET":
      return initialGameState;
    default:
      return state;
  }
}

/* ── Context ──────────────────────────────────────── */

export interface GameContextValue {
  state: GameState;
  dispatch: React.Dispatch<GameAction>;
}

export const GameContext = createContext<GameContextValue | null>(null);

export function useGame(): GameContextValue {
  const ctx = useContext(GameContext);
  if (!ctx) throw new Error("useGame must be used within GameProvider");
  return ctx;
}
