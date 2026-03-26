"""FastAPI application entry point."""
from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

# [Langfuse] 全局 Monkey Patch — 必须在导入使用 openai 的模块之前
import openai
from langfuse.openai import AsyncOpenAI as LangfuseAsyncOpenAI
openai.AsyncOpenAI = LangfuseAsyncOpenAI  # type: ignore[misc]

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router

app = FastAPI(
    title="AI Murder Mystery",
    description="AI驱动的剧本杀游戏后端",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
async def root():
    return {"status": "ok", "message": "AI Murder Mystery API"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
