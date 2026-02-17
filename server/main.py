import os
from pathlib import Path
from dotenv import load_dotenv
from database.db import check_db_connection, get_engine, get_session
from fastapi import FastAPI, HTTPException
import uvicorn

# Load local .env from package directory (`server/.env`) if present
dotenv_path = Path(__file__).resolve().parent / ".env"
if dotenv_path.exists() or os.getenv("LOAD_DOTENV", "").lower() in ("1", "true", "yes", "on"):
    load_dotenv(dotenv_path=dotenv_path)

app = FastAPI()
@app.get("/api")

async def root():
    return {"message": "Hello World"}

@app.get("/api/db/health")
async def health():
    """Health endpoint: returns 200 when DB is reachable, 503 otherwise."""
    if not await check_db_connection():
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ok", "database": "ok"}

@app.get("/api/engine/info")
async def engine_info():
    """Endpoint to get info about the async engine."""
    engine = await get_engine()
    return {"engine_info": str(engine)}

@app.get("/api/session/info")
async def session_info():
    """Endpoint to get info about the async session."""
    # iterate the async generator and use the first yielded session
    async for session in get_session():
        return {"session_info": str(session)}

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)

#dev commands:
# - FastAPI CLI: python3 -m fastapi dev main.py
# - Uvicorn directly: uvicorn main.py --reload
# - Docker container: docker-compose up --build in root