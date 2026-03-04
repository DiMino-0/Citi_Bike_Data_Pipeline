import argparse
import logging
import os
import re
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, List, Tuple

import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import SQLModel, Session, create_engine

try:
    from database.ingest import main as ingest_main
    from database.models import CitiBikeTrip
except ImportError:
    from server.database.ingest import main as ingest_main
    from server.database.models import CitiBikeTrip


logger = logging.getLogger(__name__)

SEED_JOB_ADVISORY_LOCK_ID = 913004271

MONTH_COLUMNS = [
    "ride_id",
    "rideable_type",
    "started_at",
    "ended_at",
    "start_station_name",
    "start_station_id",
    "end_station_name",
    "end_station_id",
    "start_lat",
    "start_lng",
    "end_lat",
    "end_lng",
    "member_casual",
]


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def _sync_db_url(db_url: str) -> str:
    if db_url.startswith("postgresql+asyncpg://"):
        return db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    return db_url


def _validate_month(month: str) -> str:
    if len(month) != 6 or not month.isdigit():
        raise ValueError(f"Invalid month '{month}'. Expected YYYYMM format.")
    return month


def _month_to_date(month: str) -> date:
    normalized = _validate_month(month)
    year = int(normalized[:4])
    month_num = int(normalized[4:6])
    if month_num < 1 or month_num > 12:
        raise ValueError(f"Invalid month '{month}'. Expected month between 01 and 12.")
    return date(year, month_num, 1)


def _parse_month_range(month_range: str) -> List[str]:
    match = re.fullmatch(r"\s*(\d{6})\s*(?:\.\.|:|-)\s*(\d{6})\s*", month_range)
    if not match:
        raise ValueError(f"Invalid range '{month_range}'. Expected format like YYYYMM..YYYYMM.")

    first = _month_to_date(match.group(1))
    second = _month_to_date(match.group(2))
    start = min(first, second)
    end = max(first, second)

    values: List[str] = []
    cursor = end
    while cursor >= start:
        values.append(cursor.strftime("%Y%m"))
        cursor = (cursor.replace(day=1) - timedelta(days=1))
    return values


def _resolve_target_months(target_month: str | None, target_range: str | None) -> List[str]:
    if target_range:
        return _parse_month_range(target_range)
    if target_month:
        return [_validate_month(target_month)]

    today = date.today()
    previous_month = (today.replace(day=1) - timedelta(days=1))
    return [previous_month.strftime("%Y%m")]


def _months_missing_in_db(session: Session, target_months: List[str]) -> List[str]:
    missing: List[str] = []
    for month_value in target_months:
        result = session.connection().exec_driver_sql(
            "SELECT 1 FROM citibike_trips WHERE trip_month = %s LIMIT 1",
            (month_value,),
        )
        if result.scalar() is None:
            missing.append(month_value)
    return missing


def _months_to_selection(target_months: List[str]) -> tuple[str | None, str | None]:
    if not target_months:
        return None, None
    if len(target_months) == 1:
        return target_months[0], None
    # target_months are newest -> oldest
    return None, f"{target_months[-1]}..{target_months[0]}"


def _month_from_file_name(path: Path) -> str:
    stem = path.stem
    if not stem.startswith("data"):
        raise ValueError(f"Unexpected parquet file name: {path.name}")
    month = stem.replace("data", "", 1)
    return _validate_month(month)


def _find_month_files(data_dir: Path, target_month: str | None, target_range: str | None) -> List[Path]:
    files = sorted(
        [p for p in data_dir.glob("data*.parquet") if len(p.stem) == 10 and p.stem[4:].isdigit()],
        key=lambda p: p.stem,
        reverse=True,
    )
    files_by_month = {p.stem[4:]: p for p in files}

    if target_range:
        months_in_range = _parse_month_range(target_range)
        selected_files: List[Path] = []
        missing_months: List[str] = []
        for month_value in months_in_range:
            month_file = files_by_month.get(month_value)
            if month_file is None:
                missing_months.append(month_value)
                continue
            selected_files.append(month_file)

        if missing_months:
            raise FileNotFoundError(
                f"Month parquet files not found for: {', '.join(missing_months)}"
            )
        return selected_files

    if target_month:
        target = data_dir / f"data{_validate_month(target_month)}.parquet"
        if not target.exists():
            raise FileNotFoundError(f"Month parquet not found: {target}")
        return [target]

    if not files:
        return []
    return [files[0]]


def _prepare_df(df: pd.DataFrame, trip_month: str) -> pd.DataFrame:
    prepared = df.copy()

    for column in MONTH_COLUMNS:
        if column not in prepared.columns:
            prepared[column] = None

    prepared = prepared[MONTH_COLUMNS]
    prepared["started_at"] = pd.to_datetime(prepared["started_at"], errors="coerce")
    prepared["ended_at"] = pd.to_datetime(prepared["ended_at"], errors="coerce")
    prepared = prepared.dropna(subset=["ride_id", "rideable_type", "started_at", "ended_at", "member_casual"])

    prepared["trip_month"] = trip_month
    return prepared


def _normalize_nulls(record: dict) -> dict:
    normalized = {}
    for key, value in record.items():
        if pd.isna(value):
            normalized[key] = None
        else:
            normalized[key] = value
    return normalized


def _chunked(records: List[dict], size: int) -> Iterable[List[dict]]:
    for i in range(0, len(records), size):
        yield records[i : i + size]


def seed_month_file(session: Session, parquet_file: Path, batch_size: int = 5000) -> Tuple[int, int]:
    trip_month = _month_from_file_name(parquet_file)
    logger.info("Seeding %s", parquet_file.name)

    df = pd.read_parquet(parquet_file)
    prepared = _prepare_df(df, trip_month)
    records = [_normalize_nulls(row) for row in prepared.to_dict(orient="records")]

    if not records:
        logger.info("No valid rows found for %s", parquet_file.name)
        return 0, 0

    inserted = 0
    for chunk in _chunked(records, batch_size):
        stmt = pg_insert(CitiBikeTrip).values(chunk)
        stmt = stmt.on_conflict_do_nothing(index_elements=["ride_id"])
        result = session.exec(stmt)
        session.commit()
        if result.rowcount and result.rowcount > 0:
            inserted += int(result.rowcount)

    return len(records), inserted


def _remove_parquet_file(parquet_file: Path) -> None:
    try:
        parquet_file.unlink(missing_ok=True)
        logger.info("Removed temporary parquet file: %s", parquet_file.name)
    except Exception:
        logger.exception("Failed to remove temporary parquet file: %s", parquet_file)


def parse_args() -> argparse.Namespace:
    default_data_dir = Path(__file__).resolve().parent.parent / "scratch" / "data"
    env_data_dir = os.getenv("SEED_DATA_DIR")
    if env_data_dir:
        default_data_dir = Path(env_data_dir)

    parser = argparse.ArgumentParser(
        description="Seed PostgreSQL from Citi Bike monthly parquet files using SQLModel schema."
    )
    parser.add_argument("--month", help="Specific month to seed in YYYYMM format.")
    parser.add_argument("--range", dest="month_range", help="Inclusive range in format YYYYMM..YYYYMM. Overrides --month.")
    parser.add_argument("--data-dir", default=str(default_data_dir), help="Directory containing dataYYYYMM.parquet files.")
    parser.add_argument("--db-url", default=os.getenv("DB_URL"), help="Database URL. Defaults to DB_URL env var.")
    parser.add_argument(
        "--ingest-if-missing",
        action="store_true",
        help="Run ingest to fetch recent month parquet files when none are found.",
    )
    return parser.parse_args()


def run_seed(
    db_url: str,
    data_dir: str | Path,
    month: str | None = None,
    month_range: str | None = None,
    ingest_if_missing: bool = False,
) -> Tuple[int, int, int]:
    if not db_url:
        raise RuntimeError("DB URL is required.")

    resolved_data_dir = Path(data_dir)
    try:
        resolved_data_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        fallback_data_dir = Path(tempfile.gettempdir()) / "citibike-data"
        logger.warning(
            "Seed data directory is not writable: %s. Falling back to %s",
            resolved_data_dir,
            fallback_data_dir,
        )
        fallback_data_dir.mkdir(parents=True, exist_ok=True)
        resolved_data_dir = fallback_data_dir

    sync_url = _sync_db_url(db_url)
    engine = create_engine(sync_url)

    with Session(engine) as session:
        lock_result = session.connection().exec_driver_sql(
            "SELECT pg_try_advisory_lock(%s)",
            (SEED_JOB_ADVISORY_LOCK_ID,),
        )
        lock_acquired = bool(lock_result.scalar())

        if not lock_acquired:
            logger.info("Seed skipped: another process holds advisory lock")
            return 0, 0, 0

        SQLModel.metadata.create_all(engine)

        requested_months = _resolve_target_months(month, month_range)
        months_to_seed = _months_missing_in_db(session, requested_months)

        if not months_to_seed:
            logger.info("Seed skipped: target month(s) already present in DB: %s", requested_months)
            return 0, 0, 0

        effective_month, effective_range = _months_to_selection(months_to_seed)

        month_files: List[Path] = []
        try:
            month_files = _find_month_files(resolved_data_dir, effective_month, effective_range)
        except FileNotFoundError:
            if not ingest_if_missing:
                raise
            logger.info(
                "Target month/range parquet is missing. Running ingest before retry.",
            )

        if (not month_files) and ingest_if_missing:
            logger.info("No parquet files found. Running ingest.")
            ingest_main(
                output_dir=str(resolved_data_dir),
                force=True,
                month=effective_month,
                month_range=effective_range,
            )
            month_files = _find_month_files(resolved_data_dir, effective_month, effective_range)

        if not month_files:
            raise FileNotFoundError(
                f"No parquet files found in {resolved_data_dir}. Expected files like dataYYYYMM.parquet"
            )

        total_rows = 0
        total_inserted = 0
        try:
            for month_file in month_files:
                rows, inserted = seed_month_file(session, month_file)
                total_rows += rows
                total_inserted += inserted
                _remove_parquet_file(month_file)
        finally:
            session.connection().exec_driver_sql(
                "SELECT pg_advisory_unlock(%s)",
                (SEED_JOB_ADVISORY_LOCK_ID,),
            )

    logger.info(
        "Seed complete. Files=%d Rows processed=%d Rows inserted=%d",
        len(month_files),
        total_rows,
        total_inserted,
    )
    return len(month_files), total_rows, total_inserted


def main() -> None:
    _configure_logging()
    args = parse_args()
    run_seed(
        db_url=args.db_url,
        data_dir=args.data_dir,
        month=args.month,
        month_range=args.month_range,
        ingest_if_missing=args.ingest_if_missing,
    )


if __name__ == "__main__":
    main()
