import json
import time

import pytest

from ward.api.sse import sse_data as _sse_data
from ward.api.sse import stream_sync_chunks as _stream_llm_chunks


def test_sse_data_uses_compact_json_and_unicode():
    encoded = _sse_data({"message": "完成", "done": True})
    assert encoded.endswith("\n\n")
    assert json.loads(encoded.removeprefix("data: ")) == {"message": "完成", "done": True}


@pytest.mark.asyncio
async def test_sync_stream_iteration_runs_off_event_loop():
    def chunks():
        time.sleep(0.05)
        yield {"chunk": "ok", "done": True}

    started = time.perf_counter()
    iterator = _stream_llm_chunks(chunks())
    pending = __import__("asyncio").create_task(anext(iterator))
    await __import__("asyncio").sleep(0.01)
    assert time.perf_counter() - started < 0.04
    assert "ok" in await pending
