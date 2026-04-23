from datetime import date, timedelta
import io
import logging
import requests
import zipfile
import re
import pandas as pd
from io import TextIOWrapper
import traceback
import sys
import os
from typing import Optional, Dict


logger = logging.getLogger(__name__)

REQUEST_HEADERS = {
	"User-Agent": "CitiBikeDataPipeline/1.0 (+https://github.com)",
}

_YEAR_ARCHIVE_CACHE: Dict[str, Optional[bytes]] = {}


def _download_zip(url: str) -> bytes:
	"""Download a zip file from URL and return as bytes."""
	response = requests.get(
		url, 
		stream=True, 
		timeout=(10, 60), 
		allow_redirects=True, 
		headers=REQUEST_HEADERS
	)
	response.raise_for_status()
	
	chunks = []
	chunk_size = 1024 * 1024
	
	for chunk in response.iter_content(chunk_size=chunk_size):
		if chunk:
			chunks.append(chunk)
	
	return b"".join(chunks)
	
def _configure_logging(log_file: Optional[str] = None, level: int = logging.INFO) -> None:
	handlers = [logging.StreamHandler(sys.stdout)]
	if log_file:
		os.makedirs(os.path.dirname(log_file), exist_ok=True)
		fh = logging.FileHandler(log_file)
		handlers.append(fh)
	logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)


def _parse_year_month(value: str) -> date:
	if not re.fullmatch(r"\d{6}", value):
		raise ValueError(f"Invalid month '{value}'. Expected YYYYMM format.")
	year = int(value[:4])
	month = int(value[4:6])
	if month < 1 or month > 12:
		raise ValueError(f"Invalid month '{value}'. Expected month between 01 and 12.")
	return date(year, month, 1)


def _parse_month_range(value: str) -> list[str]:
	"""Parse a month range string and return list of months in reverse order."""
	pattern = r"\s*(\d{4}|\d{6})\s*(?:\.\.|:|-)\s*(\d{4}|\d{6})\s*"
	match = re.fullmatch(pattern, value)
	
	if not match:
		raise ValueError(f"Invalid range '{value}'. Expected format like YYYY..YYYYMM.")

	first_low, first_high = _parse_range_bound(match.group(1))
	second_low, second_high = _parse_range_bound(match.group(2))

	start_date = min(first_low, second_low)
	end_date = max(first_high, second_high)

	months: list[str] = []
	current_date = end_date
	
	while current_date >= start_date:
		month_str = current_date.strftime("%Y%m")
		months.append(month_str)
		
		# Move to previous month
		first_day_of_current = current_date.replace(day=1)
		previous_day = first_day_of_current - timedelta(days=1)
		current_date = previous_day
	
	return months


def _parse_range_bound(value: str) -> tuple[date, date]:
	"""Parse YYYY or YYYYMM into a (low, high) month bound."""
	if re.fullmatch(r"\d{6}", value):
		parsed = _parse_year_month(value)
		return parsed, parsed

	if re.fullmatch(r"\d{4}", value):
		year = int(value)
		return date(year, 1, 1), date(year, 12, 1)

	raise ValueError(f"Invalid month bound '{value}'. Expected YYYY or YYYYMM format.")


def _month_zip_basename(year_month: str) -> str:
	"""Return expected monthly zip base name for a given YYYYMM."""
	return f"{year_month}-citibike-tripdata.zip"


def _month_csv_prefix(year_month: str) -> str:
	"""Return expected CSV prefix inside monthly archive for a given YYYYMM."""
	return f"{year_month}-citibike-tripdata"


def _is_target_month_zip(path_name: str, year_month: str) -> bool:
	"""Match monthly zip in yearly archive by exact basename.

	Yearly archives use a folder like YYYY-citibike-tripdata/ with nested
	monthly zips named YYYYMM-citibike-tripdata.zip.
	"""
	base_name = os.path.basename(path_name)
	return base_name == _month_zip_basename(year_month)


def _is_target_month_csv(path_name: str, year_month: str) -> bool:
	"""Match CSV chunk files for a month inside a monthly archive.

	Monthly archives contain one or more CSV parts such as:
	YYYYMM-citibike-tripdata.csv
	YYYYMM-citibike-tripdata_1.csv
	YYYYMM-citibike-tripdata_2.csv
	"""
	base_name = os.path.basename(path_name)
	lower_name = base_name.lower()
	prefix = _month_csv_prefix(year_month).lower()
	if not lower_name.endswith(".csv"):
		return False
	return lower_name.startswith(prefix)


def _read_month_parts_from_zip(
	zf: zipfile.ZipFile,
	source_label: str,
	year_month: str,
	month_parts: list[pd.DataFrame],
) -> None:
	"""Read relevant CSV files from a zip archive into month_parts."""
	csv_files = [name for name in zf.namelist() if name.lower().endswith('.csv')]
	if not csv_files:
		logger.error("No CSV file found in archive: %s", source_label)
		return

	selected_files = [name for name in csv_files if _is_target_month_csv(name, year_month)]
	if not selected_files:
		logger.warning(
			"No CSV files matched month pattern %s in %s; falling back to all %d CSV files",
			year_month,
			source_label,
			len(csv_files),
		)
		selected_files = list(csv_files)

	selected_files.sort()
	logger.info(
		"Reading %d CSV part(s) for %s from %s",
		len(selected_files),
		year_month,
		source_label,
	)

	for csv_name in selected_files:
		_read_csv_file(zf, csv_name, source_label, month_parts)


def _read_month_parts_from_year_archive(year_month: str, month_parts: list[pd.DataFrame]) -> bool:
	"""Read a month's data from yearly archive format: YYYY zip containing nested monthly zips."""
	year = year_month[:4]
	year_archive_bytes = _get_year_archive_bytes(year)
	if year_archive_bytes is None:
		return False

	year_url = f"https://s3.amazonaws.com/tripdata/{year}-citibike-tripdata.zip"

	try:
		with zipfile.ZipFile(io.BytesIO(year_archive_bytes)) as yearly_zip:
			nested_zip_files = [name for name in yearly_zip.namelist() if name.lower().endswith('.zip')]

			if not nested_zip_files:
				logger.debug("Yearly archive has no nested zips; trying direct CSV files")
				_read_month_parts_from_zip(yearly_zip, year_url, year_month, month_parts)
				return bool(month_parts)

			selected_nested = [name for name in nested_zip_files if _is_target_month_zip(name, year_month)]
			if not selected_nested:
				logger.debug("No nested month zip matched %s in yearly archive %s", year_month, year_url)
				return False

			selected_nested.sort()

			for nested_name in selected_nested:
				nested_label = f"{year_url}!{nested_name}"
				try:
					with yearly_zip.open(nested_name) as nested_zip_file:
						nested_zip_bytes = nested_zip_file.read()
					with zipfile.ZipFile(io.BytesIO(nested_zip_bytes)) as monthly_zip:
						_read_month_parts_from_zip(monthly_zip, nested_label, year_month, month_parts)
				except zipfile.BadZipFile:
					logger.exception("Nested month archive is not a valid zip: %s", nested_label)
					continue

	except zipfile.BadZipFile:
		logger.exception("Yearly archive is not a valid zip: %s", year_url)
		return False

	return bool(month_parts)


def _get_year_archive_bytes(year: str) -> Optional[bytes]:
	"""Get yearly archive bytes from cache or download once per year."""
	if year in _YEAR_ARCHIVE_CACHE:
		return _YEAR_ARCHIVE_CACHE[year]

	year_url = f"https://s3.amazonaws.com/tripdata/{year}-citibike-tripdata.zip"
	logger.info("Attempting yearly archive %s", year_url)

	try:
		year_archive_bytes = _download_zip(year_url)
		logger.debug("Downloaded yearly archive %s (%d bytes)", year_url, len(year_archive_bytes))
		_YEAR_ARCHIVE_CACHE[year] = year_archive_bytes
		return year_archive_bytes
	except requests.HTTPError as http_error:
		status_code = http_error.response.status_code if http_error.response is not None else None
		if status_code == 404:
			logger.debug("Yearly archive not found (404): %s", year_url)
		else:
			logger.warning("Yearly archive request failed for %s (status=%s): %s", year_url, status_code, http_error)
	except requests.RequestException as request_error:
		logger.warning("Yearly archive request failed for %s: %s", year_url, request_error)

	_YEAR_ARCHIVE_CACHE[year] = None
	return None


def main(
	output_dir: Optional[str] = None,
	months: int = 1,
	log_file: Optional[str] = None,
	month: Optional[str] = None,
	month_range: Optional[str] = None,
) -> Dict[str, pd.DataFrame]:
	_configure_logging(log_file)

	# Determine target months based on priority: range > specific month > recent default
	if month_range:
		logger.debug("Using month range: %s", month_range)
		target_months = _parse_month_range(month_range)
	elif month:
		logger.debug("Using specific month: %s", month)
		parsed_date = _parse_year_month(month)
		target_months = [parsed_date.strftime("%Y%m")]
	else:
		logger.debug("Using recent months: %d", months)
		target_months = []
		today = date.today()
		current_month_end = today.replace(day=1) - timedelta(days=1)
		
		for i in range(max(1, months)):
			month_str = current_month_end.strftime("%Y%m")
			target_months.append(month_str)
			
			# Move to previous month
			current_month_start = current_month_end.replace(day=1)
			current_month_end = current_month_start - timedelta(days=1)

	dataframes: Dict[str, pd.DataFrame] = {}

	# Process each target month
	for yearMonth in target_months:
		try:
			_process_month(yearMonth, output_dir, dataframes)
		except requests.RequestException as error:
			logger.warning("Request failed for month %s: %s", yearMonth, error)
			continue

	if not dataframes:
		logger.error("No Citi Bike dataset found for months: %s", target_months)
	
	return dataframes


def _process_month(yearMonth: str, output_dir: Optional[str], dataframes: Dict[str, pd.DataFrame]) -> None:
	"""Process a single month of Citi Bike data."""
	month_parts: list[pd.DataFrame] = []

	# Strategy: try yearly archive first; if not available or no match, fallback to monthly archive.
	found_in_yearly_archive = _read_month_parts_from_year_archive(yearMonth, month_parts)
	if found_in_yearly_archive:
		var_name = f"data{yearMonth}"
		try:
			combined_df = pd.concat(month_parts, ignore_index=True)
		except Exception:
			combined_df = month_parts[0]

		dataframes[var_name] = combined_df
		if output_dir:
			_save_to_parquet(output_dir, var_name, combined_df)
		return

	url = f"https://s3.amazonaws.com/tripdata/{yearMonth}-citibike-tripdata.zip"
	logger.info("Attempting download %s", url)
	
	# Download the archive
	try:
		response = _download_zip(url)
	except requests.HTTPError as http_error:
		status_code = http_error.response.status_code if http_error.response is not None else None
		
		if status_code == 404:
			logger.debug("Archive not found (404): %s", url)
			return
		
		logger.warning("Archive request failed for %s (status=%s): %s", url, status_code, http_error)
		return
	except requests.RequestException as request_error:
		logger.warning("Archive request failed for %s: %s", url, request_error)
		return

	logger.debug("Downloaded %s (%d bytes)", url, len(response) if response else 0)

	# Extract and process CSV files from zip
	zip_object = io.BytesIO(response)
	
	with zipfile.ZipFile(zip_object) as zf:
		_read_month_parts_from_zip(zf, url, yearMonth, month_parts)

	if not month_parts:
		logger.error("No readable CSV parts found for %s in monthly archive", yearMonth)
		return

	# Combine all parts for this month
	try:
		combined_df = pd.concat(month_parts, ignore_index=True)
	except Exception:
		combined_df = month_parts[0]

	# Store dataframe with month-based variable name
	var_name = f"data{yearMonth}"
	dataframes[var_name] = combined_df

	# Optionally save to parquet
	if output_dir:
		_save_to_parquet(output_dir, var_name, combined_df)


def _read_csv_file(zf: zipfile.ZipFile, csv_name: str, url: str, month_parts: list) -> None:
	"""Read a single CSV file from the zip archive."""
	with zf.open(csv_name) as csv_file:
		try:
			df = pd.read_csv(
				TextIOWrapper(csv_file, encoding='utf-8', errors='replace'),
				dtype={'end_station_id': 'str'},
				low_memory=False,
			)
			month_parts.append(df)
		except Exception as e:
			logger.exception("Error reading CSV %s in %s: %s", csv_name, url, e)
			traceback.print_exc()


def _save_to_parquet(output_dir: str, var_name: str, df: pd.DataFrame) -> None:
	"""Save dataframe to parquet file."""
	os.makedirs(output_dir, exist_ok=True)
	out_path = os.path.join(output_dir, f"{var_name}.parquet")
	
	try:
		df.to_parquet(out_path)
		logger.info("Wrote dataframe to %s", out_path)
	except Exception:
		logger.exception("Failed to write dataframe %s to %s", var_name, out_path)

# if __name__ == '__main__':
# 	try:
# 		dfs = main("data", months=3)
# 	except Exception:
# 		logger.exception("ingest.main failed")
# 		dfs = {}