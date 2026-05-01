import argparse
import csv
import io
import logging
import os
import re
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Tuple
from zoneinfo import ZoneInfo

import pandas as pd
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

COPY_INSERT_COLUMNS = MONTH_COLUMNS + ["trip_month", "created_at"]
NEW_YORK_TZ = ZoneInfo("America/New_York")
TEMP_SEED_TABLE = "tmp_citibike_seed"


def _copy_insert_sql() -> str:
	columns = ", ".join(COPY_INSERT_COLUMNS)
	return (
		f"COPY {TEMP_SEED_TABLE} ({columns}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')"
	)


def _configure_logging() -> None:
    root_logger = logging.getLogger()
    # Only configure if no handlers are already attached
    if not root_logger.handlers:
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
	"""Parse a month range string and return list of months in reverse chronological order."""
	pattern = r"\s*(\d{4}|\d{6})\s*(?:\.\.|:|-)\s*(\d{4}|\d{6})\s*"
	match = re.fullmatch(pattern, month_range)
	
	if not match:
		raise ValueError(f"Invalid range '{month_range}'. Expected format like YYYY..YYYYMM.")

	first_low, first_high = _parse_range_bound(match.group(1))
	second_low, second_high = _parse_range_bound(match.group(2))

	start_date = min(first_low, second_low)
	end_date = max(first_high, second_high)

	values: List[str] = []
	current_date = end_date
	
	while current_date >= start_date:
		month_str = current_date.strftime("%Y%m")
		values.append(month_str)
		
		# Move to previous month
		first_day = current_date.replace(day=1)
		previous_day = first_day - timedelta(days=1)
		current_date = previous_day
	
	return values


def _parse_range_bound(value: str) -> tuple[date, date]:
	"""Parse YYYY or YYYYMM into a (low, high) month bound."""
	if re.fullmatch(r"\d{6}", value):
		parsed = _month_to_date(value)
		return parsed, parsed

	if re.fullmatch(r"\d{4}", value):
		year = int(value)
		return date(year, 1, 1), date(year, 12, 1)

	raise ValueError(f"Invalid month bound '{value}'. Expected YYYY or YYYYMM format.")


def _resolve_target_months(target_month: str | None, target_range: str | None) -> List[str]:
	"""Determine which months to seed based on provided parameters."""
	# Priority: range > specific month > default previous month
	if target_range:
		logger.debug("Resolving months from range: %s", target_range)
		return _parse_month_range(target_range)
	
	if target_month:
		logger.debug("Resolving specific month: %s", target_month)
		validated_month = _validate_month(target_month)
		return [validated_month]

	# Default: use previous month
	today = date.today()
	previous_month_date = today.replace(day=1) - timedelta(days=1)
	default_month = previous_month_date.strftime("%Y%m")
	logger.debug("Using default previous month: %s", default_month)
	return [default_month]


def _month_exists_in_db(session: Session, month_value: str) -> bool:
	"""Return True when at least one row exists for the month in citibike_trips."""
	query = "SELECT 1 FROM citibike_trips WHERE trip_month = %s LIMIT 1"
	result = session.connection().exec_driver_sql(query, (month_value,))
	return result.scalar() is not None


def _month_row_count_in_db(session: Session, month_value: str) -> int:
	"""Return row count for a given month in citibike_trips."""
	query = "SELECT COUNT(*) FROM citibike_trips WHERE trip_month = %s"
	result = session.connection().exec_driver_sql(query, (month_value,))
	count = result.scalar()
	return int(count) if count is not None else 0

def _months_missing_in_db(session: Session, target_months: List[str]) -> List[str]:
	"""Check which target months are not yet loaded in the database."""
	missing: List[str] = []
	present_months: List[str] = []
	
	for month_value in target_months:
		if not _month_exists_in_db(session, month_value):
			logger.debug("Month %s not found in database", month_value)
			missing.append(month_value)
		else:
			logger.debug("Month %s already present in database", month_value)
			present_months.append(month_value)

	if present_months:
		logger.info(
			"Months already present in DB: %s",
			", ".join(present_months),
		)
	
	return missing


def _months_to_selection(target_months: List[str]) -> tuple[str | None, str | None]:
	"""Convert list of months to month/month_range parameters for ingest or seed."""
	# If empty, return no selection
	if not target_months:
		return None, None
	
	# If single month, specify just the month
	if len(target_months) == 1:
		single_month = target_months[0]
		return single_month, None
	
	# If multiple months, use range format (oldest to newest)
	# target_months are in reverse order (newest first), so reverse to get oldest first
	oldest_month = target_months[-1]
	newest_month = target_months[0]
	month_range = f"{oldest_month}..{newest_month}"
	
	return None, month_range

def _month_from_file_name(path: Path) -> str:
    stem = path.stem
    if not stem.startswith("data"):
        raise ValueError(f"Unexpected parquet file name: {path.name}")
    month = stem.replace("data", "", 1)
    return _validate_month(month)


def _resolve_month_files_for_targets(data_dir: Path, target_months: List[str]) -> tuple[List[Path], List[str]]:
	"""Return (existing_files, missing_months) for the provided target months, preserving order."""
	files: List[Path] = []
	missing: List[str] = []

	for month_value in target_months:
		validated = _validate_month(month_value)
		target_path = data_dir / f"data{validated}.parquet"
		if target_path.exists():
			files.append(target_path)
		else:
			missing.append(validated)

	return files, missing


def _find_month_files(data_dir: Path, target_month: str | None, target_range: str | None) -> List[Path]:
	"""Find parquet files matching the target month or range in the data directory."""
	# Find all matching parquet files
	all_parquet_files = [
		p for p in data_dir.glob("data*.parquet") 
		if len(p.stem) == 10 and p.stem[4:].isdigit()
	]
	
	# Sort by filename (which is by month)
	sorted_files = sorted(all_parquet_files, key=lambda p: p.stem, reverse=True)
	logger.debug("Found %d parquet files in %s", len(sorted_files), data_dir)
	
	# Build map of month -> file path
	files_by_month = {p.stem[4:]: p for p in sorted_files}

	# Handle month range selection
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

	# Handle single month selection
	if target_month:
		validated_month = _validate_month(target_month)
		target_path = data_dir / f"data{validated_month}.parquet"
		
		if not target_path.exists():
			raise FileNotFoundError(f"Month parquet not found: {target_path}")
		
		return [target_path]

	# Default: use most recent month file
	if not sorted_files:
		logger.debug("No parquet files found in %s", data_dir)
		return []
	
	most_recent = sorted_files[0]
	logger.debug("Using most recent file: %s", most_recent.name)
	return [most_recent]

def _prepare_df(df: pd.DataFrame, trip_month: str) -> pd.DataFrame:
	"""Prepare and clean Citi Bike trip dataframe for insertion."""
	# Keep only the columns we need (select upfront to reduce memory)
	missing_cols = [col for col in MONTH_COLUMNS if col not in df.columns]
	if missing_cols:
		for col in missing_cols:
			logger.debug("Adding missing column: %s", col)
			df[col] = None
	
	prepared = df[MONTH_COLUMNS].copy()
	
	# Drop rows with missing required fields BEFORE timestamp conversion (faster)
	required_columns = ["ride_id", "rideable_type", "started_at", "ended_at", "member_casual"]
	rows_before = len(prepared)
	prepared = prepared.dropna(subset=required_columns)
	rows_removed = rows_before - len(prepared)
	
	if rows_removed > 0:
		logger.debug("Removed %d rows with missing required fields", rows_removed)
	
	# Convert timestamp strings to datetime objects (only non-null rows now)
	prepared["started_at"] = pd.to_datetime(prepared["started_at"], errors="coerce", utc=False)
	prepared["ended_at"] = pd.to_datetime(prepared["ended_at"], errors="coerce", utc=False)
	
	# Add the trip month for reference
	prepared["trip_month"] = trip_month
	# Ensure COPY provides a value for created_at across schemas with/without server defaults.
	prepared["created_at"] = datetime.now(NEW_YORK_TZ).replace(tzinfo=None, microsecond=0)
	
	logger.debug("Prepared dataframe: %d rows, %d columns", len(prepared), len(prepared.columns))
	return prepared


def _insert_batch(session: Session, prepared: pd.DataFrame) -> int:
	"""Insert a batch of prepared rows directly into the database with conflict handling."""
	if prepared.empty:
		return 0

	batch_size = len(prepared)
	try:
		buffer = io.StringIO()
		prepared[COPY_INSERT_COLUMNS].to_csv(
			buffer,
			index=False,
			header=False,
			na_rep="\\N",
			quoting=csv.QUOTE_MINIMAL,
			date_format="%Y-%m-%d %H:%M:%S.%f",
		)
		buffer.seek(0)

		sql_connection = session.connection()
		dbapi_connection = sql_connection.connection
		cursor = dbapi_connection.cursor()
		cursor.execute(
			f"""
			CREATE TEMP TABLE IF NOT EXISTS {TEMP_SEED_TABLE} (
				LIKE citibike_trips INCLUDING DEFAULTS INCLUDING GENERATED
				EXCLUDING CONSTRAINTS EXCLUDING INDEXES
			)
			"""
		)
		cursor.execute(f"TRUNCATE {TEMP_SEED_TABLE}")
		cursor.copy_expert(_copy_insert_sql(), buffer)
		cursor.execute(
			f"""
			INSERT INTO citibike_trips ({", ".join(COPY_INSERT_COLUMNS)})
			SELECT {", ".join(COPY_INSERT_COLUMNS)}
			FROM {TEMP_SEED_TABLE}
			ON CONFLICT (ride_id) DO NOTHING
			"""
		)
		result = cursor.rowcount if cursor.rowcount else 0
		session.commit()
		return result
	except Exception as e:
		session.rollback()
		logger.error("Failed to insert batch of %d records: %s", batch_size, e)
		raise


def seed_month_file(session: Session, parquet_file: Path, batch_size: int = 100_000) -> Tuple[int, int]:
	"""Load data from a parquet file into the database, returning (total_rows, rows_inserted)."""
	trip_month = _month_from_file_name(parquet_file)
	logger.info("Seeding %s", parquet_file.name)
	if parquet_file.exists():
		logger.info("Parquet size for %s: %.2f MB", parquet_file.name, parquet_file.stat().st_size / (1024 * 1024))

	# Load and prepare data
	parquet_started = time.perf_counter()
	logger.info("Reading parquet for %s", parquet_file.name)
	df = pd.read_parquet(parquet_file, columns=MONTH_COLUMNS)
	logger.info(
		"Read parquet for %s in %.2fs (rows=%d)",
		parquet_file.name,
		time.perf_counter() - parquet_started,
		len(df),
	)

	prepare_started = time.perf_counter()
	logger.info("Preparing dataframe for %s", parquet_file.name)
	prepared = _prepare_df(df, trip_month)
	logger.info(
		"Prepared dataframe for %s in %.2fs (rows=%d)",
		parquet_file.name,
		time.perf_counter() - prepare_started,
		len(prepared),
	)

	if prepared.empty:
		logger.info("No valid rows found for %s", parquet_file.name)
		return 0, 0

	if batch_size <= 0:
		raise ValueError("batch_size must be greater than 0")

	total_rows = len(prepared)
	total_inserted = 0
	total_batches = ((total_rows - 1) // batch_size) + 1

	for start in range(0, total_rows, batch_size):
		stop = min(start + batch_size, total_rows)
		batch = prepared.iloc[start:stop]
		batch_number = (start // batch_size) + 1
		batch_started = time.perf_counter()
		logger.info(
			"Inserting batch %d/%d for %s (rows %d-%d)",
			batch_number,
			total_batches,
			parquet_file.name,
			start + 1,
			stop,
		)
		inserted = _insert_batch(session, batch)
		total_inserted += inserted
		logger.info(
			"Inserted batch %d/%d for %s in %.2fs (inserted=%d)",
			batch_number,
			total_batches,
			parquet_file.name,
			time.perf_counter() - batch_started,
			inserted,
		)

	logger.info(
		"Completed %s: total rows=%d, inserted=%d batches=%d",
		parquet_file.name,
		total_rows,
		total_inserted,
		total_batches,
	)
	return total_rows, total_inserted


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
	parser.add_argument(
		"--range",
		dest="month_range",
		help="Inclusive range in format YYYYMM..YYYYMM. Overrides --month.",
	)
	parser.add_argument(
		"--data-dir",
		default=str(default_data_dir),
		help="Directory containing dataYYYYMM.parquet files.",
	)
	parser.add_argument(
		"--db-url",
		default=os.getenv("DB_URL"),
		help="Database URL. Defaults to DB_URL env var.",
	)
	parser.add_argument(
		"--ingest-if-missing",
		action="store_true",
		help="Run ingest to fetch recent month parquet files when none are found.",
	)
	parser.add_argument(
		"--backfill-missing-rows",
		action="store_true",
		help=(
			"Attempt to backfill missing rows for target months even when rows already exist in DB. "
			"Useful for partially seeded months."
		),
	)
	return parser.parse_args()


def run_seed(
    db_url: str,
    data_dir: str | Path,
    month: str | None = None,
    month_range: str | None = None,
    ingest_if_missing: bool = False,
	backfill_missing_rows: bool = False,
	force_clear_lock: bool = False,
) -> Tuple[int, int, int]:
	"""
	Seed the database with Citi Bike trip data.
	
	Args:
		db_url: Database connection URL
		data_dir: Directory containing parquet files
		month: Specific month to seed (YYYYMM format)
		month_range: Range of months to seed (YYYYMM..YYYYMM format)
		ingest_if_missing: Fetch missing month files via ingest if not found locally
		backfill_missing_rows: Re-seed target months to attempt filling missing rows
		force_clear_lock: Force-clear any lingering advisory locks (for startup recovery)
	
	Returns: (files_processed, total_rows, rows_inserted)
	"""
	if not db_url:
		raise RuntimeError("DB URL is required.")
	

	# Prepare data directory
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

	# Convert async URL to sync URL for SQLAlchemy
	sync_url = _sync_db_url(db_url)
	engine = create_engine(sync_url)

	# If using DuckDB as the target database, avoid creating constraints/indexes
	# because they can slow down bulk loads. Create a minimal table schema
	# without UNIQUE/PK constraints or additional indexes instead of
	# SQLModel.metadata.create_all(engine) which would add them.
	is_duckdb = str(sync_url).startswith("duckdb://")
	if is_duckdb:
		# Create a lightweight table suitable for bulk COPY loads.
		create_table_sql = (
			"CREATE TABLE IF NOT EXISTS citibike_trips ("
			"id BIGINT, "
			"ride_id VARCHAR, "
			"rideable_type VARCHAR, "
			"started_at TIMESTAMP, "
			"ended_at TIMESTAMP, "
			"start_station_name VARCHAR, "
			"start_station_id VARCHAR, "
			"end_station_name VARCHAR, "
			"end_station_id VARCHAR, "
			"start_lat DOUBLE, "
			"start_lng DOUBLE, "
			"end_lat DOUBLE, "
			"end_lng DOUBLE, "
			"member_casual VARCHAR, "
			"trip_month VARCHAR(6), "
			"created_at TIMESTAMP"
			")"
		)
		with engine.begin() as conn:
			# Use exec_driver_sql for raw SQL compatibility across dialects
			conn.exec_driver_sql(create_table_sql)

	with Session(engine) as session:
		# Force-clear any lingering advisory locks if requested (handles crashed seed operations)
		if force_clear_lock:
			try:
				session.connection().exec_driver_sql(
					"SELECT pg_advisory_unlock_all()"
				)
				logger.debug("Cleared any lingering advisory locks from previous operations")
			except Exception as e:
				logger.warning("Failed to clear lingering advisory locks: %s", e)

		# Attempt to acquire advisory lock for this seeding operation
		lock_result = session.connection().exec_driver_sql(
			"SELECT pg_try_advisory_lock(%s)",
			(SEED_JOB_ADVISORY_LOCK_ID,),
		)
		lock_acquired = bool(lock_result.scalar())

		if not lock_acquired:
			logger.info("Seed skipped: another process holds advisory lock")
			return 0, 0, 0

		# Ensure database schema is created
		SQLModel.metadata.create_all(engine)

		# Determine which months to seed
		requested_months = _resolve_target_months(month, month_range)
		logger.debug("Requested months: %s", requested_months)

		mode_parts = []
		if ingest_if_missing:
			mode_parts.append("download")
		mode_parts.append("seed")
		mode_str = "/".join(mode_parts)
    
		requested_months = _resolve_target_months(month, month_range)
		logger.info(
			"Starting %s mode for months: %s (ingest_if_missing=%s, backfill=%s)",
			mode_str,
			", ".join(requested_months),
			ingest_if_missing,
			backfill_missing_rows,
		)
		
		# When backfilling, reseed target months and rely on ON CONFLICT(ride_id) DO NOTHING
		# to only insert rows that are truly missing.
		if backfill_missing_rows:
			months_to_seed = requested_months
		else:
			# Default behavior: only seed months with no rows yet.
			months_to_seed = _months_missing_in_db(session, requested_months)
		
		if not months_to_seed:
			logger.info("Seed skipped: target month(s) already present in DB: %s", requested_months)
			return 0, 0, 0
		
		logger.info("Months to seed: %s", months_to_seed)

		# Resolve local month files and only ingest the specific missing months.
		month_files, missing_local_months = _resolve_month_files_for_targets(resolved_data_dir, months_to_seed)

		if backfill_missing_rows and ingest_if_missing:
			logger.info(
				"Backfill mode enabled; re-ingesting target months before seed: %s",
				months_to_seed,
			)
			for target_month in months_to_seed:
				try:
					ingest_main(
						output_dir=str(resolved_data_dir),
						month=target_month,
					)
				except Exception:
					logger.exception("Failed to refresh month %s during backfill", target_month)

			month_files, missing_local_months = _resolve_month_files_for_targets(resolved_data_dir, months_to_seed)

		if missing_local_months:
			if not ingest_if_missing:
				raise FileNotFoundError(
					f"Month parquet files not found for: {', '.join(missing_local_months)}"
				)

			logger.info(
				"Missing %d month parquet files locally; ingesting only missing months: %s",
				len(missing_local_months),
				missing_local_months,
			)
			for missing_month in missing_local_months:
				try:
					ingest_main(
						output_dir=str(resolved_data_dir),
						month=missing_month,
					)
				except Exception:
					logger.exception("Failed to ingest missing month %s", missing_month)

			month_files, missing_after_ingest = _resolve_month_files_for_targets(resolved_data_dir, months_to_seed)
			if missing_after_ingest:
				logger.warning(
					"Skipping unavailable month parquet files after ingest attempt: %s",
					", ".join(missing_after_ingest),
				)
				month_files = [
					month_file
					for month_file in month_files
					if month_file.exists()
				]

		if not month_files:
			logger.warning(
				"No parquet files available to seed in %s. Expected files like dataYYYYMM.parquet",
				resolved_data_dir,
			)
			return 0, 0, 0

		# Process each month file
		total_rows = 0
		total_inserted = 0
		try:
			for month_file in month_files:
				trip_month = _month_from_file_name(month_file)
				month_has_rows = _month_exists_in_db(session, trip_month)
				if month_has_rows and not backfill_missing_rows:
					logger.info(
						"Skipping %s because trip_month=%s already has rows in DB",
						month_file.name,
						trip_month,
					)
					_remove_parquet_file(month_file)
					continue

				rows, inserted = seed_month_file(session, month_file)
				total_rows += rows
				total_inserted += inserted
				_remove_parquet_file(month_file)
		finally:
			# Always release the advisory lock
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
		backfill_missing_rows=args.backfill_missing_rows,
		force_clear_lock=True,  # CLI invocation should clear lingering locks
    )


if __name__ == "__main__":
    main()
