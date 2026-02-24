from server.database.ingest import main
import logging
import os
import pandas as pd
from datetime import date

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_last_months(n, ref_date=None):
	if ref_date is None:
		ref_date = date.today()
	months = []
	y = ref_date.year
	m = ref_date.month
	# skip current (in-progress) month and start from the previous month
	m -= 1
	if m == 0:
		m = 12
		y -= 1
	for _ in range(n):
		months.append(f"{y}{m:02d}")
		m -= 1
		if m == 0:
			m = 12
			y -= 1
	return months


if __name__ == "__main__":
	try:
		MONTHS = 3
		months_needed = get_last_months(MONTHS)
		expected_files = [f"data{m}.parquet" for m in months_needed]

		if not os.path.exists("data"):
			logger.info("Data directory doesn't exist. Creating and running ingest for last %d months.", MONTHS)
			os.makedirs("data", exist_ok=True)
			dfs = main(output_dir="data", months=MONTHS)
		else:
			existing = [f for f in os.listdir("data") if f.endswith(".parquet")]
			missing = [f for f in expected_files if f not in existing]
			if missing:
				logger.info("Missing month files %s — running ingest.main for last %d months", missing, MONTHS)
				dfs = main(output_dir="data", months=MONTHS)
			else:
				logger.info("All last %d months present: %s", MONTHS, expected_files)
				dfs = {f.split(".")[0]: pd.read_parquet(os.path.join("data", f)) for f in existing}
	except Exception:
		logger.exception("ingest.main failed or reading parquet failed")
		dfs = {}