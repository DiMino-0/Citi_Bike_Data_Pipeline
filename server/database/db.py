import os
from dotenv import load_dotenv
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
import uvicorn

#load environment variables from .env file
load_dotenv()

#connect to database
DB_URL = os.getenv("DB_URL")
DB_KEY = os.getenv("DB_KEY")

# 'postgresql+asyncpg' for async operations, 'postgresql' for sync
# For sync: engine = create_engine(DB_URL, echo=True) 

# Create engine for async using asyncio from SQLAlchemy:
engine = create_async_engine(DB_URL, echo=True)

app = FastAPI()

async def check_db_connection() -> bool:
	"""Run a small query to confirm DB is reachable."""
	try:
		async with engine.connect() as conn:
			await conn.execute(text("SELECT 1"))
		return True
	except SQLAlchemyError:
		return False

@app.get("/health")
async def health():
	"""Health endpoint: returns 200 when DB is reachable, 503 otherwise."""
	if not await check_db_connection():
		raise HTTPException(status_code=503, detail="database unavailable")
	return {"status": "ok", "database": "ok"}

# For async session management
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSession(engine) as session:
        yield session

if __name__ == "__main__":
	# Run with: python main.py  (use `uvicorn main:app --reload` for development)
	uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)

