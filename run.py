import uvicorn

from app.core.config import (
    UVICORN_HOST,
    UVICORN_PORT,
    UVICORN_RELOAD,
    UVICORN_WORKERS,
)

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=UVICORN_HOST,
        port=UVICORN_PORT,
        reload=UVICORN_RELOAD,
        # uvicorn запрещает workers > 1 вместе с reload,
        # поэтому при включённом reload воркеров всегда 1.
        workers=1 if UVICORN_RELOAD else UVICORN_WORKERS,
    )