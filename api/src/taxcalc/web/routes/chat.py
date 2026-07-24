"""`/chat` — streams the model reply as a **domain event stream** (SSE JSON lines).

FastAPI owns the model (and, later, the agent loop). It emits a stable,
framework-agnostic event schema — ``{"type": "text-delta", "delta": ...}`` today,
plus ``tool_call`` / ``source`` events when the read-only agent lands — so the
frontend transport is never coupled to the Anthropic or Vercel wire format. The
Next.js route handler translates these events into the Vercel AI SDK UI Message
Stream Protocol. Adding event types here is additive on both sides.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from taxcalc.web.config import get_settings

router = APIRouter()

_SYSTEM = (
    "You are a helpful assistant for a UK crypto Capital Gains Tax calculation "
    "and reporting aid. You are read-only and never perform arithmetic on the "
    "user's figures. This is not tax advice."
)


class ChatRequest(BaseModel):
    message: str


def _sse(payload: dict[str, str]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _event_stream(message: str) -> AsyncIterator[str]:
    settings = get_settings()
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    async with client.messages.stream(
        model=settings.anthropic_model,
        max_tokens=1024,
        system=_SYSTEM,
        messages=[{"role": "user", "content": message}],
    ) as stream:
        async for text in stream.text_stream:
            yield _sse({"type": "text-delta", "delta": text})
    yield _sse({"type": "done"})


@router.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    return StreamingResponse(_event_stream(req.message), media_type="text/event-stream")
