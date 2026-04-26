# Repository Guidelines

## Project Structure & Module Organization

Ward is a Python 3.12 FastAPI application with a vanilla static frontend. Backend code lives in `src/ward/`: `app.py` creates the app, `cli.py` runs Uvicorn, `api/routes.py` defines HTTP and SSE endpoints, `core/` handles configuration and data fetching, `services/` contains business logic and SQLite persistence, `schemas/` holds Pydantic models, and `agent/` plus `mini_agent/` implement the AI agent framework. Frontend files are served directly from `static/index.html`, `static/css/style.css`, and `static/js/app.js`. Runtime scratch files belong in `workspace/`.

## Build, Test, and Development Commands

- `uv sync`: install project dependencies from `pyproject.toml`.
- `uv run ward`: start the web app on `WEB_PORT` or port `8000`.
- `./start.sh`: convenience launcher used by the repo.
- `./restart.sh`: restart helper for local server workflows.
- `pip install -e . && ward`: pip-based alternative when `uv` is unavailable.

After starting the app, open `http://localhost:8000`. Configure credentials with `cp .env.example .env`; `MINIMAX_API_KEY` is required for AI features.

## Coding Style & Naming Conventions

Use standard Python style: 4-space indentation, type hints where useful, module docstrings for entry points, and clear snake_case names. Keep FastAPI route handlers in `api/routes.py` thin; place market, history, and database behavior in `services/`. Pydantic request and response types belong in `schemas/models.py`. Frontend code is plain HTML/CSS/JS; keep selectors descriptive and avoid introducing a framework without a clear need.

## Testing Guidelines

There is no committed test suite yet. When adding tests, use `pytest` and place files under `tests/` with names like `test_stock_service.py` or `test_chat_stream.py`. Prefer focused tests around data normalization, service behavior, and SSE event formatting. Mock external market and LLM providers so tests do not require network access or API keys. Run tests with `uv run pytest` once `pytest` is added to development dependencies.

## Commit & Pull Request Guidelines

Recent history uses conventional-style prefixes such as `fix:`, `feat:`, and `refactor:`; follow that pattern and keep the subject concise, for example `fix: handle SSE chunks across packets`. Pull requests should describe the behavior change, list manual or automated checks, mention required environment changes, and include screenshots or short recordings for UI updates. Link related issues when available and call out any data-provider or API-key assumptions.

## Security & Configuration Tips

Never commit `.env` or API keys. Use `.env.example` for documented variables only. The app stores chat history in SQLite under `~/.ward/conversations.db`; avoid committing exported user conversations or generated logs that may contain prompts, market context, or credentials.
