# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Ward is a US stock market data analysis tool with a Web UI. It provides real-time index quotes, pre/regular/after-hours pricing, stock search, K-line charts, AI-powered analysis, and an intelligent Q&A chat system.

- **Backend**: FastAPI + SQLite
- **Frontend**: Vanilla HTML/CSS/JS (no framework)
- **Data sources**: akshare (East Money/Sina) + yfinance (Yahoo Finance)
- **AI**: MiniMax API (Anthropic-compatible) via mini-agent framework

## Running the Project

```bash
# Install dependencies
uv sync

# Run the web server
uv run ward

# Access at http://localhost:8000 (or http://127.0.0.1:8000)
```

Environment variables (set in `.env`):
- `MINIMAX_API_KEY` (required) — MiniMax API key
- `LLM_MODEL` (optional, default `MiniMax-M2.7-highspeed`)
- `ANTHROPIC_BASE_URL` (optional)
- `WEB_PORT` (optional, default `8000`)
- `PUBLIC_MODE=1` — bind to `0.0.0.0` for external access

## Architecture

```
src/ward/
├── app.py                    # FastAPI app factory + static file mounting
├── cli.py                    # CLI entry point (uvicorn runner)
├── core/
│   ├── config.py             # Config loading from .env via dotenv
│   └── data_fetcher.py       # Unified data fetching (akshare + yfinance)
├── api/
│   └── routes.py             # All FastAPI routes + SSE streaming helpers
├── schemas/
│   └── models.py             # Pydantic request/response models + ChatContext
├── services/
│   ├── chat_service.py       # Original ChatService (Anthropic streaming)
│   ├── nasdaq_service.py     # Market overview (indices + gold)
│   ├── index_service.py      # Index quotes, K-lines, AI analysis
│   ├── stock_service.py      # Stock quotes, search, K-lines, AI analysis
│   ├── report_service.py     # Market report generation
│   └── db/
│       └── conversation_service.py  # SQLite chat history
├── agent/
│   ├── ward_agent.py         # WardMiniAgent — SSE wrapper around mini-agent
│   └── ward_tools.py         # Tool definitions (get_stock_quote, etc.)
└── mini_agent/               # Mini-Agent framework (custom LLM agent)
    ├── agent.py              # Core Agent class (run + run_streaming)
    ├── logger.py             # JSON run logging
    ├── retry.py              # Retry logic
    ├── schema.py              # Message, Event types
    ├── llm/
    │   ├── base.py           # LLMClient abstract base
    │   ├── anthropic_client.py  # Anthropic API client
    │   └── llm_wrapper.py    # Concrete LLMClient implementation
    └── tools/
        └── base.py           # Tool, ToolResult base classes
```

## Key Design Points

### Two Agent Systems

The codebase has **two parallel agent implementations**:

1. **WardMiniAgent** (`agent/ward_agent.py`) — newer, uses the `mini_agent/Agent` framework with `run_streaming()`. All new tool definitions live here (`ward_tools.py`).

2. **ChatService** (`services/chat_service.py`) — original implementation, uses raw `Anthropic` SDK streaming. Kept for backward compatibility with history endpoints.

Both are exposed via `/api/chat` (non-streaming) and `/api/chat/stream` (SSE). The routes use `WardMiniAgent` via `get_ward_agent()`.

### ChatContext

`ChatContext` (`schemas/models.py`) carries all UI-loaded market data (quotes, K-lines, analyses, extended hours) to the agent so it can answer without always calling tools. It is built by the frontend and sent with each chat request.

### Data Flow for Chat

```
HTTP Request → /api/chat/stream → WardMiniAgent.chat_stream()
  → MiniAgent.run_streaming()
    → LLMClient.generate() (Anthropic API)
      → tool_call events → Tool.execute() (ward_tools.py)
        → StockService / IndexService / MarketService
          → DataFetcher (akshare / yfinance)
```

### SSE Streaming

`/api/chat/stream` yields SSE events via `StreamingResponse`. Each chunk has keys: `chunk` (text delta), `thinking`, `tool_call`, `tool_result`, `done`. The frontend JS parses these to render streaming responses.

### Cancellation

Conversation cancellation uses `asyncio.Event` stored in `_conversation_cancels` dict keyed by `conversation_id`. Setting the event interrupts the agent loop at the next safe checkpoint.

## Adding New Tools

1. Create a new `Tool` subclass in `agent/ward_tools.py` (or `mini_agent/tools/base.py` if shared)
2. Register it in `get_all_tools()`
3. The tool will automatically be available to `WardMiniAgent`
4. For ChatService tools, also add to `TOOLS` list in `services/chat_service.py`

## Database

SQLite at `~/.ward/conversations.db`. Two tables: `conversations` and `messages`. Managed by `ConversationService`.

## Static Files

Frontend lives in `static/` (served at `/static`). `static/index.html` is the main page. No build step required.
