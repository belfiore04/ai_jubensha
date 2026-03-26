/* ── Enums ─────────────────────────────────────────── */

export type ScriptStyle =
  | "detective"
  | "drama"
  | "discover"
  | "destiny"
  | "dream"
  | "dimension"
  | "death";

export type RoleAlignment = "innocent" | "murderer";

export type GamePhase =
  | "style_select"
  | "character_select"
  | "generating"
  | "role_assign"
  | "act_1"
  | "act_2"
  | "act_3"
  | "voting"
  | "ending";

export type MessageType =
  | "dm_narration"
  | "character_speak"
  | "player_speak"
  | "system"
  | "clue"
  | "choice"
  | "vote";

/* ── Characters & Roles ───────────────────────────── */

export interface Character {
  id: string;
  name: string;
  avatar: string;
  personality: string;
  description: string;
}

export interface Role {
  id: string;
  name: string;
  alignment: RoleAlignment;
  background: string;
  secret: string;
  clues: string[];
}

export interface CharacterRoleMapping {
  character_id: string;
  role_id: string;
  is_player: boolean;
}

/* ── Game Content ─────────────────────────────────── */

export interface Clue {
  id: string;
  title: string;
  content: string;
  act: number;
  revealed: boolean;
}

export interface ChoiceOption {
  id: string;
  text: string;
  is_correct: boolean;
}

export interface ChoiceQuestion {
  id: string;
  question: string;
  options: ChoiceOption[];
  explanation: string;
}

export interface Act {
  act_number: number;
  title: string;
  narration: string;
  clues: Clue[];
  choices: ChoiceQuestion[];
  generated: boolean;
}

export interface Script {
  style: ScriptStyle;
  title: string;
  prologue: string;
  acts: Act[];
  roles: Role[];
  truth: string;
  murderer_role_id: string;
}

/* ── Chat Messages ────────────────────────────────── */

export interface ChatMessage {
  id: string;
  type: MessageType;
  sender_id: string;
  sender_name: string;
  content: string;
  choices: ChoiceQuestion | null;
  timestamp: number;
}

/* ── Game Session ─────────────────────────────────── */

export interface GameSession {
  id: string;
  phase: GamePhase;
  style: ScriptStyle | null;
  characters: Character[];
  mappings: CharacterRoleMapping[];
  script: Script | null;
  messages: ChatMessage[];
  current_act: number;
  score: number;
  player_character_id: string;
}

/* ── Style metadata (for UI) ──────────────────────── */

export interface StyleCard {
  value: ScriptStyle;
  label: string;
  emoji: string;
  desc: string;
}
