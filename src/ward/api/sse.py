"""Shared Server-Sent Events helpers."""

from __future__ import annotations

import asyncio
import json

from fastapi.responses import StreamingResponse


CACHED_STREAM_CHARS = 32


def sse_data(chunk: dict) -> str:
    data = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
    return f"data: {data}\n\n"


def _next_sync_chunk(iterator):
    try:
        return True, next(iterator)
    except StopIteration:
        return False, None


async def stream_sync_chunks(chunks):
    """Bridge a blocking sync LLM generator into an async SSE stream."""
    iterator = iter(chunks)
    try:
        while True:
            has_chunk, chunk = await asyncio.to_thread(_next_sync_chunk, iterator)
            if not has_chunk:
                break
            text = chunk.get("chunk")
            if chunk.get("cached") and text and not chunk.get("done"):
                base = dict(chunk)
                base.pop("chunk", None)
                for offset in range(0, len(text), CACHED_STREAM_CHARS):
                    yield sse_data({**base, "chunk": text[offset:offset + CACHED_STREAM_CHARS]})
                    await asyncio.sleep(0.02)
            else:
                yield sse_data(chunk)
                await asyncio.sleep(0)
            if chunk.get("done"):
                break
    except Exception as exc:
        yield sse_data({"ok": False, "error": str(exc), "done": True})


def sse_response(generator) -> StreamingResponse:
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Transfer-Encoding": "chunked",
        },
    )
