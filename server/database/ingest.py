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
import json
from typing import Optional, Dict


logger = logging.getLogger(__name__)

MAX_ARCHIVE_PARTS_PER_MONTH = 12


def _download_zip(url: str) -> bytes:
	with requests.get(url, stream=True, timeout=(10, 60)) as response:
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


def _load_processed(path: str) -> set:
	if os.path.exists(path):
		try:
			with open(path, "r", encoding="utf-8") as fh:
				return set(json.load(fh))
		except Exception:
			logger.exception("Failed to read processed months file %s", path)
			return set()
	return set()

def _save_processed(path: str, months: set) -> None:
	tmp = f"{path}.tmp"
	# ensure parent directory exists when saving
	dirpath = os.path.dirname(path)
	if dirpath:
		os.makedirs(dirpath, exist_ok=True)
	with open(tmp, "w", encoding="utf-8") as fh:
		json.dump(sorted(months), fh)
	os.replace(tmp, path)


def _month_archive_urls(year_month: str, max_parts: int = MAX_ARCHIVE_PARTS_PER_MONTH) -> list[str]:
	base = f"https://s3.amazonaws.com/tripdata/{year_month}-citibike-tripdata.zip"
	urls = [base]
	for index in range(1, max(1, max_parts) + 1):
		urls.append(f"https://s3.amazonaws.com/tripdata/{year_month}-citibike-tripdata_{index}.zip")
	return urls


def main(processed_file: str = "processed_months.json", output_dir: Optional[str] = None, force: bool = True, months: int = 2, log_file: Optional[str] = None) -> Dict[str, pd.DataFrame]:
	_configure_logging(log_file)

	# default processed_file should live next to this module (server/database)
	if not os.path.isabs(processed_file):
		script_dir = os.path.dirname(__file__)
		processed_file = os.path.join(script_dir, processed_file)

	# ensure parent directory for processed_file exists
	parent = os.path.dirname(processed_file)
	if parent:
		os.makedirs(parent, exist_ok=True)

	# compute target months
	today = date.today()
	previous_month = (today.replace(day=1) - timedelta(days=1))
	
	# build a list of the last `months`
	target_months = []
	cur = previous_month
	for _ in range(max(1, months)):
		target_months.append(cur.strftime("%Y%m"))
		cur = (cur.replace(day=1) - timedelta(days=1))

	processed = _load_processed(processed_file)
	dataframes: Dict[str, pd.DataFrame] = {}

	# determine which months we actually expect to download (respecting `force`)
	if force:
		expected_to_download = set(target_months)
	else:
		expected_to_download = set([m for m in target_months if m not in processed])

	# query bucket and process each available month
	for yearMonth in target_months:
		try:
			# skip candidate months we've already processed 
			if (yearMonth in processed) and not force:
				logger.debug("Skipping candidate %s (already processed)", yearMonth)
				continue

			month_parts = []
			found_any_archive = False
			for url in _month_archive_urls(yearMonth):
				head = requests.head(url, timeout=(10, 20), allow_redirects=True)
				if head.status_code != 200:
					continue

				found_any_archive = True
				logger.info("Downloading %s", url)
				response = _download_zip(url)
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
				logger.error("No readable CSV parts found for %s across split archives", yearMonth)
				continue

			try:
				df = pd.concat(month_parts, ignore_index=True)
			except Exception:
				df = month_parts[0]

			var_name = f"data{yearMonth}"
			dataframes[var_name] = df

			processed.add(yearMonth)
			try:
				_save_processed(processed_file, processed)
			except Exception:
				logger.exception("Failed to save processed months file %s", processed_file)

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
		if not expected_to_download:
			logger.info("No new Citi Bike datasets to download; all target months already processed: %s", target_months)
			return dataframes
		logger.error("No Citi Bike dataset found for months: %s", target_months)
		# raise RuntimeError(f"No Citi Bike dataset found for months: {target_months}")
	return dataframes

# if __name__ == '__main__':
# 	try:
# 		dfs = main("data", months=3)
# 	except Exception:
# 		logger.exception("ingest.main failed")
# 		dfs = {}