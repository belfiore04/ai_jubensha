"""Structured game logger — JSONL file + colored terminal output."""
from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path
from typing import Any


# ── ANSI colors ───────────────────────────────────────
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    # foreground
    GOLD = "\033[33m"
    GREEN = "\033[32m"
    CYAN = "\033[36m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"
    RED = "\033[31m"
    MAGENTA = "\033[35m"
    BLUE = "\033[34m"


class GameLogger:
    """One logger per game session. Writes JSONL + prints to terminal."""

    def __init__(self, game_id: str, log_dir: str = "logs"):
        self.game_id = game_id
        self.start_time = time.time()
        self._llm_calls: list[dict] = []

        # ensure log directory
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        self._file_path = os.path.join(log_dir, f"game_{game_id[:8]}_{ts}.jsonl")
        self._file = open(self._file_path, "a", encoding="utf-8")

    # ── core write ────────────────────────────────────

    def _write(self, event_type: str, data: dict) -> None:
        record = {
            "ts": time.time(),
            "elapsed": round(time.time() - self.start_time, 2),
            "type": event_type,
            **data,
        }
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()

    # ── LLM call logging ─────────────────────────────

    def llm_start(self, name: str, system_prompt: str, user_prompt: str) -> dict:
        """Call before LLM. Returns a context dict to pass to llm_end."""
        ctx = {"name": name, "start": time.time()}
        self._print(f"{C.DIM}[LLM] {name} 调用中...{C.RESET}")
        return ctx

    def llm_end(self, ctx: dict, response: str, model: str = "") -> None:
        """Call after LLM completes."""
        duration = round(time.time() - ctx["start"], 1)
        name = ctx["name"]

        call_record = {
            "name": name,
            "model": model,
            "response_len": len(response),
            "duration_s": duration,
        }
        self._llm_calls.append(call_record)
        self._write("llm_call", call_record)
        self._print(f"{C.DIM}[LLM] {name} 完成 ({duration}s, {len(response)}字){C.RESET}")

    def llm_error(self, ctx: dict, error: Exception) -> None:
        """Call on LLM failure."""
        duration = round(time.time() - ctx["start"], 1)
        self._write("llm_error", {
            "name": ctx["name"],
            "error": str(error),
            "duration_s": duration,
        })
        self._print(f"{C.RED}[LLM] {ctx['name']} 失败 ({duration}s): {error}{C.RESET}")

    # ── game event logging ────────────────────────────

    def event(self, event_name: str, **details: Any) -> None:
        self._write("game_event", {"event": event_name, **details})

    # ── message logging (for terminal display) ────────

    def dm_narration(self, content: str) -> None:
        self._write("message", {"msg_type": "dm_narration", "content": content})
        self._print(f"\n{C.GOLD}{C.BOLD}[DM]{C.RESET} {C.GOLD}{content}{C.RESET}")

    def clue(self, content: str) -> None:
        self._write("message", {"msg_type": "clue", "content": content})
        self._print(f"{C.GREEN}  🔍 {content}{C.RESET}")

    def character_speak(self, char_name: str, role_name: str, content: str) -> None:
        self._write("message", {
            "msg_type": "character_speak",
            "char_name": char_name,
            "role_name": role_name,
            "content": content,
        })
        self._print(f"{C.CYAN}  [{char_name}({role_name})] {content}{C.RESET}")

    def player_speak(self, char_name: str, role_name: str, content: str) -> None:
        self._write("message", {
            "msg_type": "player_speak",
            "char_name": char_name,
            "role_name": role_name,
            "content": content,
        })
        self._print(f"{C.WHITE}{C.BOLD}  [{char_name}({role_name})] {content}{C.RESET}")

    def system(self, content: str) -> None:
        self._write("message", {"msg_type": "system", "content": content})
        self._print(f"{C.GRAY}  {content}{C.RESET}")

    def choice_result(self, correct: bool, explanation: str, score: int) -> None:
        self._write("message", {
            "msg_type": "choice_result",
            "correct": correct,
            "explanation": explanation,
            "score": score,
        })
        if correct:
            self._print(f"{C.GREEN}  ✅ 回答正确！+10分  {C.DIM}{explanation}{C.RESET}")
        else:
            self._print(f"{C.RED}  ❌ 回答错误。{C.DIM}{explanation}{C.RESET}")

    # ── error logging ─────────────────────────────────

    def error(self, error: Exception, context: str = "") -> None:
        tb = traceback.format_exception(type(error), error, error.__traceback__)
        self._write("error", {
            "context": context,
            "error": str(error),
            "traceback": "".join(tb),
        })
        self._print(f"{C.RED}[ERROR] {context}: {error}{C.RESET}")

    # ── summary ───────────────────────────────────────

    def summary(self, score: int, total_choices: int) -> None:
        total_time = round(time.time() - self.start_time, 1)
        llm_total = round(sum(c["duration_s"] for c in self._llm_calls), 1)
        llm_count = len(self._llm_calls)

        summary_data = {
            "total_time_s": total_time,
            "llm_calls": llm_count,
            "llm_total_time_s": llm_total,
            "score": score,
            "total_choices": total_choices,
            "calls_detail": self._llm_calls,
        }
        self._write("summary", summary_data)

        mins = int(total_time // 60)
        secs = int(total_time % 60)

        self._print(f"\n{C.BOLD}{'═' * 40}{C.RESET}")
        self._print(f"{C.BOLD}  本局统计{C.RESET}")
        self._print(f"{C.BOLD}{'═' * 40}{C.RESET}")
        self._print(f"  总耗时: {mins}m {secs}s")
        self._print(f"  LLM 调用: {llm_count}次, 总耗时 {llm_total}s")
        for c in self._llm_calls:
            self._print(f"    - {c['name']}: {c['duration_s']}s")
        self._print(f"  得分: {score}/{total_choices * 10}")
        self._print(f"  日志: {self._file_path}")
        self._print(f"{C.BOLD}{'═' * 40}{C.RESET}\n")

    # ── helpers ───────────────────────────────────────

    def section(self, title: str) -> None:
        """Print a visual section separator."""
        self._print(f"\n{C.MAGENTA}{C.BOLD}{'═' * 3} {title} {'═' * (35 - len(title))}{C.RESET}")

    def _print(self, text: str) -> None:
        print(text)

    def close(self) -> None:
        self._file.close()
