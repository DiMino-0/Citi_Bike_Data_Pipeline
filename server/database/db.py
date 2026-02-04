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

def _create_ssl_context() -> ssl.SSLContext | None:
    """Create SSL context if SSL_CA_PATH is set; otherwise return None."""
    cafile = os.getenv("SSL_CA_PATH")
    if not cafile:
        return None
    ctx = ssl.create_default_context(cafile=cafile)
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx

# Lazy initialization of async engine and sessionmaker
import asyncio
from typing import Optional

_engine: Optional[object] = None  # will be AsyncEngine when initialized
_async_session_local: Optional[async_sessionmaker] = None
_engine_lock = asyncio.Lock()

# Initializer for the async engine and sessionmaker
async def init_engine(db_url: Optional[str] = None) -> None:
    """Initialize the async engine and sessionmaker if not already done.

    Pass an explicit db_url to override the environment value.
    """
    global _engine, _async_session_local
    if db_url is None:
        db_url = os.getenv("DB_URL")
    if not db_url:
        raise RuntimeError("DB_URL is not set in environment")

    async with _engine_lock:
        if _engine is None:
            ssl_ctx = _create_ssl_context()
            connect_args = {"ssl": ssl_ctx} if ssl_ctx else {}
            _engine = create_async_engine(db_url, echo=True, connect_args=connect_args)
            _async_session_local = async_sessionmaker(bind=_engine, expire_on_commit=False)

# Accessor for the async engine
async def get_engine() -> object:
    """Return the initialized async engine, initializing it if needed."""
    if _engine is None:
        await init_engine()
    return _engine


# for cleaning up async resources
async def dispose_engine() -> None:
    """Dispose the underlying engine and reset cached objects."""
    global _engine, _async_session_local
    async with _engine_lock:
        if _engine is not None:
            # AsyncEngine.dispose() may be sync or async depending on SQLAlchemy version
            try:
                await _engine.dispose()
            except TypeError:
                _engine.dispose()
            _engine = None
            _async_session_local = None


async def check_db_connection() -> bool:
    """Run a small query to confirm DB is reachable."""
    try:
        engine = await get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False

 # `get_session()` is an async generator (used as a FastAPI dependency)
 # non-blocking connection for db queries 
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    # Ensure engine & sessionmaker are initialized
    await init_engine()
    if _async_session_local is None:
        raise RuntimeError("Database session factory is not initialized")