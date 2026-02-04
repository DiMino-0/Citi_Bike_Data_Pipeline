from fastapi import FastAPI, HTTPException
import uvicorn

from database.db import check_db_connection, get_engine, get_session

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
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)

# current dev command: python3 -m fastapi dev main.py

# local server hello world endpoint is reachable
# db is reachable from health endpoint