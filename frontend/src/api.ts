import type { GameSession, ScriptStyle } from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
const API = `${BASE}/api`;

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

/* ── Game lifecycle ───────────────────────────────── */

export function createGame(): Promise<GameSession> {
  return request<GameSession>(`${API}/game`, { method: "POST" });
}

export function getGame(gameId: string): Promise<GameSession> {
  return request<GameSession>(`${API}/game/${gameId}`);
}

export function setStyle(
  gameId: string,
  style: ScriptStyle
): Promise<GameSession> {
  return request<GameSession>(`${API}/game/${gameId}/style`, {
    method: "POST",
    body: JSON.stringify({ style }),
  });
}

export function startGame(
  gameId: string,
  playerRoleId: string,
  playerCharacterId: string
): Promise<{ messages: GameSession["messages"] }> {
  return request(`${API}/game/${gameId}/start`, {
    method: "POST",
    body: JSON.stringify({
      player_role_id: playerRoleId,
      player_character_id: playerCharacterId,
    }),
  });
}

export function playerAction(
  gameId: string,
  actionType: "speak" | "choice" | "vote",
  content: string
): Promise<{ messages: GameSession["messages"] }> {
  return request(`${API}/game/${gameId}/action`, {
    method: "POST",
    body: JSON.stringify({ action_type: actionType, content }),
  });
}

/* ── SSE helper ───────────────────────────────────── */

export function connectGameStream(
  gameId: string,
  onMessage: (data: string) => void,
  onError?: (e: Event) => void
): EventSource {
  const es = new EventSource(`${API}/game/${gameId}/stream`);
  es.addEventListener("message", (ev) => onMessage(ev.data));
  es.onerror = (e) => {
    if (onError) onError(e);
  };
  return es;
}
