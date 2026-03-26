/**
 * Simple global game store using React context + useReducer.
 * Avoids external state libraries to keep deps minimal.
 */
import { createContext, useContext } from "react";
import type {
  GameSession,
  ChatMessage,
  Character,
  ScriptStyle,
  GamePhase,
} from "../types";

/* ── State ────────────────────────────────────────── */

export interface GameState {
  gameId: string | null;
  phase: GamePhase;
  style: ScriptStyle | null;
  characters: Character[];
  playerCharacterId: string | null;
  session: GameSession | null;
  messages: ChatMessage[];
  loading: boolean;
  error: string | null;
  bgmPlaying: boolean;
}

export const initialGameState: GameState = {
  gameId: null,
  phase: "style_select",
  style: null,
  characters: [],
  playerCharacterId: null,
  session: null,
  messages: [],
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
  | { type: "SET_STYLE"; payload: ScriptStyle }
  | { type: "SET_CHARACTERS"; payload: Character[] }
  | { type: "SET_PLAYER_CHARACTER"; payload: string }
  | { type: "SET_PHASE"; payload: GamePhase }
  | { type: "ADD_MESSAGES"; payload: ChatMessage[] }
  | { type: "ADD_MESSAGE"; payload: ChatMessage }
  | { type: "SET_MESSAGES_DIRECT"; payload: ChatMessage[] }
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
        phase: action.payload.phase,
        style: action.payload.style,
        characters: action.payload.characters,
        playerCharacterId: action.payload.player_character_id || state.playerCharacterId,
        messages: action.payload.messages.length > 0 ? action.payload.messages : state.messages,
        loading: false,
      };
    case "SET_GAME_ID":
      return { ...state, gameId: action.payload };
    case "SET_STYLE":
      return { ...state, style: action.payload };
    case "SET_CHARACTERS":
      return { ...state, characters: action.payload };
    case "SET_PLAYER_CHARACTER":
      return { ...state, playerCharacterId: action.payload };
    case "SET_PHASE":
      return { ...state, phase: action.payload };
    case "ADD_MESSAGES": {
      const existingIds = new Set(state.messages.map((m) => m.id));
      const newMsgs = action.payload.filter((m) => !existingIds.has(m.id));
      return { ...state, messages: [...state.messages, ...newMsgs] };
    }
    case "ADD_MESSAGE": {
      if (state.messages.some((m) => m.id === action.payload.id)) return state;
      return { ...state, messages: [...state.messages, action.payload] };
    }
    case "SET_MESSAGES_DIRECT":
      return { ...state, messages: action.payload };
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
