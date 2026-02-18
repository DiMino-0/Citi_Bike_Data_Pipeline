from datetime import date, timedelta
import io
import logging
import requests
import zipfile


logger = logging.getLogger(__name__)


def _download_zip(url: str) -> bytes:
	with requests.get(url, stream=True, timeout=(10, 60)) as response:
		response.raise_for_status()
		chunks = []
		for chunk in response.iter_content(chunk_size=1024 * 1024):
			if chunk:
				chunks.append(chunk)
		return b"".join(chunks)

# get zip from bucket
# need format - YYYYMM
# setting up so i can gather the historical data later, last months gets published on or near the first hence need to persist
today = date.today()
previous_month = (today.replace(day=1) - timedelta(days=1))
month_before_previous = (previous_month.replace(day=1) - timedelta(days=1))
target_months = [previous_month.strftime("%Y%m"), month_before_previous.strftime("%Y%m")]

# target url ex - https://s3.amazonaws.com/tripdata/202601-citibike-tripdata.zip
# JC is diff format, not ingesting here
candidate_urls = []
for yearMonth in target_months:
	candidate_urls.extend(
		[
			f"https://s3.amazonaws.com/tripdata/{yearMonth}-citibike-tripdata.zip"
		]
	)

response = None
for url in candidate_urls:
	try:
		head = requests.head(url, timeout=(10, 20), allow_redirects=True)
		if head.status_code != 200:
			logger.info("Not found (%s): %s", head.status_code, url)
			continue

		logger.info("Starting download: %s", url)
		response = _download_zip(url)
		logger.info("Downloaded: %s", url)
		break
	except requests.RequestException as error:
		logger.warning("Request failed for %s: %s", url, error)

if response is None:
	raise RuntimeError(f"No Citi Bike dataset found for months: {target_months}")

zip_object = io.BytesIO(response)

with zipfile.ZipFile(zip_object) as zf:
	csv_files = [name for name in zf.namelist() if name.endswith(".csv")]
	if not csv_files:
		raise RuntimeError("No CSV file found in downloaded zip archive")

	csv_filename = csv_files[0]
	with zf.open(csv_filename) as csv_file:
		csv_data = csv_file.read()