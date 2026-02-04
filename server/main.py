from fastapi import FastAPI, HTTPException
import uvicorn

from database.db import check_db_connection, get_session

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.get("/health")
async def health():
    """Health endpoint: returns 200 when DB is reachable, 503 otherwise."""
    if not await check_db_connection():
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ok", "database": "ok"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)