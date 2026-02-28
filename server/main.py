import os
import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from database.db import check_db_connection, get_engine, get_session
from database.seed import run_seed
from fastapi import FastAPI, HTTPException
import uvicorn


if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


async def _daily_seed_loop(stop_event: asyncio.Event) -> None:
    enabled = _env_bool("ENABLE_MONTHLY_SEED_JOB", False)
    if not enabled:
        logger.info("Daily seed job is disabled (ENABLE_MONTHLY_SEED_JOB=false)")
        return

    schedule_hour = 3
    schedule_minute = 0
    months = 1
    ingest_if_missing = True
    data_dir = str(Path(__file__).resolve().parent / "scratch" / "data")
    timezone = ZoneInfo("UTC")

    logger.info(
        "Daily seed schedule enabled: hour=%d minute=%d tz=%s months=%d ingest_if_missing=%s data_dir=%s",
        schedule_hour,
        schedule_minute,
        timezone.key,
        months,
        ingest_if_missing,
        data_dir,
    )

    last_triggered_date: str | None = None
    while not stop_event.is_set():
        now = datetime.now(timezone)
        current_date = now.strftime("%Y%m%d")
        should_run = (
            now.hour == schedule_hour
            and now.minute == schedule_minute
        )

        if should_run and last_triggered_date != current_date:
            db_url = os.getenv("DB_URL")
            if not db_url:
                logger.error("Daily seed skipped: DB_URL is not configured")
            else:
                logger.info("Starting daily seed job for date=%s", current_date)
                try:
                    files_count, total_rows, total_inserted = await asyncio.to_thread(
                        run_seed,
                        db_url,
                        data_dir,
                        None,
                        months,
                        ingest_if_missing,
                    )
                    logger.info(
                        "Daily seed finished. Files=%d Rows processed=%d Rows inserted=%d",
                        files_count,
                        total_rows,
                        total_inserted,
                    )
                except Exception:
                    logger.exception("Daily seed job failed")
            last_triggered_date = current_date

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=20)
        except asyncio.TimeoutError:
            continue

# Load local .env from package directory (`server/.env`) if present
dotenv_path = Path(__file__).resolve().parent / ".env"
if dotenv_path.exists() or os.getenv("LOAD_DOTENV", "").lower() in ("1", "true", "yes", "on"):
    load_dotenv(dotenv_path=dotenv_path)

@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Server startup initiated")
    db_reachable = await check_db_connection()
    if db_reachable:
        logger.info("Database connection check at startup: ok")
    else:
        logger.warning("Database connection check at startup: unavailable")
    stop_event = asyncio.Event()
    seed_task = asyncio.create_task(_daily_seed_loop(stop_event))
    yield
    stop_event.set()
    seed_task.cancel()
    try:
        await seed_task
    except asyncio.CancelledError:
        pass
    logger.info("Server shutdown initiated")


app = FastAPI(lifespan=lifespan)


@app.get("/api")

async def root():
    return {"message": "Hello World"}

@app.get("/api/db/health")
async def health():
    """Health endpoint: returns 200 when DB is reachable, 503 otherwise."""
    if not await check_db_connection():
        logger.warning("Database health check failed")
        raise HTTPException(status_code=503, detail="database unavailable")
    logger.info("Database health check passed")
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
    logger.info("Starting Uvicorn server on 127.0.0.1:8000")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)

#dev commands:
# - FastAPI CLI: python3 -m fastapi dev main.py
# - Uvicorn directly: uvicorn main.py --reload
# - Docker container: docker-compose up --build in root