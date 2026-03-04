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


def _download_zip(url: str) -> bytes:
	with requests.get(url, stream=True, timeout=(10, 60), allow_redirects=True, headers=REQUEST_HEADERS) as response:
		response.raise_for_status()
		chunks = []
		for chunk in response.iter_content(chunk_size=1024 * 1024):
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
	match = re.fullmatch(r"\s*(\d{6})\s*(?:\.\.|:|-)\s*(\d{6})\s*", value)
	if not match:
		raise ValueError(f"Invalid range '{value}'. Expected format like YYYYMM..YYYYMM.")

	first = _parse_year_month(match.group(1))
	second = _parse_year_month(match.group(2))
	start = min(first, second)
	end = max(first, second)

	months: list[str] = []
	cursor = end
	while cursor >= start:
		months.append(cursor.strftime("%Y%m"))
		cursor = (cursor.replace(day=1) - timedelta(days=1))
	return months


def main(
	processed_file: str = "processed_months.json",
	output_dir: Optional[str] = None,
	force: bool = True,
	months: int = 1,
	log_file: Optional[str] = None,
	month: Optional[str] = None,
	month_range: Optional[str] = None,
) -> Dict[str, pd.DataFrame]:
	_configure_logging(log_file)

	# compute target months with precedence: range > month > recent default
	if month_range:
		target_months = _parse_month_range(month_range)
	elif month:
		target_months = [_parse_year_month(month).strftime("%Y%m")]
	else:
		target_months = []
		today = date.today()
		cur = (today.replace(day=1) - timedelta(days=1))
		for _ in range(max(1, months)):
			target_months.append(cur.strftime("%Y%m"))
			cur = (cur.replace(day=1) - timedelta(days=1))

	dataframes: Dict[str, pd.DataFrame] = {}

	# query bucket and process each available month
	for yearMonth in target_months:
		try:
			month_parts = []
			found_any_archive = False
			url = f"https://s3.amazonaws.com/tripdata/{yearMonth}-citibike-tripdata.zip"
			logger.info("Attempting download %s", url)
			try:
				response = _download_zip(url)
			except requests.HTTPError as http_error:
				status_code = http_error.response.status_code if http_error.response is not None else None
				if status_code == 404:
					logger.debug("Archive not found (404): %s", url)
					continue
				logger.warning("Archive request failed for %s (status=%s): %s", url, status_code, http_error)
				continue
			except requests.RequestException as request_error:
				logger.warning("Archive request failed for %s: %s", url, request_error)
				continue

			found_any_archive = True
			logger.debug("Downloaded %s (%d bytes)", url, len(response) if response else 0)

			zip_object = io.BytesIO(response)
			with zipfile.ZipFile(zip_object) as zf:
				csv_files = [name for name in zf.namelist() if name.lower().endswith('.csv')]
				if not csv_files:
					logger.error("No CSV file found in downloaded zip archive for %s", url)
					continue

				selected_names = [name for name in csv_files if yearMonth in name]
				if not selected_names:
					selected_names = list(csv_files)

				for name in selected_names:
					with zf.open(name) as csv_file:
						try:
							part = pd.read_csv(
								TextIOWrapper(csv_file, encoding='utf-8', errors='strict'),
								dtype={'end_station_id': 'str'},
								low_memory=False,
							)
						except Exception as e:
							logger.exception("Error reading CSV %s in %s: %s", name, url, e)
							traceback.print_exc()
							continue
						month_parts.append(part)

			if not found_any_archive:
				logger.debug("No dataset archive found for month %s", yearMonth)
				continue

			if not month_parts:
				logger.error("No readable CSV parts found for %s in monthly archive", yearMonth)
				continue

			try:
				df = pd.concat(month_parts, ignore_index=True)
			except Exception:
				df = month_parts[0]

			var_name = f"data{yearMonth}"
			dataframes[var_name] = df

			if output_dir:
				os.makedirs(output_dir, exist_ok=True)
				out_path = os.path.join(output_dir, f"{var_name}.parquet")
				try:
					df.to_parquet(out_path)
					logger.info("Wrote dataframe to %s", out_path)
				except Exception:
					logger.exception("Failed to write dataframe %s to %s", var_name, out_path)

		except requests.RequestException as error:
			logger.warning("Request failed for month %s: %s", yearMonth, error)
			continue

	if not dataframes:
		logger.error("No Citi Bike dataset found for months: %s", target_months)
		# raise RuntimeError(f"No Citi Bike dataset found for months: {target_months}")
	return dataframes

# if __name__ == '__main__':
# 	try:
# 		dfs = main("data", months=3)
# 	except Exception:
# 		logger.exception("ingest.main failed")
# 		dfs = {}