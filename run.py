import uvicorn

from app.config import UVICORN_HOST, UVICORN_PORT, UVICORN_RELOAD

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=UVICORN_HOST,
        port=UVICORN_PORT,
        reload=UVICORN_RELOAD,
    )