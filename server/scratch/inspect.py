from server.database.ingest import main
import logging
import os
from pathlib import Path
import pandas as pd
from datetime import date
from matplotlib import pyplot as plt
import numpy as np
import scipy.stats as stats
import statsmodels.api as sm


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

		# use local data folder 
		script_dir = Path(__file__).resolve().parent
		data_dir = script_dir / "data"

		if not data_dir.exists():
			logger.info("Data directory doesn't exist. Creating and running ingest for last %d months.", MONTHS)
			data_dir.mkdir(parents=True, exist_ok=True)
			dfs = main(output_dir=str(data_dir), months=MONTHS)
		else:
			existing = [f for f in os.listdir(data_dir) if f.endswith(".parquet")]
			missing = [f for f in expected_files if f not in existing]
			if missing:
				logger.info("Missing month files %s — running ingest.main for last %d months", missing, MONTHS)
				dfs = main(output_dir=str(data_dir), months=MONTHS)
			else:
				logger.info("All last %d months present: %s", MONTHS, expected_files)
				dfs = {f.split(".")[0]: pd.read_parquet(os.path.join(data_dir, f)) for f in existing}

		# check normality of trip durations for the most recent month
		latest_month = months_needed[0]
		latest_key = f"data{latest_month}"
		if latest_key in dfs:
			df = dfs[latest_key]
		else:
			logger.info("No dataframe found for latest month %s (looking for key %s). Available keys: %s", latest_month, latest_key, list(dfs.keys()))
			df = None

		if df is not None:
			# compute duration as a Timedelta 
			df["started_at"] = pd.to_datetime(df["started_at"], errors="coerce")
			df["ended_at"] = pd.to_datetime(df["ended_at"], errors="coerce")

			# keep timedelta dtype
			df["tripduration"] = df["ended_at"] - df["started_at"]

			# set invalid or non-positive durations to NaT
			df.loc[df["tripduration"].isna() | (df["tripduration"] <= pd.Timedelta(0)), "tripduration"] = pd.NaT
			
			# for plotting/analytics convert to minutes (more readable) and drop NA
			durations = df["tripduration"].dt.total_seconds().dropna()
			# convert to minutes
			durations_min = durations / 60.0
			# limit upper bound to 99th percentile to reduce extreme-tail domination
			upper = float(durations_min.quantile(0.99))
			# choose more bins for finer intervals
			bins = 80

			# plotting
			plt.figure(figsize=(14, 6))
			plt.subplot(1, 2, 1)
			plt.title(f"QQ Plot of Trip Durations (minutes) for {latest_month}")
			# use clipped data for QQ plot to avoid extreme tails
			qq_data = durations_min.clip(upper=upper)

			# compute probplot once and normalize types so Pylance understands the array/float ops
			(osm, osr), (slope, intercept, r) = stats.probplot(qq_data, dist="norm")
			osm = np.asarray(osm)             # ensure ArrayLike/ndarray
			# ensure slope/intercept are scalar floats even if returned as 0-d arrays, masked arrays, or numpy scalars
			try:
				slope = float(np.asarray(slope))
			except Exception:
				slope = float(np.array(slope).item())
			try:
				intercept = float(np.asarray(intercept))
			except Exception:
				intercept = float(np.array(intercept).item())
			ax = plt.gca()
			ax.scatter(osm, osr, s=12, alpha=0.6)
			ax.plot(osm, slope * osm + intercept, color="red", lw=2, label=f"fit (r={r:.3f})")
			ax.set_xlabel("Theoretical Quantiles")
			ax.set_ylabel("Sample Quantiles (minutes)")
			ax.grid(True, linestyle=':', linewidth=0.5)
			ax.legend(loc="lower right")
			# annotate sample size
			ax.text(0.02, 0.95, f"n={len(qq_data):,}", transform=ax.transAxes, va="top")

			plt.subplot(1, 2, 2)
			plt.title(f"Histogram of Trip Durations (minutes) for {latest_month}")
			# plot histogram clipped at 99th percentile to improve visualization
			plt.hist(durations_min.clip(upper=upper), bins=bins, edgecolor="k")
			ax = plt.gca()
			# set x-axis ticks with more intervals
			xticks = np.linspace(0, upper, 12)
			ax.set_xticks(xticks)
			ax.set_xlim(0, upper)
			ax.set_xlabel("Duration (minutes)")
			plt.tight_layout()
			# save the combined figure into the script-local data folder
			fig_path = data_dir / f"fig_{latest_month}.png"
			try:
				plt.savefig(str(fig_path))
				logger.info("Saved figure to %s", fig_path)
			except Exception:
				logger.exception("Failed to save figure %s", fig_path)
			plt.show()
			
	except Exception:
		logger.exception("ingest.main failed or reading parquet failed")
		dfs = {}