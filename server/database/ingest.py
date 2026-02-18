# Plan
# - Python **requests** to handle the download
# possibly 2 files, possibly not on first of month
# - **zipfile** module to handle unzipping
# - **io** for file handling
# minimal parsing required
# - **asyncpg** for postgres
# - Use cron job to schedule it on live server
# needs to persist daily until new csv(s) obtained
from datetime import date, timedelta
import requests

# get zip from bucket
# want - 202602
today = date.today()
previous_month = (today.replace(day=1) - timedelta(days=1))
target_months = [today.strftime("%Y%m"), previous_month.strftime("%Y%m")]

# want - https://s3.amazonaws.com/tripdata/202601-citibike-tripdata.zip
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
	r = requests.get(url, timeout=30)
	if r.status_code == 200:
		response = r
		print(f"Downloaded: {url}")
		break
	print(f"Not found ({r.status_code}): {url}")

if response is None:
	raise RuntimeError(f"No Citi Bike dataset found for months: {target_months}")