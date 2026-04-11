"""CLI entry point — runs the FastAPI web server."""

from __future__ import annotations

import uvicorn
from ward.core.config import get_config


def main():
    cfg = get_config()
    uvicorn.run(
        "ward.app:app",
        host=cfg.web_host,
        port=cfg.web_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
