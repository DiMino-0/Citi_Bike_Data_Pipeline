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

	# create (yearMonth, url) pairs for the target months
	candidate_urls = [(yearMonth, f"https://s3.amazonaws.com/tripdata/{yearMonth}-citibike-tripdata.zip") for yearMonth in target_months]

	processed = _load_processed(processed_file)
	dataframes: Dict[str, pd.DataFrame] = {}

	# determine which months we actually expect to download (respecting `force`)
	if force:
		expected_to_download = set(target_months)
	else:
		expected_to_download = set([m for m in target_months if m not in processed])

	# query bucket and process each available month
	response = None
	for yearMonth, url in candidate_urls:
		try:
			# skip candidate months we've already processed 
			if (yearMonth in processed) and not force:
				logger.debug("Skipping candidate %s (already processed)", yearMonth)
				continue
			head = requests.head(url, timeout=(10, 20), allow_redirects=True)
			if head.status_code != 200:
				logger.debug("Not found (%s): %s", head.status_code, url)
				continue

			logger.info("Downloading %s", url)
			response = _download_zip(url)
			logger.debug("Downloaded %s (%d bytes)", url, len(response) if response else 0)
			
			# set a fallback month from the URL in case filenames don't include YYYYMM
			downloaded_month = yearMonth

			# unzip and process immediately for this month
			zip_object = io.BytesIO(response)
			with zipfile.ZipFile(zip_object) as zf:
				csv_files = [name for name in zf.namelist() if name.lower().endswith('.csv')]
				if not csv_files:
					logger.error("No CSV file found in downloaded zip archive for %s", yearMonth)
					continue
				# process all CSV parts for this month (concatenate if multiple files)
				# prefer files whose name includes the target yearMonth
				selected_names = [name for name in csv_files if yearMonth in name]
				if not selected_names:
					selected_names = list(csv_files)

				# derive month from the first selected filename, fallback to downloaded_month
				first_name = selected_names[0]
				m = re.search(r"(\d{6})", first_name)
				if m:
					yearMonth_from_name = m.group(1)
				else:
					m2 = re.search(r"(\d{4})\D(\d{2})", first_name)
					if m2:
						yearMonth_from_name = f"{m2.group(1)}{m2.group(2)}"
					else:
						yearMonth_from_name = downloaded_month

				if (yearMonth_from_name in processed) and not force:
					logger.debug("Skipping %s (already processed)", yearMonth_from_name)
					continue

				parts = []
				for name in selected_names:
					with zf.open(name) as csv_file:
						try:
							part = pd.read_csv(
								TextIOWrapper(csv_file, encoding='utf-8', errors='strict'),
								dtype={'end_station_id': 'str'},
								low_memory=False,
							)
						except Exception as e:
							logger.exception("Error reading CSV %s: %s", name, e)
							traceback.print_exc()
							continue
						parts.append(part)

				if not parts:
					logger.error("No readable CSV parts found for %s in %s", yearMonth_from_name, url)
					continue

				# concatenate parts for the same month
				try:
					df = pd.concat(parts, ignore_index=True)
				except Exception:
					# fallback: if concat fails, keep first part
					df = parts[0]

				var_name = f"data{yearMonth_from_name}"
				dataframes[var_name] = df

				# persist processed month after successful read
				processed.add(yearMonth_from_name)
				try:
					_save_processed(processed_file, processed)
				except Exception:
					logger.exception("Failed to save processed months file %s", processed_file)

				# optional: persist dataframe to output_dir if provided
				if output_dir:
					os.makedirs(output_dir, exist_ok=True)
					out_path = os.path.join(output_dir, f"{var_name}.parquet")
					try:
						df.to_parquet(out_path)
						logger.info("Wrote dataframe to %s", out_path)
					except Exception:
						logger.exception("Failed to write dataframe %s to %s", var_name, out_path)

		except requests.RequestException as error:
			logger.warning("Request failed for %s: %s", url, error)
			continue

	# if we never downloaded any of the candidate months, raise an error only if
	# we expected to download something. If all target months were already
	# processed, that's not an error.
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