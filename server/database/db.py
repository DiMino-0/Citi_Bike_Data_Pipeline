import os
import ssl
from dotenv import load_dotenv
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

#load environment variables from .env file
load_dotenv()

#connect to database
DB_URL = os.getenv("DB_URL")

if not DB_URL:
    raise RuntimeError("DB_URL is not set in environment")

# Create SSL context for asyncpg
ssl_context = ssl.create_default_context(cafile = os.getenv("SSL_CA_PATH"))
ssl_context.verify_mode = ssl.CERT_REQUIRED

# Create async engine
engine = create_async_engine(DB_URL, echo=True, connect_args={"ssl": ssl_context})

# async session factory
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

async def check_db_connection() -> bool:
    """Run a small query to confirm DB is reachable."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False

# For async session management
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session