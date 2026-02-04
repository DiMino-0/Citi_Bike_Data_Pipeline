from server.database.db import check_db_connection, get_engine, get_session
from fastapi import FastAPI, HTTPException
import uvicorn


app = FastAPI()

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
# - FastAPI CLI: python -m fastapi dev server.main:app
# - Uvicorn directly: uvicorn server.main:app --reload