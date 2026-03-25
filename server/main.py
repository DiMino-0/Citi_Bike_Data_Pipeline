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
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
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


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid integer for %s=%r. Using default=%d", name, raw, default)
        return default


async def _run_startup_seed_once() -> None:
    enabled = _env_bool("ENABLE_STARTUP_SEED", False)
    if not enabled:
        logger.info("Startup seed is disabled (ENABLE_STARTUP_SEED=false)")
        return

    db_url = os.getenv("DB_URL")
    if not db_url:
        logger.error("Startup seed skipped: DB_URL is not configured")
        return

    default_data_dir = Path(__file__).resolve().parent / "scratch" / "data"
    data_dir = os.getenv("SEED_DATA_DIR", str(default_data_dir))
    month = os.getenv("STARTUP_SEED_MONTH") or None
    month_range = os.getenv("STARTUP_SEED_RANGE") or None
    ingest_if_missing = _env_bool("STARTUP_SEED_INGEST_IF_MISSING", True)

    logger.info(
        "Running startup seed: month=%s range=%s ingest_if_missing=%s data_dir=%s",
        month,
        month_range,
        ingest_if_missing,
        data_dir,
    )

    try:
        files_count, total_rows, total_inserted = await asyncio.to_thread(
            run_seed,
            db_url,
            data_dir,
            month=month,
            month_range=month_range,
            ingest_if_missing=ingest_if_missing,
        )
        logger.info(
            "Startup seed finished. Files=%d Rows processed=%d Rows inserted=%d",
            files_count,
            total_rows,
            total_inserted,
        )
    except Exception:
        logger.exception("Startup seed failed")


async def _daily_seed_loop(stop_event: asyncio.Event) -> None:
    enabled = _env_bool("ENABLE_MONTHLY_SEED_JOB", False)
    if not enabled:
        logger.info("Daily seed job is disabled (ENABLE_MONTHLY_SEED_JOB=false)")
        return

    schedule_hour = 3
    schedule_minute = 0
    months = 1
    ingest_if_missing = True
    default_data_dir = Path(__file__).resolve().parent / "scratch" / "data"
    data_dir = os.getenv("SEED_DATA_DIR", str(default_data_dir))
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
                        ingest_if_missing=ingest_if_missing,
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
    await _run_startup_seed_once()
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


@app.get("/api/analytics/monthly-trip-counts")
async def analytics_monthly_trip_counts(session: AsyncSession = Depends(get_session)):
    query = text(
        """
        SELECT trip_month, COUNT(*) AS trip_count
        FROM citibike_trips
        GROUP BY trip_month
        ORDER BY trip_month
        """
    )
    result = await session.execute(query)
    rows = result.mappings().all()
    return [
        {
            "tripMonth": row["trip_month"],
            "tripCount": int(row["trip_count"]),
        }
        for row in rows
    ]


@app.get("/api/analytics/lost-bike-fee-summary")
async def analytics_lost_bike_fee_summary(
    month: str = Query(..., min_length=6, max_length=6),
    rider: str = Query("all", pattern="^(all|member|casual)$"),
    session: AsyncSession = Depends(get_session),
):
    query = text(
        """
        WITH durations AS (
            SELECT
                trip_month,
                LOWER(member_casual) AS member_casual,
                GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (ended_at - started_at)) / 60))::int AS duration_min
            FROM citibike_trips
            WHERE ended_at IS NOT NULL
              AND started_at IS NOT NULL
              AND trip_month = :month
              AND (:rider = 'all' OR LOWER(member_casual) = :rider)
        )
        SELECT
            trip_month,
            member_casual,
            COUNT(*) FILTER (WHERE duration_min > 1440) AS lost_bike_fee_trips,
            COUNT(*) AS total_trips
        FROM durations
        GROUP BY trip_month, member_casual
        ORDER BY member_casual
        """
    )
    result = await session.execute(query, {"month": month, "rider": rider})
    rows = result.mappings().all()
    return [
        {
            "tripMonth": row["trip_month"],
            "memberCasual": row["member_casual"],
            "lostBikeFeeTrips": int(row["lost_bike_fee_trips"]),
            "totalTrips": int(row["total_trips"]),
        }
        for row in rows
    ]


@app.get("/api/analytics/duration-buckets")
async def analytics_duration_buckets(
    month: str = Query(..., min_length=6, max_length=6),
    rider: str = Query("all", pattern="^(all|member|casual)$"),
    bucket_minutes: int = Query(5, ge=1, le=60),
    session: AsyncSession = Depends(get_session),
):
    query = text(
        """
        WITH durations AS (
            SELECT
                trip_month,
                LOWER(member_casual) AS member_casual,
                GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (ended_at - started_at)) / 60))::int AS duration_min
            FROM citibike_trips
            WHERE ended_at IS NOT NULL
              AND started_at IS NOT NULL
              AND trip_month = :month
              AND (:rider = 'all' OR LOWER(member_casual) = :rider)
        ), bucketed AS (
            SELECT
                d.trip_month,
                d.member_casual,
                d.duration_min,
                CASE
                    WHEN d.duration_min > 1440 THEN 'LOST_BIKE_FEE'
                    ELSE CONCAT(
                        LPAD(((d.duration_min / :bucket_minutes) * :bucket_minutes)::text, 4, '0'),
                        '-',
                        LPAD((((d.duration_min / :bucket_minutes) * :bucket_minutes) + :bucket_minutes - 1)::text, 4, '0'),
                        ' min'
                    )
                END AS duration_bucket
            FROM durations d
        )
        SELECT
            trip_month,
            member_casual,
            duration_bucket,
            COUNT(*) AS trips,
            (COUNT(*) FILTER (WHERE duration_min > 1440) > 0) AS lost_bike_fee_flag
        FROM bucketed
        GROUP BY trip_month, member_casual, duration_bucket
        ORDER BY
            member_casual,
            CASE WHEN duration_bucket = 'LOST_BIKE_FEE' THEN 1 ELSE 0 END,
            duration_bucket
        """
    )
    result = await session.execute(
        query,
        {"month": month, "rider": rider, "bucket_minutes": bucket_minutes},
    )
    rows = result.mappings().all()
    return [
        {
            "tripMonth": row["trip_month"],
            "memberCasual": row["member_casual"],
            "bucket": row["duration_bucket"],
            "trips": int(row["trips"]),
            "lostBikeFeeFlag": bool(row["lost_bike_fee_flag"]),
        }
        for row in rows
    ]

if __name__ == "__main__":
    logger.info("Starting Uvicorn server on 127.0.0.1:8000")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)

#dev commands:
# - FastAPI CLI: python3 -m fastapi dev main.py
# - Uvicorn directly: uvicorn main.py --reload
# - Docker container: docker-compose up --build in root