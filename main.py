"""ASGI entrypoint. Run with ``python -m app.main`` or ``uvicorn app.main:app``."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.application:app",
        host="127.0.0.1",
        port=8005,
        reload=True,
    )
