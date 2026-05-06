import os
import glob
import logging
import asyncio
import fcntl
from functools import lru_cache
from contextlib import asynccontextmanager
from datetime import datetime
from collections import defaultdict
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any, SupportsInt, cast
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from database.db import check_db_connection, get_engine, get_session
from database.models import CitiBikeTrip
from database.seed import run_seed
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Float, Integer, String, case, cast as sa_cast, func, inspect, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession
import uvicorn
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

logger = logging.getLogger(__name__)

EARTH_RADIUS_MILES = 3958.7613
ESTIMATED_SPEED_MPH = 10.0
_LOCK_EX = getattr(fcntl, "LOCK_EX")
_LOCK_NB = getattr(fcntl, "LOCK_NB")
_LOCK_UN = getattr(fcntl, "LOCK_UN")
_flock = getattr(fcntl, "flock")


def _query_source() -> str:
    default_source = "parquet" if glob.glob(_parquet_glob()) else "db"
    source = os.getenv("DEMO_SOURCE", os.getenv("DEMO_QUERY_SOURCE", default_source)).strip().lower()
    if source not in {"db", "parquet"}:
        logger.warning("Invalid DEMO_SOURCE=%r. Falling back to 'db'.", source)
        return "db"
    return source


def _parquet_glob() -> str:
    base_dir = Path(__file__).resolve().parent
    default_glob = base_dir / "scratch" / "data" / "data*.parquet"

    raw_glob = os.getenv("DEMO_PARQUET_GLOB")
    if not raw_glob:
        return default_glob.as_posix()

    glob_path = Path(raw_glob)
    if not glob_path.is_absolute():
        glob_path = base_dir / glob_path

    return glob_path.as_posix()


def _parquet_files() -> list[str]:
    candidate_files = [Path(path) for path in glob.glob(_parquet_glob())]
    valid_files: list[str] = []

    for file_path in candidate_files:
        try:
            with file_path.open("rb") as parquet_file:
                header = parquet_file.read(4)
                if header != b"PAR1":
                    logger.warning("Skipping non-parquet file %s", file_path)
                    continue

                parquet_file.seek(-4, os.SEEK_END)
                footer = parquet_file.read(4)
                if footer != b"PAR1":
                    logger.warning("Skipping truncated parquet file %s", file_path)
                    continue
        except OSError:
            logger.exception("Unable to inspect parquet file %s", file_path)
            continue

        valid_files.append(file_path.as_posix())

    logger.info("Found %d valid parquet files for query source", len(valid_files))

    return valid_files


def _parquet_files_for_month(month: str | None) -> list[str]:
    files = _parquet_files()
    if month is None:
        return files

    target_file_name = f"data{month}.parquet"
    month_files = [path for path in files if Path(path).name == target_file_name]
    if month_files:
        return month_files

    logger.warning(
        "No parquet file matched month=%s (expected %s); falling back to all valid files",
        month,
        target_file_name,
    )
    return files


def _is_parquet_source() -> bool:
    return _query_source() == "parquet"


def _coerce_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    raise ValueError(f"Unsupported datetime value: {value!r}")


def _coerce_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, (float, str, bytes, bytearray)):
        return int(value)
    return int(cast(SupportsInt, value))


def _duckdb_rows(query: str, params: list[object] | None = None) -> list[dict[str, object]]:
    try:
        import duckdb
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail="Parquet demo mode requires duckdb. Install server requirements first.",
        ) from exc

    con = duckdb.connect()
    try:
        # Keep DuckDB from over-consuming memory in constrained containers.
        con.execute("PRAGMA threads=2")
        con.execute("PRAGMA memory_limit='7GB'")
        con.execute("PRAGMA temp_directory='/tmp'")
        executed = con.execute(query, params or [])
        columns = [column[0] for column in executed.description]
        rows = executed.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    finally:
        con.close()


async def _duckdb_rows_async(query: str, params: list[object] | None = None) -> list[dict[str, object]]:
    # DuckDB execution is blocking; run it in a worker thread to keep the event loop responsive.
    return await asyncio.to_thread(_duckdb_rows, query, params)


@lru_cache(maxsize=256)
def _parquet_columns_for_file(parquet_file: str) -> frozenset[str]:
    try:
        import duckdb
    except ImportError:
        logger.warning("DuckDB is unavailable; parquet schema inspection is disabled")
        return frozenset()

    con = duckdb.connect()
    try:
        con.execute("PRAGMA threads=2")
        result = con.execute("DESCRIBE SELECT * FROM read_parquet(?, filename=true)", [parquet_file])
        return frozenset(str(row[0]) for row in result.fetchall())
    except Exception:
        logger.exception("Unable to inspect parquet schema for %s", parquet_file)
        return frozenset()
    finally:
        con.close()


@lru_cache(maxsize=32)
def _parquet_columns_for_files(parquet_files: tuple[str, ...]) -> frozenset[str]:
    columns: set[str] = set()
    for parquet_file in parquet_files:
        columns.update(_parquet_columns_for_file(parquet_file))
    return frozenset(columns)


def _sql_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _parquet_file_list_sql(parquet_files: list[str]) -> str:
    if not parquet_files:
        return "[]"
    return "[" + ", ".join(_sql_string_literal(path) for path in parquet_files) + "]"


def _parquet_source_expr(columns: frozenset[str], normalized_name: str, raw_name: str | None = None) -> str:
    if normalized_name in columns:
        return normalized_name
    if raw_name is not None and raw_name in columns:
        return f'"{raw_name}"'
    return "NULL"


def _parquet_trip_projection_sql(columns: frozenset[str], parquet_files_sql: str) -> str:
    trip_month_expr = _parquet_trip_month_expr_sql()
    ride_id_expr = _parquet_source_expr(columns, "ride_id")
    rideable_type_expr = _parquet_source_expr(columns, "rideable_type")
    started_at_expr = _parquet_source_expr(columns, "started_at", "Start Time")
    ended_at_expr = _parquet_source_expr(columns, "ended_at", "End Time")
    start_station_name_expr = _parquet_source_expr(columns, "start_station_name", "Start Station Name")
    start_station_id_expr = _parquet_source_expr(columns, "start_station_id", "Start Station ID")
    end_station_name_expr = _parquet_source_expr(columns, "end_station_name", "End Station Name")
    end_station_id_expr = _parquet_source_expr(columns, "end_station_id", "End Station ID")
    start_lat_expr = _parquet_source_expr(columns, "start_lat", "Start Station Latitude")
    start_lng_expr = _parquet_source_expr(columns, "start_lng", "Start Station Longitude")
    end_lat_expr = _parquet_source_expr(columns, "end_lat", "End Station Latitude")
    end_lng_expr = _parquet_source_expr(columns, "end_lng", "End Station Longitude")
    member_casual_expr = _parquet_source_expr(columns, "member_casual", "Member/Casual")

    return f"""
        SELECT
            CAST({ride_id_expr} AS VARCHAR) AS ride_id,
            CAST({rideable_type_expr} AS VARCHAR) AS rideable_type,
            TRY_CAST({started_at_expr} AS TIMESTAMP) AS started_at,
            TRY_CAST({ended_at_expr} AS TIMESTAMP) AS ended_at,
            CAST({start_station_name_expr} AS VARCHAR) AS start_station_name,
            CAST({start_station_id_expr} AS VARCHAR) AS start_station_id,
            CAST({end_station_name_expr} AS VARCHAR) AS end_station_name,
            CAST({end_station_id_expr} AS VARCHAR) AS end_station_id,
            TRY_CAST({start_lat_expr} AS DOUBLE) AS start_lat,
            TRY_CAST({start_lng_expr} AS DOUBLE) AS start_lng,
            TRY_CAST({end_lat_expr} AS DOUBLE) AS end_lat,
            TRY_CAST({end_lng_expr} AS DOUBLE) AS end_lng,
            LOWER(CAST({member_casual_expr} AS VARCHAR)) AS member_casual,
            {trip_month_expr} AS trip_month,
            CURRENT_TIMESTAMP::TIMESTAMP AS created_at
        FROM read_parquet({parquet_files_sql}, union_by_name=true, filename=true)
    """


async def _monthly_trip_counts_from_parquet(month: str | None) -> list[dict[str, object]]:
    parquet_files = _parquet_files_for_month(month)
    if not parquet_files:
        return []

    parquet_files_sql = _parquet_file_list_sql(parquet_files)
    parquet_query = f"""
        SELECT
            trip_month,
            COUNT(*) AS trip_count
        FROM (
            SELECT
                NULLIF(regexp_extract(filename, 'data(\\d{{6}})\\.parquet$', 1), '') AS trip_month
            FROM read_parquet({parquet_files_sql}, union_by_name=true, filename=true)
            WHERE filename IS NOT NULL
        ) AS monthly
        WHERE trip_month IS NOT NULL
          AND (? IS NULL OR trip_month = ?)
        GROUP BY trip_month
        ORDER BY trip_month
        """

    rows = await _duckdb_rows_async(parquet_query, [month, month])
    counts: dict[str, int] = {}
    for row in rows:
        trip_month = row.get("trip_month") if isinstance(row, dict) else None
        trip_count = row.get("trip_count") if isinstance(row, dict) else None
        if trip_month is None or trip_count is None:
            continue
        counts[str(trip_month)] = _coerce_int(trip_count)

    return [
        {"trip_month": trip_month, "trip_count": count}
        for trip_month, count in sorted(counts.items())
    ]


async def _monthly_trip_counts_from_db(month: str | None) -> list[dict[str, object]]:
    async for session in get_session():
        if month is None:
            stmt = text(
                """
                SELECT trip_month, COUNT(*) AS trip_count
                FROM citibike_trips
                WHERE trip_month IS NOT NULL
                GROUP BY trip_month
                ORDER BY trip_month
                """
            )
            result = await session.execute(stmt)
        else:
            stmt = text(
                """
                SELECT trip_month, COUNT(*) AS trip_count
                FROM citibike_trips
                WHERE trip_month = :month
                GROUP BY trip_month
                ORDER BY trip_month
                """
            )
            result = await session.execute(stmt, {"month": month})
        return [dict(row) for row in result.mappings().all()]
    return []


def _merge_monthly_trip_counts(
    primary_rows: list[dict[str, object]],
    secondary_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    merged: dict[str, int] = {}

    for rows in (primary_rows, secondary_rows):
        for row in rows:
            trip_month = row.get("trip_month") if isinstance(row, dict) else None
            trip_count = row.get("trip_count") if isinstance(row, dict) else None
            if trip_month is None or trip_count is None:
                continue
            month_key = str(trip_month)
            if month_key not in merged:
                merged[month_key] = _coerce_int(trip_count)

    return [
        {"trip_month": trip_month, "trip_count": trip_count}
        for trip_month, trip_count in sorted(merged.items())
    ]


def _parquet_trip_month_expr_sql() -> str:
    # Use the month encoded in the parquet filename so the query works across
    # both raw and normalized parquet schemas.
    return "NULLIF(regexp_extract(filename, 'data(\\d{6})\\.parquet$', 1), '')"


def _parquet_trips_cte_sql(parquet_files: list[str]) -> str:
    # Project the parquet files into a DB-like schema using only columns that exist anywhere in the set.
    columns = _parquet_columns_for_files(tuple(parquet_files))
    parquet_files_sql = _parquet_file_list_sql(parquet_files)
    return _parquet_trip_projection_sql(columns, parquet_files_sql)


async def _query_rows(
    *,
    db_query: str,
    db_params: dict[str, object] | None = None,
    parquet_query: str | None = None,
    parquet_params: list[object] | None = None,
) -> list[dict[str, object]]:
    async def _fetch_db_rows() -> list[dict[str, object]]:
        async for session in get_session():
            result = await session.execute(text(db_query), db_params or {})
            rows = result.mappings().all()
            return [dict(row) for row in rows]
        return []

    async def _fetch_parquet_rows() -> list[dict[str, object]]:
        query = parquet_query if parquet_query is not None else db_query
        params = parquet_params if parquet_query is not None else []
        return await _duckdb_rows_async(query, params)

    try:
        if _is_parquet_source():
            return await _fetch_parquet_rows()
        return await _fetch_db_rows()
    except Exception:
        logger.exception("Primary query source failed")

    try:
        if _is_parquet_source():
            return await _fetch_db_rows()
        return await _fetch_parquet_rows()
    except Exception:
        logger.exception("Fallback query source failed")
        return []


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


def _analytics_query_timeout_ms() -> int:
    # Keep analytics queries bounded to avoid upstream gateway timeouts.
    return max(1000, _env_int("ANALYTICS_QUERY_TIMEOUT_MS", 180000
    ))


async def _execute_with_statement_timeout(session: AsyncSession, stmt: Any):
    """Execute a SQLAlchemy statement with a local statement timeout when supported."""
    timeout_ms = _analytics_query_timeout_ms()
    try:
        # PostgreSQL: timeout scoped to current transaction.
        await session.execute(
            text("SELECT set_config('statement_timeout', :timeout, true)"),
            {"timeout": f"{timeout_ms}ms"},
        )
    except Exception:
        # Non-Postgres or unsupported dialect: continue without timeout setting.
        pass
    return await session.execute(stmt)


def _haversine_miles(
    start_lat: float,
    start_lng: float,
    end_lat: float,
    end_lng: float,
) -> float:
    lat1 = radians(start_lat)
    lon1 = radians(start_lng)
    lat2 = radians(end_lat)
    lon2 = radians(end_lng)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    a = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * asin(sqrt(a))


def _rounded(value: float | None, precision: int = 3) -> float | None:
    if value is None:
        return None
    return round(value, precision)


# Global variable to hold the startup lock file object (must stay alive for lock to persist)
_startup_lock_file = None


def _acquire_startup_lock() -> bool:
    """Attempt to acquire a non-blocking file lock for startup tasks. Returns True if acquired."""
    global _startup_lock_file
    lock_path = Path("/tmp/citibike_startup.lock")
    try:
        # Open the lock file, creating it if it doesn't exist
        _startup_lock_file = open(lock_path, "w")
        # Try to acquire a non-blocking exclusive lock
        _flock(_startup_lock_file.fileno(), _LOCK_EX | _LOCK_NB)
        logger.debug("Successfully acquired startup lock at %s", lock_path)
        return True
    except (IOError, OSError) as e:
        # Lock is held by another process
        if _startup_lock_file:
            _startup_lock_file.close()
            _startup_lock_file = None
        logger.debug("Could not acquire startup lock: %s", e)
        return False


def _release_startup_lock() -> None:
    """Release the startup lock."""
    global _startup_lock_file
    if _startup_lock_file is not None:
        try:
            _flock(_startup_lock_file.fileno(), _LOCK_UN)
            _startup_lock_file.close()
            logger.debug("Released startup lock")
        except OSError as e:
            logger.debug("Error releasing startup lock: %s", e)
        finally:
            _startup_lock_file = None


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
    backfill_missing_rows = _env_bool("STARTUP_SEED_BACKFILL_MISSING_ROWS", False)

    logger.info(
        "Running startup seed: month=%s range=%s ingest_if_missing=%s backfill_missing_rows=%s data_dir=%s",
        month,
        month_range,
        ingest_if_missing,
        backfill_missing_rows,
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
            backfill_missing_rows=backfill_missing_rows,
            force_clear_lock=True,  # Clear any lingering locks from previous crashed seed operations
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
    backfill_missing_rows = _env_bool("DAILY_SEED_BACKFILL_MISSING_ROWS", False)
    default_data_dir = Path(__file__).resolve().parent / "scratch" / "data"
    data_dir = os.getenv("SEED_DATA_DIR", str(default_data_dir))
    timezone = ZoneInfo("America/New_York")

    logger.info(
        "Daily seed schedule enabled: hour=%d minute=%d tz=%s months=%d ingest_if_missing=%s backfill_missing_rows=%s data_dir=%s",
        schedule_hour,
        schedule_minute,
        timezone.key,
        months,
        ingest_if_missing,
        backfill_missing_rows,
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
                        backfill_missing_rows=backfill_missing_rows,
                        force_clear_lock=False,  # Respect advisory lock in regular operation
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

    # Attempt to acquire lock for startup tasks (only one worker should run these)
    owns_startup_lock = _acquire_startup_lock()
    startup_seed_task = None
    seed_task = None
    stop_event = None

    if owns_startup_lock:
        logger.info("This worker acquired the startup lock and will run startup tasks")
        # Schedule startup seed in background so API readiness is not blocked by long seed runs.
        startup_seed_task = asyncio.create_task(_run_startup_seed_once())
        stop_event = asyncio.Event()
        seed_task = asyncio.create_task(_daily_seed_loop(stop_event))
    else:
        logger.info("Another worker holds the startup lock - skipping startup tasks for this worker")

    yield

    # Clean up tasks only if this worker owns them
    if stop_event is not None:
        stop_event.set()
    if startup_seed_task is not None:
        startup_seed_task.cancel()
    if seed_task is not None:
        seed_task.cancel()

    try:
        if startup_seed_task is not None:
            await startup_seed_task
    except asyncio.CancelledError:
        pass

    try:
        if seed_task is not None:
            await seed_task
    except asyncio.CancelledError:
        pass

    if owns_startup_lock:
        _release_startup_lock()

    logger.info("Server shutdown initiated")


app = FastAPI(lifespan=lifespan)


class MonthlyTripCountResponse(BaseModel):
    tripMonth: str
    tripCount: int


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


@app.get("/api/analytics/monthly-trip-counts", response_model=list[MonthlyTripCountResponse])
async def analytics_monthly_trip_counts(
    month: str | None = Query(None, min_length=6, max_length=6),
):
    try:
        rows: list[dict[str, object]] = []

        try:
            if _is_parquet_source():
                primary_rows = await _monthly_trip_counts_from_parquet(month)
                secondary_rows = await _monthly_trip_counts_from_db(month)
            else:
                primary_rows = await _monthly_trip_counts_from_db(month)
                secondary_rows = await _monthly_trip_counts_from_parquet(month)
            rows = _merge_monthly_trip_counts(primary_rows, secondary_rows)
        except Exception:
            logger.exception("Monthly trip counts query failed for primary source")
            try:
                if _is_parquet_source():
                    primary_rows = await _monthly_trip_counts_from_db(month)
                    secondary_rows = await _monthly_trip_counts_from_parquet(month)
                else:
                    primary_rows = await _monthly_trip_counts_from_parquet(month)
                    secondary_rows = await _monthly_trip_counts_from_db(month)
                rows = _merge_monthly_trip_counts(primary_rows, secondary_rows)
            except Exception:
                logger.exception("Monthly trip counts query failed for fallback source")
                return []

        response: list[dict[str, object]] = []
        for row in rows:
            trip_month = row.get("trip_month") if isinstance(row, dict) else None
            trip_count = row.get("trip_count") if isinstance(row, dict) else None
            if trip_month is None or trip_count is None:
                continue
            response.append(
                {
                    "tripMonth": str(trip_month),
                    "tripCount": _coerce_int(trip_count),
                }
            )
        return response
    except Exception:
        logger.exception("Monthly trip counts endpoint failed")
        return []


@app.get("/api/analytics/lost-bike-fee-summary")
async def analytics_lost_bike_fee_summary(
    month: str = Query(..., min_length=6, max_length=6),
    rider: str = Query("all", pattern="^(all|member|casual)$"),
):
    def _parquet_query(parquet_files: list[str]) -> str:
        columns = _parquet_columns_for_files(tuple(parquet_files))
        parquet_files_sql = _parquet_file_list_sql(parquet_files)
        trip_projection = _parquet_trip_projection_sql(columns, parquet_files_sql)
        return f"""
            WITH trips AS (
                {trip_projection}
            ),
             durations AS (
                 SELECT
                     trip_month,
                     LOWER(member_casual) AS member_casual,
                     GREATEST(0, CAST(FLOOR(date_diff('second', started_at, ended_at) / 60.0) AS INTEGER)) AS duration_min
                 FROM trips
                 WHERE ended_at IS NOT NULL
                   AND started_at IS NOT NULL
                   AND trip_month = ?
                   AND (? = 'all' OR LOWER(member_casual) = ?)
             )
            SELECT
                trip_month,
                member_casual,
                SUM(CASE WHEN duration_min > 1440 THEN 1 ELSE 0 END) AS lost_bike_fee_trips,
                COUNT(*) AS total_trips
            FROM durations
            GROUP BY trip_month, member_casual
            ORDER BY member_casual
            """

    async def _fetch_db_rows() -> list[dict[str, object]]:
        t = inspect(CitiBikeTrip).c
        duration_seconds = func.extract("epoch", t.ended_at) - func.extract("epoch", t.started_at)
        duration_min = sa_cast(
            func.greatest(
                literal(0),
                func.floor(duration_seconds / 60.0),
            ),
            Integer,
        )

        stmt = (
            select(
                t.trip_month.label("trip_month"),
                func.lower(t.member_casual).label("member_casual"),
                func.count().filter(duration_min > 1440).label("lost_bike_fee_trips"),
                func.count().label("total_trips"),
            )
            .where(
                t.ended_at.is_not(None),
                t.started_at.is_not(None),
                t.trip_month == month,
            )
            .group_by(t.trip_month, func.lower(t.member_casual))
            .order_by(func.lower(t.member_casual))
        )
        if rider != "all":
            stmt = stmt.where(func.lower(t.member_casual) == rider)

        async for session in get_session():
            result = await _execute_with_statement_timeout(session, stmt)
            return [dict(row) for row in result.mappings().all()]
        return []

    rows: list[dict[str, object]] = []
    try:
        if _is_parquet_source():
            parquet_files = _parquet_files_for_month(month)
            rows = await _duckdb_rows_async(_parquet_query(parquet_files), [month, rider, rider])
        else:
            rows = await _fetch_db_rows()
    except Exception:
        logger.exception("Lost bike fee summary query failed for primary source")
        try:
            if _is_parquet_source():
                rows = await _fetch_db_rows()
            else:
                parquet_files = _parquet_files_for_month(month)
                rows = await _duckdb_rows_async(_parquet_query(parquet_files), [month, rider, rider])
        except Exception:
            logger.exception("Lost bike fee summary query failed for fallback source")
            rows = []

    return [
        {
            "tripMonth": row["trip_month"],
            "memberCasual": row["member_casual"],
            "lostBikeFeeTrips": _coerce_int(row["lost_bike_fee_trips"]),
            "totalTrips": _coerce_int(row["total_trips"]),
        }
        for row in rows
    ]


@app.get("/api/analytics/duration-buckets")
async def analytics_duration_buckets(
    month: str = Query(..., min_length=6, max_length=6),
    rider: str = Query("all", pattern="^(all|member|casual)$"),
    bucket_minutes: int = Query(5, ge=1, le=1400),
):
    def _parquet_query(parquet_files: list[str]) -> str:
        columns = _parquet_columns_for_files(tuple(parquet_files))
        parquet_files_sql = _parquet_file_list_sql(parquet_files)
        trip_projection = _parquet_trip_projection_sql(columns, parquet_files_sql)
        return f"""
            WITH trips AS (
                {trip_projection}
            ),
             durations AS (
                 SELECT
                     trip_month,
                     LOWER(member_casual) AS member_casual,
                     GREATEST(0, CAST(FLOOR(date_diff('second', started_at, ended_at) / 60.0) AS INTEGER)) AS duration_min
                 FROM trips
                 WHERE ended_at IS NOT NULL
                   AND started_at IS NOT NULL
                   AND trip_month = ?
                   AND (? = 'all' OR LOWER(member_casual) = ?)
             ), bucketed AS (
                SELECT
                    d.trip_month,
                    d.member_casual,
                    d.duration_min,
                    CASE
                        WHEN d.duration_min > 1440 THEN 'LOST_BIKE_FEE'
                        ELSE
                            LPAD(CAST(CAST(FLOOR(d.duration_min::DOUBLE / ?) * ? AS INTEGER) AS VARCHAR), 4, '0')
                            || '-'
                            || LPAD(CAST(CAST(FLOOR(d.duration_min::DOUBLE / ?) * ? + ? - 1 AS INTEGER) AS VARCHAR), 4, '0')
                            || ' min'
                    END AS duration_bucket
                FROM durations d
            )
            SELECT
                trip_month,
                member_casual,
                duration_bucket,
                COUNT(*) AS trips,
                (SUM(CASE WHEN duration_min > 1440 THEN 1 ELSE 0 END) > 0) AS lost_bike_fee_flag
            FROM bucketed
            GROUP BY trip_month, member_casual, duration_bucket
            ORDER BY
                member_casual,
                CASE WHEN duration_bucket = 'LOST_BIKE_FEE' THEN 1 ELSE 0 END,
                duration_bucket
            """

    async def _fetch_db_rows() -> list[dict[str, object]]:
        t = inspect(CitiBikeTrip).c
        duration_seconds = func.extract("epoch", t.ended_at) - func.extract("epoch", t.started_at)
        duration_min = sa_cast(
            func.greatest(
                literal(0),
                func.floor(duration_seconds / 60.0),
            ),
            Integer,
        )
        bucket_floor = sa_cast(
            func.floor(sa_cast(duration_min, Float) / bucket_minutes) * bucket_minutes,
            Integer,
        )
        bucket_label = case(
            (duration_min > 1440, literal("LOST_BIKE_FEE")),
            else_=func.concat(
                func.lpad(sa_cast(bucket_floor, String), 4, "0"),
                "-",
                func.lpad(sa_cast(bucket_floor + (bucket_minutes - 1), String), 4, "0"),
                " min",
            ),
        )

        bucketed = (
            select(
                t.trip_month.label("trip_month"),
                func.lower(t.member_casual).label("member_casual"),
                duration_min.label("duration_min"),
                bucket_label.label("duration_bucket"),
            )
            .where(
                t.ended_at.is_not(None),
                t.started_at.is_not(None),
                t.trip_month == month,
            )
            .subquery()
        )

        stmt = (
            select(
                bucketed.c.trip_month,
                bucketed.c.member_casual,
                bucketed.c.duration_bucket,
                func.count().label("trips"),
                func.bool_or(bucketed.c.duration_min > 1440).label("lost_bike_fee_flag"),
            )
            .group_by(bucketed.c.trip_month, bucketed.c.member_casual, bucketed.c.duration_bucket)
            .order_by(
                bucketed.c.member_casual,
                case((bucketed.c.duration_bucket == "LOST_BIKE_FEE", 1), else_=0),
                bucketed.c.duration_bucket,
            )
        )
        if rider != "all":
            stmt = stmt.where(bucketed.c.member_casual == rider)

        async for session in get_session():
            result = await _execute_with_statement_timeout(session, stmt)
            return [dict(row) for row in result.mappings().all()]
        return []

    rows: list[dict[str, object]] = []
    try:
        if _is_parquet_source():
            parquet_files = _parquet_files_for_month(month)
            rows = await _duckdb_rows_async(
                _parquet_query(parquet_files),
                [
                    month,
                    rider,
                    rider,
                    bucket_minutes,
                    bucket_minutes,
                    bucket_minutes,
                    bucket_minutes,
                    bucket_minutes,
                ],
            )
        else:
            rows = await _fetch_db_rows()
    except Exception:
        logger.exception("Duration buckets query failed for primary source")
        try:
            if _is_parquet_source():
                rows = await _fetch_db_rows()
            else:
                parquet_files = _parquet_files_for_month(month)
                rows = await _duckdb_rows_async(
                    _parquet_query(parquet_files),
                    [
                        month,
                        rider,
                        rider,
                        bucket_minutes,
                        bucket_minutes,
                        bucket_minutes,
                        bucket_minutes,
                        bucket_minutes,
                    ],
                )
        except Exception:
            logger.exception("Duration buckets query failed for fallback source")
            rows = []

    return [
        {
            "tripMonth": row["trip_month"],
            "memberCasual": row["member_casual"],
            "bucket": row["duration_bucket"],
            "trips": _coerce_int(row["trips"]),
            "lostBikeFeeFlag": bool(row["lost_bike_fee_flag"]),
        }
        for row in rows
    ]


@app.get("/api/analytics/dashboard-summary")
async def analytics_dashboard_summary(
    month: str = Query(..., min_length=6, max_length=6),
    rider: str = Query("all", pattern="^(all|member|casual)$"),
    top_n: int = Query(10, ge=1, le=50),
):
    def _parquet_query(parquet_files: list[str]) -> str:
        parquet_trips_cte = _parquet_trips_cte_sql(parquet_files)
        return f"""
            WITH trips AS (
                {parquet_trips_cte}
            )
             SELECT
                 rideable_type,
                 member_casual,
                 started_at,
                 ended_at,
                 start_station_name,
                 start_station_id,
                 end_station_name,
                 end_station_id,
                 start_lat,
                 start_lng,
                 end_lat,
                 end_lng
             FROM trips
             WHERE trip_month = ?
               AND started_at IS NOT NULL
               AND ended_at IS NOT NULL
                             AND (? = 'all' OR member_casual = ?)
             """

    async def _fetch_db_rows() -> list[dict[str, object]]:
        t = inspect(CitiBikeTrip).c
        max_dashboard_rows = max(1000, _env_int("ANALYTICS_DASHBOARD_MAX_ROWS", 3000000))
        stmt = (
            select(
                t.rideable_type.label("rideable_type"),
                t.member_casual.label("member_casual"),
                t.started_at.label("started_at"),
                t.ended_at.label("ended_at"),
                t.start_station_name.label("start_station_name"),
                t.start_station_id.label("start_station_id"),
                t.end_station_name.label("end_station_name"),
                t.end_station_id.label("end_station_id"),
                t.start_lat.label("start_lat"),
                t.start_lng.label("start_lng"),
                t.end_lat.label("end_lat"),
                t.end_lng.label("end_lng"),
            )
            .where(
                t.trip_month == month,
                t.started_at.is_not(None),
                t.ended_at.is_not(None),
            )
            .limit(max_dashboard_rows)
        )
        if rider != "all":
            stmt = stmt.where(t.member_casual == rider)

        async for session in get_session():
            result = await _execute_with_statement_timeout(session, stmt)
            return [dict(row) for row in result.mappings().all()]
        return []

    rows: list[dict[str, object]] = []
    try:
        if _is_parquet_source():
            parquet_files = _parquet_files_for_month(month)
            rows = await _duckdb_rows_async(_parquet_query(parquet_files), [month, rider, rider])
        else:
            rows = await _fetch_db_rows()
    except Exception:
        logger.exception("Dashboard summary query failed for primary source")
        try:
            if _is_parquet_source():
                rows = await _fetch_db_rows()
            else:
                parquet_files = _parquet_files_for_month(month)
                rows = await _duckdb_rows_async(_parquet_query(parquet_files), [month, rider, rider])
        except Exception:
            logger.exception("Dashboard summary query failed for fallback source")
            rows = []

    total_trips = 0
    actual_duration_total = 0.0
    estimated_duration_total = 0.0
    actual_duration_with_estimate_total = 0.0
    estimated_trip_count = 0
    station_usage: dict[tuple[str, str], dict[str, object]] = {}
    station_flow: dict[tuple[str, str, str, str], int] = defaultdict(int)
    duration_by_hour: dict[tuple[int, str], dict[str, float | int | str]] = {}
    histogram_by_bike: dict[str, int] = defaultdict(int)
    histogram_by_rider: dict[str, int] = defaultdict(int)
    origin_spread: dict[tuple[float | None, float | None, str, str], int] = defaultdict(int)
    coord_pairs: dict[tuple[float | None, float | None, float | None, float | None], int] = defaultdict(int)
    actual_vs_estimated: dict[tuple[str, str], dict[str, float | int | str]] = {}

    for row in rows:
        total_trips += 1
        rideable_type = str(row["rideable_type"] or "unknown")
        member_casual = str(row["member_casual"] or "unknown").lower()

        histogram_by_bike[rideable_type] += 1
        histogram_by_rider[member_casual] += 1

        started_at = _coerce_datetime(row["started_at"])
        ended_at = _coerce_datetime(row["ended_at"])
        actual_minutes = max(0.0, (ended_at - started_at).total_seconds() / 60)
        actual_duration_total += actual_minutes

        hour_key = (int(started_at.hour), member_casual)
        hour_bucket = duration_by_hour.setdefault(
            hour_key,
            {"hour": int(started_at.hour), "memberCasual": member_casual, "tripCount": 0, "averageDurationMinutes": 0.0},
        )
        hour_bucket["tripCount"] = int(hour_bucket["tripCount"]) + 1
        hour_bucket["averageDurationMinutes"] = float(hour_bucket["averageDurationMinutes"]) + actual_minutes

        start_station_name = str(row["start_station_name"] or "Unknown station")
        start_station_id = str(row["start_station_id"] or "Unknown station")
        end_station_name = str(row["end_station_name"] or "Unknown station")
        end_station_id = str(row["end_station_id"] or "Unknown station")

        start_key = (start_station_name, start_station_id)
        start_station = station_usage.setdefault(
            start_key,
            {
                "stationName": start_station_name,
                "stationId": start_station_id,
                "arrivals": 0,
                "departures": 0,
                "totalTrips": 0,
            },
        )
        start_station["departures"] = _coerce_int(start_station["departures"]) + 1
        start_station["totalTrips"] = _coerce_int(start_station["totalTrips"]) + 1

        end_key = (end_station_name, end_station_id)
        end_station = station_usage.setdefault(
            end_key,
            {
                "stationName": end_station_name,
                "stationId": end_station_id,
                "arrivals": 0,
                "departures": 0,
                "totalTrips": 0,
            },
        )
        end_station["arrivals"] = _coerce_int(end_station["arrivals"]) + 1
        end_station["totalTrips"] = _coerce_int(end_station["totalTrips"]) + 1

        station_flow[(start_station_name, start_station_id, end_station_name, end_station_id)] += 1

        start_lat = cast(float | None, row["start_lat"])
        start_lng = cast(float | None, row["start_lng"])
        end_lat = cast(float | None, row["end_lat"])
        end_lng = cast(float | None, row["end_lng"])

        rounded_start_lat = _rounded(start_lat)
        rounded_start_lng = _rounded(start_lng)
        rounded_end_lat = _rounded(end_lat)
        rounded_end_lng = _rounded(end_lng)

        origin_spread[(rounded_start_lat, rounded_start_lng, member_casual, rideable_type)] += 1
        coord_pairs[(rounded_start_lat, rounded_start_lng, rounded_end_lat, rounded_end_lng)] += 1

        if start_lat is not None and start_lng is not None and end_lat is not None and end_lng is not None:
            distance_miles = _haversine_miles(
                start_lat,
                start_lng,
                end_lat,
                end_lng,
            )
            estimated_minutes = (distance_miles / ESTIMATED_SPEED_MPH) * 60
            estimated_duration_total += estimated_minutes
            actual_duration_with_estimate_total += actual_minutes
            estimated_trip_count += 1

            group_key = (member_casual, rideable_type)
            group_stats = actual_vs_estimated.setdefault(
                group_key,
                {
                    "memberCasual": member_casual,
                    "rideableType": rideable_type,
                    "tripCount": 0,
                    "averageActualMinutes": 0.0,
                    "averageEstimatedMinutes": 0.0,
                },
            )
            group_stats["tripCount"] = int(group_stats["tripCount"]) + 1
            group_stats["averageActualMinutes"] = float(group_stats["averageActualMinutes"]) + actual_minutes
            group_stats["averageEstimatedMinutes"] = float(group_stats["averageEstimatedMinutes"]) + estimated_minutes

    summary = {
        "tripCount": total_trips,
        "averageActualMinutes": (actual_duration_with_estimate_total / estimated_trip_count) if estimated_trip_count else 0.0,
        "averageEstimatedMinutes": (estimated_duration_total / estimated_trip_count) if estimated_trip_count else 0.0,
        "averageDeltaMinutes": (
            (actual_duration_with_estimate_total / estimated_trip_count) - (estimated_duration_total / estimated_trip_count)
            if estimated_trip_count
            else 0.0
        ),
    }

    def _finalize_average(payload: dict[str, float | int | str]) -> dict[str, float | int | str]:
        trip_count = int(payload["tripCount"])
        if trip_count:
            payload["averageDurationMinutes"] = float(payload["averageDurationMinutes"]) / trip_count
        return payload

    duration_by_hour_rows = [
        _finalize_average(bucket)
        for _, bucket in sorted(duration_by_hour.items(), key=lambda item: (item[0][0], item[0][1]))
    ]

    actual_vs_estimated_rows = []
    for _, bucket in sorted(actual_vs_estimated.items(), key=lambda item: (item[0][0], item[0][1])):
        trip_count = int(bucket["tripCount"])
        average_actual = float(bucket["averageActualMinutes"]) / trip_count if trip_count else 0.0
        average_estimated = float(bucket["averageEstimatedMinutes"]) / trip_count if trip_count else 0.0
        actual_vs_estimated_rows.append(
            {
                "memberCasual": bucket["memberCasual"],
                "rideableType": bucket["rideableType"],
                "tripCount": trip_count,
                "averageActualMinutes": average_actual,
                "averageEstimatedMinutes": average_estimated,
                "deltaMinutes": average_actual - average_estimated,
            }
        )

    return {
        "summary": summary,
        "stationUsage": sorted(
            station_usage.values(),
            key=lambda item: (-_coerce_int(item["totalTrips"]), str(item["stationName"]), str(item["stationId"])),
        )[:top_n],
        "histogramByBikeType": [
            {"rideableType": key, "tripCount": value}
            for key, value in sorted(histogram_by_bike.items(), key=lambda item: item[0])
        ],
        "histogramByRiderType": [
            {"memberCasual": key, "tripCount": value}
            for key, value in sorted(histogram_by_rider.items(), key=lambda item: item[0])
        ],
        "durationByHour": duration_by_hour_rows,
        "originSpread": [
            {
                "startLat": item[0],
                "startLng": item[1],
                "memberCasual": item[2],
                "rideableType": item[3],
                "tripCount": value,
            }
            for item, value in sorted(origin_spread.items(), key=lambda entry: (-entry[1], str(entry[0])))[:top_n]
        ],
        "stationFlow": [
            {
                "startStationName": item[0],
                "startStationId": item[1],
                "endStationName": item[2],
                "endStationId": item[3],
                "tripCount": value,
            }
            for item, value in sorted(station_flow.items(), key=lambda entry: (-entry[1], str(entry[0])))[:top_n]
        ],
        "coordinatePairs": [
            {
                "startLat": item[0],
                "startLng": item[1],
                "endLat": item[2],
                "endLng": item[3],
                "tripCount": value,
            }
            for item, value in sorted(coord_pairs.items(), key=lambda entry: (-entry[1], str(entry[0])))[:top_n]
        ],
        "actualVsEstimated": actual_vs_estimated_rows,
        "estimatedSpeedMph": ESTIMATED_SPEED_MPH,
    }

if __name__ == "__main__":
    logger.info("Starting Uvicorn server on 127.0.0.1:8000")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)

#dev commands:
# - FastAPI CLI: python3 -m fastapi dev main.py
# - Uvicorn directly: uvicorn main.py --reload
# - Docker container: docker-compose up --build in root