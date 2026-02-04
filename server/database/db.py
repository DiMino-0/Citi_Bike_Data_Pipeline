import os
import ssl
import asyncio
from typing import Optional
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker, AsyncEngine
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

# abstracted sql logging from static value to env variable
# default false to make sure its off in production unless explicitly set
def _read_bool_env(DB_ECHO: str, default: bool = False) -> bool:
    """Return the boolean value of an environment variable DB_ECHO.

    Recognizes: '1', 'true', 'yes', 'on' (case-insensitive).
    """
    val = os.getenv("DB_ECHO")
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


def _create_ssl_context() -> ssl.SSLContext | None:
    """Create SSL context if SSL_CA_PATH is set; otherwise return None."""
    cafile = os.getenv("SSL_CA_PATH")
    if not cafile:
        return None
    ctx = ssl.create_default_context(cafile=cafile)
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx

# Lazy initialization of async engine and sessionmaker
_engine: Optional[AsyncEngine] = None  # AsyncEngine when initialized
_async_session_local: Optional[async_sessionmaker[AsyncSession]] = None
_engine_lock = asyncio.Lock()

# Initializer for the async engine and sessionmaker
async def init_engine(db_url: Optional[str] = None, echo: Optional[bool] = None) -> None:
    """
    Initialize the async engine and sessionmaker if not already done.
    Pass an explicit db_url to override the environment value.
    Pass `echo` to override the `DB_ECHO` environment flag (controls SQL logging).
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
            if echo is None:
                echo = _read_bool_env("DB_ECHO", False)
            _engine = create_async_engine(db_url, echo=echo, connect_args=connect_args)
            _async_session_local = async_sessionmaker(bind=_engine, expire_on_commit=False)

# Accessor for the async engine
async def get_engine(db_url: Optional[str] = None, echo: Optional[bool] = None) -> AsyncEngine:
    """
    Return the initialized async engine, initializing it if needed.
    Pass `db_url` to override the environment value when initializing.
    Pass `echo` to override the `DB_ECHO` environment flag (controls SQL logging).
    """
    if _engine is None:
        await init_engine(db_url=db_url, echo=echo)
    return _engine

# for cleaning up async resources
async def dispose_engine() -> None:
    # Dispose the underlying engine and reset cached objects.
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

# Health check for DB connectivity
async def check_db_connection() -> bool:
    # Run a small query to confirm DB is reachable.
    try:
        engine = await get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False

# `get_session()` is an async generator (used as a FastAPI dependency)
# non-blocking connection for db queries 
async def get_session(db_url: Optional[str] = None) -> AsyncGenerator[AsyncSession, None]:
    """Async generator dependency that yields a DB session.
    Can Pass `db_url` to override the environment value (useful for tests).
    """
    # Ensure engine & sessionmaker are initialized
    await init_engine(db_url=db_url)
    if _async_session_local is None:
        raise RuntimeError("Database session factory is not initialized")

    async with _async_session_local() as session:
        yield session