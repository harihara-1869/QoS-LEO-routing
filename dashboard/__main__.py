"""Serve the built local dashboard: python -m dashboard."""

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "dashboard.server:app",
        host="127.0.0.1",
        port=int(os.environ.get("LEO_DASHBOARD_PORT", "8000")),
    )
