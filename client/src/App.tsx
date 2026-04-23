import { useEffect, useMemo, useState } from "react";
import "./App.css";

type MonthCount = {
  tripMonth: string;
  tripCount: number;
};

type FeeSummary = {
  tripMonth: string;
  memberCasual: "member" | "casual";
  lostBikeFeeTrips: number;
  totalTrips: number;
};

type BucketSummary = {
  tripMonth: string;
  memberCasual: "member" | "casual";
  bucket: string;
  trips: number;
  lostBikeFeeFlag: boolean;
};

const API_BASE =
  typeof import.meta.env.VITE_API_BASE_URL === "string"
    ? import.meta.env.VITE_API_BASE_URL
    : "";

function parseMonthCounts(value: unknown): MonthCount[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((row) => {
      if (!row || typeof row !== "object") {
        return null;
      }

      const item = row as { tripMonth?: unknown; tripCount?: unknown };
      if (
        typeof item.tripMonth !== "string" ||
        typeof item.tripCount !== "number"
      ) {
        return null;
      }

      return { tripMonth: item.tripMonth, tripCount: item.tripCount };
    })
    .filter((item): item is MonthCount => item !== null);
}

function parseFeeSummary(value: unknown): FeeSummary[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((row) => {
      if (!row || typeof row !== "object") {
        return null;
      }

      const item = row as {
        tripMonth?: unknown;
        memberCasual?: unknown;
        lostBikeFeeTrips?: unknown;
        totalTrips?: unknown;
      };

      if (
        typeof item.tripMonth !== "string" ||
        (item.memberCasual !== "member" && item.memberCasual !== "casual") ||
        typeof item.lostBikeFeeTrips !== "number" ||
        typeof item.totalTrips !== "number"
      ) {
        return null;
      }

      return {
        tripMonth: item.tripMonth,
        memberCasual: item.memberCasual,
        lostBikeFeeTrips: item.lostBikeFeeTrips,
        totalTrips: item.totalTrips,
      };
    })
    .filter((item): item is FeeSummary => item !== null);
}

function parseBucketSummary(value: unknown): BucketSummary[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((row) => {
      if (!row || typeof row !== "object") {
        return null;
      }

      const item = row as {
        tripMonth?: unknown;
        memberCasual?: unknown;
        bucket?: unknown;
        trips?: unknown;
        lostBikeFeeFlag?: unknown;
      };

      if (
        typeof item.tripMonth !== "string" ||
        (item.memberCasual !== "member" && item.memberCasual !== "casual") ||
        typeof item.bucket !== "string" ||
        typeof item.trips !== "number" ||
        typeof item.lostBikeFeeFlag !== "boolean"
      ) {
        return null;
      }

      return {
        tripMonth: item.tripMonth,
        memberCasual: item.memberCasual,
        bucket: item.bucket,
        trips: item.trips,
        lostBikeFeeFlag: item.lostBikeFeeFlag,
      };
    })
    .filter((item): item is BucketSummary => item !== null);
}

function App() {
  const [monthlyTripCounts, setMonthlyTripCounts] = useState<MonthCount[]>([]);
  const [feeRows, setFeeRows] = useState<FeeSummary[]>([]);
  const [bucketRows, setBucketRows] = useState<BucketSummary[]>([]);
  const [selectedMonth, setSelectedMonth] = useState<string>("");
  const [selectedRider, setSelectedRider] = useState<
    "all" | "member" | "casual"
  >("all");
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>("");

  const months = useMemo(
    () => monthlyTripCounts.map((item) => item.tripMonth),
    [monthlyTripCounts],
  );

  useEffect(() => {
    const loadMonths = async () => {
      try {
        setLoading(true);
        setError("");
        const response = await fetch(
          `${API_BASE}/api/analytics/monthly-trip-counts`,
        );
        if (!response.ok) {
          throw new Error("Unable to load monthly trip counts.");
        }

        const payload: unknown = await response.json();
        const data = parseMonthCounts(payload);
        setMonthlyTripCounts(data);

        if (data.length > 0) {
          setSelectedMonth(
            (current) => current || data[data.length - 1].tripMonth,
          );
        }
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Unknown error loading month data.",
        );
      } finally {
        setLoading(false);
      }
    };

    void loadMonths();
  }, []);

  useEffect(() => {
    if (!selectedMonth) {
      return;
    }

    const loadFilteredData = async () => {
      try {
        setLoading(true);
        setError("");
        const params = new URLSearchParams({
          month: selectedMonth,
          rider: selectedRider,
        });

        const [feeResponse, bucketResponse] = await Promise.all([
          fetch(
            `${API_BASE}/api/analytics/lost-bike-fee-summary?${params.toString()}`,
          ),
          fetch(
            `${API_BASE}/api/analytics/duration-buckets?${params.toString()}&bucket_minutes=5`,
          ),
        ]);

        if (!feeResponse.ok || !bucketResponse.ok) {
          throw new Error("Unable to load filtered analytics data.");
        }

        const feePayload: unknown = await feeResponse.json();
        const bucketPayload: unknown = await bucketResponse.json();
        const feeData = parseFeeSummary(feePayload);
        const bucketData = parseBucketSummary(bucketPayload);

        setFeeRows(feeData);
        setBucketRows(bucketData);
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Unknown error loading analytics data.",
        );
        setFeeRows([]);
        setBucketRows([]);
      } finally {
        setLoading(false);
      }
    };

    void loadFilteredData();
  }, [selectedMonth, selectedRider]);

  const currentMonthTotals = useMemo(() => {
    const feeTrips = feeRows.reduce(
      (sum, row) => sum + row.lostBikeFeeTrips,
      0,
    );
    const totalTrips = feeRows.reduce((sum, row) => sum + row.totalTrips, 0);

    return {
      feeTrips,
      totalTrips,
      feePct: totalTrips === 0 ? 0 : (feeTrips / totalTrips) * 100,
    };
  }, [feeRows]);

  return (
    <main className="dashboard">
      <header className="dashboard-header">
        <h1>Citi Bike SQL Results</h1>
        <p>Minimal dashboard backed by FastAPI analytics endpoints.</p>
      </header>

      <section className="panel" aria-label="computed elements">
        <h2>Computed Elements</h2>
        <ul className="notes-list">
          <li>
            Ride duration: calculated as the difference between{" "}
            <code>ended_at</code> and <code>started_at</code>.
          </li>
          <li>
            Optimal route + duration: computed from start/end longitude and
            latitude, with routing logic offloaded to the OSRM API.
          </li>
          <li>
            Station usage: total trip count by station name and station ID,
            including arrivals and departures tracked per station.
          </li>
          <li>
            Actual vs optimal trip duration: compares rider behavior against
            estimated optimal duration to evaluate whether members keep bikes
            longer than casual riders and whether electric or classic bikes are
            favored for longer rides.
          </li>
        </ul>
      </section>

      <section className="panel" aria-label="visualizations made">
        <h2>Visualizations Made</h2>
        <ul className="notes-list">
          <li>
            Histograms: number of station uses by bike type (classic/electric)
            and rider type (member/casual).
          </li>
          <li>
            Scatter plot: trip duration vs time of day, highlighting dense usage
            windows for member/casual riders.
          </li>
          <li>
            Scatter plot: start longitude vs start latitude, showing
            density/spread of trip origins colored by rider type and bike type.
          </li>
          <li>
            Scatter plot: start station vs end station (with ID jitter),
            visualizing station-to-station flow.
          </li>
          <li>
            Scatter plot: start lng/lat vs end lng/lat, showing approximate
            rider trip distances.
          </li>
        </ul>
      </section>

      {error ? <p className="status-error">{error}</p> : null}
      {loading ? <p className="status-loading">Loading data...</p> : null}

      <section className="filters" aria-label="filters">
        <label>
          Month
          <select
            value={selectedMonth}
            onChange={(event) => setSelectedMonth(event.target.value)}
            disabled={months.length === 0}
          >
            {months.map((month) => (
              <option key={month} value={month}>
                {month}
              </option>
            ))}
          </select>
        </label>

        <label>
          Rider Type
          <select
            value={selectedRider}
            onChange={(event) =>
              setSelectedRider(
                event.target.value as "all" | "member" | "casual",
              )
            }
            disabled={!selectedMonth}
          >
            <option value="all">all</option>
            <option value="member">member</option>
            <option value="casual">casual</option>
          </select>
        </label>
      </section>

      <section className="kpis" aria-label="key metrics">
        <article>
          <h2>Total Trips</h2>
          <strong>{currentMonthTotals.totalTrips.toLocaleString()}</strong>
        </article>
        <article>
          <h2>Lost Bike Fee Trips</h2>
          <strong>{currentMonthTotals.feeTrips.toLocaleString()}</strong>
        </article>
        <article>
          <h2>Lost Bike Fee %</h2>
          <strong>{currentMonthTotals.feePct.toFixed(2)}%</strong>
        </article>
      </section>

      <section className="panel" aria-label="monthly trip counts">
        <h2>Monthly Trip Counts</h2>
        <table>
          <thead>
            <tr>
              <th>Trip Month</th>
              <th>Trip Count</th>
            </tr>
          </thead>
          <tbody>
            {monthlyTripCounts.map((row) => (
              <tr key={row.tripMonth}>
                <td>{row.tripMonth}</td>
                <td>{row.tripCount.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel" aria-label="lost bike fee summary">
        <h2>Lost Bike Fee by Rider Type</h2>
        <table>
          <thead>
            <tr>
              <th>Month</th>
              <th>Rider</th>
              <th>Fee Trips</th>
              <th>Total Trips</th>
              <th>Fee %</th>
            </tr>
          </thead>
          <tbody>
            {feeRows.map((row) => {
              const pct =
                row.totalTrips === 0
                  ? 0
                  : (row.lostBikeFeeTrips / row.totalTrips) * 100;

              return (
                <tr key={`${row.tripMonth}-${row.memberCasual}`}>
                  <td>{row.tripMonth}</td>
                  <td>{row.memberCasual}</td>
                  <td>{row.lostBikeFeeTrips.toLocaleString()}</td>
                  <td>{row.totalTrips.toLocaleString()}</td>
                  <td>{pct.toFixed(2)}%</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <section className="panel" aria-label="duration bucket summary">
        <h2>5-Minute Duration Buckets</h2>
        <table>
          <thead>
            <tr>
              <th>Month</th>
              <th>Rider</th>
              <th>Bucket</th>
              <th>Trips</th>
              <th>Fee Flag</th>
            </tr>
          </thead>
          <tbody>
            {bucketRows.map((row) => (
              <tr key={`${row.tripMonth}-${row.memberCasual}-${row.bucket}`}>
                <td>{row.tripMonth}</td>
                <td>{row.memberCasual}</td>
                <td>{row.bucket}</td>
                <td>{row.trips.toLocaleString()}</td>
                <td>{row.lostBikeFeeFlag ? "yes" : "no"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  );
}

export default App;
