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

type StationUsage = {
  stationName: string;
  stationId: string;
  arrivals: number;
  departures: number;
  totalTrips: number;
};

type HistogramBucket = {
  rideableType?: string;
  memberCasual?: "member" | "casual";
  tripCount: number;
};

type DurationByHour = {
  hour: number;
  memberCasual: "member" | "casual";
  tripCount: number;
  averageDurationMinutes: number;
};

type FlowPoint = {
  startStationName?: string;
  startStationId?: string;
  endStationName?: string;
  endStationId?: string;
  startLat?: number | null;
  startLng?: number | null;
  endLat?: number | null;
  endLng?: number | null;
  rideableType?: string;
  memberCasual?: "member" | "casual";
  tripCount: number;
};

type DashboardSummary = {
  summary: {
    tripCount: number;
    averageActualMinutes: number;
    averageEstimatedMinutes: number;
    averageDeltaMinutes: number;
  };
  stationUsage: StationUsage[];
  histogramByBikeType: HistogramBucket[];
  histogramByRiderType: HistogramBucket[];
  durationByHour: DurationByHour[];
  originSpread: FlowPoint[];
  stationFlow: FlowPoint[];
  coordinatePairs: FlowPoint[];
  actualVsEstimated: Array<{
    memberCasual: "member" | "casual";
    rideableType: string;
    tripCount: number;
    averageActualMinutes: number;
    averageEstimatedMinutes: number;
    deltaMinutes: number;
  }>;
  estimatedSpeedMph: number;
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

function parseDashboardSummary(value: unknown): DashboardSummary | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const item = value as {
    summary?: unknown;
    stationUsage?: unknown;
    histogramByBikeType?: unknown;
    histogramByRiderType?: unknown;
    durationByHour?: unknown;
    originSpread?: unknown;
    stationFlow?: unknown;
    coordinatePairs?: unknown;
    actualVsEstimated?: unknown;
    estimatedSpeedMph?: unknown;
  };

  if (
    !item.summary ||
    !Array.isArray(item.stationUsage) ||
    !Array.isArray(item.histogramByBikeType) ||
    !Array.isArray(item.histogramByRiderType) ||
    !Array.isArray(item.durationByHour) ||
    !Array.isArray(item.originSpread) ||
    !Array.isArray(item.stationFlow) ||
    !Array.isArray(item.coordinatePairs) ||
    !Array.isArray(item.actualVsEstimated) ||
    typeof item.estimatedSpeedMph !== "number"
  ) {
    return null;
  }

  const summary = item.summary as {
    tripCount?: unknown;
    averageActualMinutes?: unknown;
    averageEstimatedMinutes?: unknown;
    averageDeltaMinutes?: unknown;
  };

  if (
    typeof summary.tripCount !== "number" ||
    typeof summary.averageActualMinutes !== "number" ||
    typeof summary.averageEstimatedMinutes !== "number" ||
    typeof summary.averageDeltaMinutes !== "number"
  ) {
    return null;
  }

  return {
    summary: {
      tripCount: summary.tripCount,
      averageActualMinutes: summary.averageActualMinutes,
      averageEstimatedMinutes: summary.averageEstimatedMinutes,
      averageDeltaMinutes: summary.averageDeltaMinutes,
    },
    stationUsage: item.stationUsage
      .map((row) => {
        if (!row || typeof row !== "object") {
          return null;
        }

        const station = row as StationUsage;
        if (
          typeof station.stationName !== "string" ||
          typeof station.stationId !== "string" ||
          typeof station.arrivals !== "number" ||
          typeof station.departures !== "number" ||
          typeof station.totalTrips !== "number"
        ) {
          return null;
        }

        return station;
      })
      .filter((row): row is StationUsage => row !== null),
    histogramByBikeType: item.histogramByBikeType
      .map((row) => {
        if (!row || typeof row !== "object") {
          return null;
        }

        const bucket = row as HistogramBucket;
        if (
          typeof bucket.rideableType !== "string" ||
          typeof bucket.tripCount !== "number"
        ) {
          return null;
        }

        return bucket;
      })
      .filter((row): row is HistogramBucket => row !== null),
    histogramByRiderType: item.histogramByRiderType
      .map((row) => {
        if (!row || typeof row !== "object") {
          return null;
        }

        const bucket = row as HistogramBucket;
        if (
          bucket.memberCasual !== "member" &&
          bucket.memberCasual !== "casual"
        ) {
          return null;
        }

        if (typeof bucket.tripCount !== "number") {
          return null;
        }

        return bucket;
      })
      .filter((row): row is HistogramBucket => row !== null),
    durationByHour: item.durationByHour
      .map((row) => {
        if (!row || typeof row !== "object") {
          return null;
        }

        const bucket = row as DurationByHour;
        if (
          typeof bucket.hour !== "number" ||
          (bucket.memberCasual !== "member" &&
            bucket.memberCasual !== "casual") ||
          typeof bucket.tripCount !== "number" ||
          typeof bucket.averageDurationMinutes !== "number"
        ) {
          return null;
        }

        return bucket;
      })
      .filter((row): row is DurationByHour => row !== null),
    originSpread: item.originSpread
      .map((row) =>
        row && typeof row === "object" ? (row as FlowPoint) : null,
      )
      .filter((row): row is FlowPoint => row !== null),
    stationFlow: item.stationFlow
      .map((row) =>
        row && typeof row === "object" ? (row as FlowPoint) : null,
      )
      .filter((row): row is FlowPoint => row !== null),
    coordinatePairs: item.coordinatePairs
      .map((row) =>
        row && typeof row === "object" ? (row as FlowPoint) : null,
      )
      .filter((row): row is FlowPoint => row !== null),
    actualVsEstimated: item.actualVsEstimated
      .map((row) => {
        if (!row || typeof row !== "object") {
          return null;
        }

        const bucket = row as DashboardSummary["actualVsEstimated"][number];
        if (
          (bucket.memberCasual !== "member" &&
            bucket.memberCasual !== "casual") ||
          typeof bucket.rideableType !== "string" ||
          typeof bucket.tripCount !== "number" ||
          typeof bucket.averageActualMinutes !== "number" ||
          typeof bucket.averageEstimatedMinutes !== "number" ||
          typeof bucket.deltaMinutes !== "number"
        ) {
          return null;
        }

        return bucket;
      })
      .filter(
        (row): row is DashboardSummary["actualVsEstimated"][number] =>
          row !== null,
      ),
    estimatedSpeedMph: item.estimatedSpeedMph,
  };
}

function App() {
  const [monthlyTripCounts, setMonthlyTripCounts] = useState<MonthCount[]>([]);
  const [feeRows, setFeeRows] = useState<FeeSummary[]>([]);
  const [bucketRows, setBucketRows] = useState<BucketSummary[]>([]);
  const [dashboardSummary, setDashboardSummary] =
    useState<DashboardSummary | null>(null);
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

        const [feeResponse, bucketResponse, dashboardResponse] =
          await Promise.all([
            fetch(
              `${API_BASE}/api/analytics/lost-bike-fee-summary?${params.toString()}`,
            ),
            fetch(
              `${API_BASE}/api/analytics/duration-buckets?${params.toString()}&bucket_minutes=5`,
            ),
            fetch(
              `${API_BASE}/api/analytics/dashboard-summary?${params.toString()}`,
            ),
          ]);

        const [feeOk, bucketOk, dashboardOk] = [
          feeResponse.ok,
          bucketResponse.ok,
          dashboardResponse.ok,
        ];

        if (!feeOk || !bucketOk || !dashboardOk) {
          throw new Error("Unable to load filtered analytics data.");
        }

        const feePayload: unknown = await feeResponse.json();
        const bucketPayload: unknown = await bucketResponse.json();
        const dashboardPayload: unknown = await dashboardResponse.json();
        const feeData = parseFeeSummary(feePayload);
        const bucketData = parseBucketSummary(bucketPayload);
        const dashboardData = parseDashboardSummary(dashboardPayload);

        setFeeRows(feeData);
        setBucketRows(bucketData);
        setDashboardSummary(dashboardData);
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Unknown error loading analytics data.",
        );
        setFeeRows([]);
        setBucketRows([]);
        setDashboardSummary(null);
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

  const formatMinutes = (value: number) => `${value.toFixed(1)} min`;

  return (
    <main className="dashboard">
      <header className="dashboard-header">
        <h1>Citi Bike SQL Results</h1>
        <p>Minimal dashboard backed by FastAPI analytics endpoints.</p>
      </header>

      <section className="panel" aria-label="computed elements">
        <h2>Computed Elements</h2>
        {dashboardSummary ? (
          <>
            <ul className="notes-list">
              <li>
                Ride duration:{" "}
                {formatMinutes(dashboardSummary.summary.averageActualMinutes)}{" "}
                average across{" "}
                {dashboardSummary.summary.tripCount.toLocaleString()} trips.
              </li>
              <li>
                Estimated trip duration:{" "}
                {formatMinutes(
                  dashboardSummary.summary.averageEstimatedMinutes,
                )}{" "}
                using a local straight-line estimate at{" "}
                {dashboardSummary.estimatedSpeedMph.toFixed(1)} mph.
              </li>
              <li>
                Actual vs estimated delta:{" "}
                {formatMinutes(dashboardSummary.summary.averageDeltaMinutes)} on
                average.
              </li>
            </ul>

            <h3>Actual vs Estimated by Rider and Bike Type</h3>
            <table>
              <thead>
                <tr>
                  <th>Rider</th>
                  <th>Bike</th>
                  <th>Trips</th>
                  <th>Actual Avg</th>
                  <th>Estimated Avg</th>
                  <th>Delta</th>
                </tr>
              </thead>
              <tbody>
                {dashboardSummary.actualVsEstimated.map((row) => (
                  <tr key={`${row.memberCasual}-${row.rideableType}`}>
                    <td>{row.memberCasual}</td>
                    <td>{row.rideableType}</td>
                    <td>{row.tripCount.toLocaleString()}</td>
                    <td>{formatMinutes(row.averageActualMinutes)}</td>
                    <td>{formatMinutes(row.averageEstimatedMinutes)}</td>
                    <td>{formatMinutes(row.deltaMinutes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <h3>Station Usage</h3>
            <table>
              <thead>
                <tr>
                  <th>Station</th>
                  <th>ID</th>
                  <th>Arrivals</th>
                  <th>Departures</th>
                  <th>Total Trips</th>
                </tr>
              </thead>
              <tbody>
                {dashboardSummary.stationUsage.map((row) => (
                  <tr key={`${row.stationName}-${row.stationId}`}>
                    <td>{row.stationName}</td>
                    <td>{row.stationId}</td>
                    <td>{row.arrivals.toLocaleString()}</td>
                    <td>{row.departures.toLocaleString()}</td>
                    <td>{row.totalTrips.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <p className="status-loading">Computed summary loading...</p>
        )}
      </section>

      <section className="panel" aria-label="visualizations made">
        <h2>Visualizations Made</h2>
        {dashboardSummary ? (
          <>
            <h3>Histograms</h3>
            <table>
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Category</th>
                  <th>Trips</th>
                </tr>
              </thead>
              <tbody>
                {dashboardSummary.histogramByBikeType.map((row) => (
                  <tr key={`bike-${row.rideableType}`}>
                    <td>bike</td>
                    <td>{row.rideableType}</td>
                    <td>{row.tripCount.toLocaleString()}</td>
                  </tr>
                ))}
                {dashboardSummary.histogramByRiderType.map((row) => (
                  <tr key={`rider-${row.memberCasual}`}>
                    <td>rider</td>
                    <td>{row.memberCasual}</td>
                    <td>{row.tripCount.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <h3>Scatter: Trip Duration vs Time of Day</h3>
            <table>
              <thead>
                <tr>
                  <th>Hour</th>
                  <th>Rider</th>
                  <th>Trips</th>
                  <th>Avg Duration</th>
                </tr>
              </thead>
              <tbody>
                {dashboardSummary.durationByHour.map((row) => (
                  <tr key={`${row.hour}-${row.memberCasual}`}>
                    <td>{row.hour.toString().padStart(2, "0")} : 00</td>
                    <td>{row.memberCasual}</td>
                    <td>{row.tripCount.toLocaleString()}</td>
                    <td>{formatMinutes(row.averageDurationMinutes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <h3>Scatter: Start Longitude vs Start Latitude</h3>
            <table>
              <thead>
                <tr>
                  <th>Start Lat</th>
                  <th>Start Lng</th>
                  <th>Rider</th>
                  <th>Bike</th>
                  <th>Trips</th>
                </tr>
              </thead>
              <tbody>
                {dashboardSummary.originSpread.map((row) => (
                  <tr
                    key={`${row.startLat}-${row.startLng}-${row.memberCasual}-${row.rideableType}`}
                  >
                    <td>{row.startLat ?? "n/a"}</td>
                    <td>{row.startLng ?? "n/a"}</td>
                    <td>{row.memberCasual}</td>
                    <td>{row.rideableType}</td>
                    <td>{row.tripCount.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <h3>Scatter: Start Station vs End Station</h3>
            <table>
              <thead>
                <tr>
                  <th>Start Station</th>
                  <th>End Station</th>
                  <th>Trips</th>
                </tr>
              </thead>
              <tbody>
                {dashboardSummary.stationFlow.map((row) => (
                  <tr
                    key={`${row.startStationId}-${row.endStationId}-${row.startStationName}-${row.endStationName}`}
                  >
                    <td>{row.startStationName ?? "n/a"}</td>
                    <td>{row.endStationName ?? "n/a"}</td>
                    <td>{row.tripCount.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <h3>Scatter: Start Lng/Lat vs End Lng/Lat</h3>
            <table>
              <thead>
                <tr>
                  <th>Start Lat</th>
                  <th>Start Lng</th>
                  <th>End Lat</th>
                  <th>End Lng</th>
                  <th>Trips</th>
                </tr>
              </thead>
              <tbody>
                {dashboardSummary.coordinatePairs.map((row) => (
                  <tr
                    key={`${row.startLat}-${row.startLng}-${row.endLat}-${row.endLng}`}
                  >
                    <td>{row.startLat ?? "n/a"}</td>
                    <td>{row.startLng ?? "n/a"}</td>
                    <td>{row.endLat ?? "n/a"}</td>
                    <td>{row.endLng ?? "n/a"}</td>
                    <td>{row.tripCount.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <p className="status-loading">Visualization data loading...</p>
        )}
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
