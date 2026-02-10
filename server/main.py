import os
from pathlib import Path
from dotenv import load_dotenv
from server.database.db import check_db_connection, get_engine, get_session
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Load local .env from package directory (`server/.env`) if present
dotenv_path = Path(__file__).resolve().parent / ".env"
if dotenv_path.exists() or os.getenv("LOAD_DOTENV", "").lower() in ("1", "true", "yes", "on"):
    load_dotenv(dotenv_path=dotenv_path)

app = FastAPI()

# CORS configuration 🔧
# Set `CORS_ALLOWED_ORIGINS` to a comma-separated list of origins (e.g. "https://example.com,https://app.example.com").
# If unset or empty, all origins will be allowed (similar to allow_origins=["*"]).
origins_env = os.getenv("CORS_ALLOWED_ORIGINS", "")
# parse the origins env variable
if origins_env:
    origins = [o.strip() for o in origins_env.split(",") if o.strip()]
else:
    origins = ["http://127.0.0.1:8000", "http://localhost:8000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.get("/db/health")
async def health():
    """Health endpoint: returns 200 when DB is reachable, 503 otherwise."""
    if not await check_db_connection():
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ok", "database": "ok"}

@app.get("/engine/info")
async def engine_info():
    """Endpoint to get info about the async engine."""
    engine = await get_engine()
    return {"engine_info": str(engine)}

@app.get("/session/info")
async def session_info():
    """Endpoint to get info about the async session."""
    # iterate the async generator and use the first yielded session
    async for session in get_session():
        return {"session_info": str(session)}

if __name__ == "__main__":
    # Updated to use an importable module path so reload works when started from the repo root
    uvicorn.run("server.main:app", host="127.0.0.1", port=8000, reload=True)

#dev commands:
# - FastAPI CLI: python3 -m fastapi dev main.py
# - Uvicorn directly: uvicorn main.py --reload