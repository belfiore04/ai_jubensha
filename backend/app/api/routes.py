"""FastAPI routes for the murder-mystery game."""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.engine.game_engine import GameEngine
from app.models.game import (
    GameSession,
    ScriptStyle,
)
from app.generator.script_generator import STYLE_LABELS

router = APIRouter(prefix="/api")

# single engine instance (shared in-memory store)
engine = GameEngine()


# ── request / response schemas ─────────────────────────

class SetStyleRequest(BaseModel):
    style: ScriptStyle


class StartGameRequest(BaseModel):
    player_role_id: str
    player_character_id: str


class PlayerActionRequest(BaseModel):
    action_type: str   # "speak" | "choice" | "vote"
    content: str


class StyleInfo(BaseModel):
    value: str
    label: str


# ── routes ─────────────────────────────────────────────

@router.get("/styles", response_model=list[StyleInfo])
async def list_styles():
    """Return available script styles."""
    return [
        StyleInfo(value=s.value, label=STYLE_LABELS[s])
        for s in ScriptStyle
    ]


@router.post("/game", response_model=GameSession)
async def create_game():
    """Create a new game session."""
    return engine.create_game()


@router.get("/game/{game_id}", response_model=GameSession)
async def get_game(game_id: str):
    """Get current game state."""
    try:
        return engine.get_state(game_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Game not found")


@router.post("/game/{game_id}/style", response_model=GameSession)
async def set_style(game_id: str, req: SetStyleRequest):
    """Set the narrative style and generate the script outline."""
    try:
        return await engine.set_style(game_id, req.style)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/game/{game_id}/start")
async def start_game(game_id: str, req: StartGameRequest):
    """Player picks a role, characters are assigned, and the game begins."""
    try:
        messages = await engine.start_game(
            game_id, req.player_role_id, req.player_character_id
        )
        return {"messages": [m.model_dump() for m in messages]}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/game/{game_id}/action")
async def player_action(game_id: str, req: PlayerActionRequest):
    """Player performs an action (speak / choice / vote)."""
    try:
        messages = await engine.player_action(
            game_id, req.action_type, req.content
        )
        return {"messages": [m.model_dump() for m in messages]}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── SSE stream ─────────────────────────────────────────

@router.get("/game/{game_id}/stream")
async def game_stream(game_id: str, request: Request):
    """SSE endpoint – pushes ChatMessage objects as JSON events."""
    try:
        engine.get_state(game_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Game not found")

    queue = engine.get_message_queue(game_id)

    async def event_generator():
        while True:
            # check if client disconnected
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield {
                    "event": "message",
                    "data": msg.model_dump_json(),
                }
            except asyncio.TimeoutError:
                # send keepalive
                yield {"event": "ping", "data": ""}

    return EventSourceResponse(event_generator())


@router.get("/game/{game_id}/debug")
async def game_debug_stream(game_id: str, request: Request):
    """SSE endpoint for debug logs."""
    try:
        engine.get_state(game_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Game not found")

    queue = engine.get_debug_queue(game_id)

    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            try:
                log = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield {
                    "event": "debug",
                    "data": json.dumps(log, ensure_ascii=False),
                }
            except asyncio.TimeoutError:
                yield {"event": "ping", "data": ""}

    return EventSourceResponse(event_generator())
