import { useMemo, useState } from "react";
import "./App.css";
import { useQuery } from "@tanstack/react-query";
import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  PointElement,
  Tooltip,
  type ChartOptions,
} from "chart.js";
import { Bar, Scatter } from "react-chartjs-2";

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  PointElement,
  Tooltip,
  Legend,
);

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

const CHART_COLORS = {
  member: "#2563eb",
  casual: "#ea580c",
  electric: "#0f766e",
  classic: "#9333ea",
  start: "#0ea5e9",
  end: "#f97316",
  default: "#475569",
};

// const MAX_SCATTER_POINTS = 500;
const DURATION_BUCKET_MINUTES_MIN = 1;
const DURATION_BUCKET_MINUTES_MAX = 1400;

// function hashString(value: string): number {
//   let hash = 0;
//   for (let i = 0; i < value.length; i += 1) {
//     hash = (hash << 5) - hash + value.charCodeAt(i);
//     hash |= 0;
//   }
//   return Math.abs(hash);
// }

// function jitterFromKey(key: string, range = 0.32): number {
//   const seed = hashString(key) % 10_000;
//   const normalized = seed / 10_000;
//   return (normalized * 2 - 1) * range;
// }

function pointRadiusFromTrips(trips: number): number {
  if (trips >= 1_000) return 7;
  if (trips >= 200) return 5;
  if (trips >= 50) return 4;
  return 3;
}

const barOptions: ChartOptions<"bar"> = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { display: false },
  },
  scales: {
    x: {
      ticks: { color: "#334155" },
      grid: { display: false },
    },
    y: {
      beginAtZero: true,
      ticks: { color: "#334155" },
      grid: { color: "#e2e8f0" },
    },
  },
};

const scatterOptions: ChartOptions<"scatter"> = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { position: "top" },
  },
  scales: {
    x: {
      ticks: { color: "#334155" },
      grid: { color: "#e2e8f0" },
    },
    y: {
      ticks: { color: "#334155" },
      grid: { color: "#e2e8f0" },
    },
  },
};

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
  const [selectedMonth, setSelectedMonth] = useState<string>("");
  const [selectedRider, setSelectedRider] = useState<
    "all" | "member" | "casual"
  >("all");
  const [selectedBucketMinutes, setSelectedBucketMinutes] = useState<number>(5);
  const [isDurationBucketOpen, setIsDurationBucketOpen] =
    useState<boolean>(false);
  const [isMonthlyTripsOpen, setIsMonthlyTripsOpen] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<"overview" | "visualizations">(
    "overview",
  );

  // Fetch month counts once on initial load, then derive dropdown months from the same payload.
  const {
    data: monthlyTripCountsData = [],
    isLoading: isLoadingMonths,
    error: monthsError,
  } = useQuery({
    queryKey: ["monthlyTripCounts"],
    queryFn: async () => {
      const response = await fetch(
        `${API_BASE}/api/analytics/monthly-trip-counts`,
      );
      if (!response.ok) throw new Error("Unable to load monthly trip counts.");
      const payload: unknown = await response.json();
      return parseMonthCounts(payload);
    },
    staleTime: Infinity,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
  });

  const monthlyTripCounts = useMemo(
    () => monthlyTripCountsData,
    [monthlyTripCountsData],
  );

  const months = useMemo(
    () => monthlyTripCounts.map((item) => item.tripMonth),
    [monthlyTripCounts],
  );

  const mostRecentMonth = months[months.length - 1] || "";

  const selectedMonthForMonthlyCounts = selectedMonth || mostRecentMonth;

  const effectiveSelectedMonth =
    selectedMonth && selectedMonth !== "all" ? selectedMonth : mostRecentMonth;

  const {
    data: feeSummaryData,
    isLoading: isLoadingFeeSummary,
    error: feeSummaryError,
  } = useQuery({
    queryKey: ["analytics-fee-summary", effectiveSelectedMonth, selectedRider],
    queryFn: async () => {
      if (!effectiveSelectedMonth) {
        return [];
      }
      const params = new URLSearchParams({
        month: effectiveSelectedMonth,
        rider: selectedRider,
      });
      const response = await fetch(
        `${API_BASE}/api/analytics/lost-bike-fee-summary?${params.toString()}`,
      );
      if (!response.ok) {
        throw new Error("Unable to load lost bike fee summary data.");
      }
      const payload: unknown = await response.json();
      return parseFeeSummary(payload);
    },
    enabled: !!effectiveSelectedMonth,
  });

  const {
    data: dashboardSummaryData,
    isLoading: isLoadingDashboardSummary,
    error: dashboardSummaryError,
  } = useQuery({
    queryKey: [
      "analytics-dashboard-summary",
      effectiveSelectedMonth,
      selectedRider,
    ],
    queryFn: async () => {
      if (!effectiveSelectedMonth) {
        return null;
      }
      const params = new URLSearchParams({
        month: effectiveSelectedMonth,
        rider: selectedRider,
      });
      const response = await fetch(
        `${API_BASE}/api/analytics/dashboard-summary?${params.toString()}`,
      );
      if (!response.ok) {
        throw new Error("Unable to load dashboard summary data.");
      }
      const payload: unknown = await response.json();
      return parseDashboardSummary(payload);
    },
    enabled: !!effectiveSelectedMonth,
  });

  const {
    data: durationBucketData,
    isLoading: isLoadingDurationBuckets,
    error: durationBucketError,
  } = useQuery({
    queryKey: [
      "analytics-duration-buckets",
      effectiveSelectedMonth,
      selectedRider,
      selectedBucketMinutes,
    ],
    queryFn: async () => {
      if (!effectiveSelectedMonth) {
        return [];
      }
      const params = new URLSearchParams({
        month: effectiveSelectedMonth,
        rider: selectedRider,
      });
      const response = await fetch(
        `${API_BASE}/api/analytics/duration-buckets?${params.toString()}&bucket_minutes=${selectedBucketMinutes}`,
      );
      if (!response.ok) {
        throw new Error("Unable to load duration bucket data.");
      }
      const payload: unknown = await response.json();
      return parseBucketSummary(payload);
    },
    enabled: !!effectiveSelectedMonth,
  });

  const durationBucketMinuteOptions = useMemo(
    () =>
      Array.from(
        {
          length: DURATION_BUCKET_MINUTES_MAX - DURATION_BUCKET_MINUTES_MIN + 1,
        },
        (_, index) => DURATION_BUCKET_MINUTES_MIN + index,
      ),
    [],
  );

  const feeRows = useMemo(() => feeSummaryData ?? [], [feeSummaryData]);
  const bucketRows = useMemo(
    () => durationBucketData ?? [],
    [durationBucketData],
  );
  const dashboardSummary = useMemo(
    () => dashboardSummaryData ?? null,
    [dashboardSummaryData],
  );

  const bikeHistogramChartData = useMemo(() => {
    if (!dashboardSummary) {
      return { labels: [], datasets: [] };
    }

    const labels = dashboardSummary.histogramByBikeType.map(
      (row) => row.rideableType ?? "unknown",
    );
    const values = dashboardSummary.histogramByBikeType.map(
      (row) => row.tripCount,
    );

    return {
      labels,
      datasets: [
        {
          label: "Trips",
          data: values,
          backgroundColor: labels.map((label) =>
            label === "electric"
              ? CHART_COLORS.electric
              : label === "classic"
                ? CHART_COLORS.classic
                : CHART_COLORS.default,
          ),
        },
      ],
    };
  }, [dashboardSummary]);

  const riderHistogramChartData = useMemo(() => {
    if (!dashboardSummary) {
      return { labels: [], datasets: [] };
    }

    const labels = dashboardSummary.histogramByRiderType.map(
      (row) => row.memberCasual ?? "unknown",
    );
    const values = dashboardSummary.histogramByRiderType.map(
      (row) => row.tripCount,
    );

    return {
      labels,
      datasets: [
        {
          label: "Trips",
          data: values,
          backgroundColor: labels.map((label) =>
            label === "member"
              ? CHART_COLORS.member
              : label === "casual"
                ? CHART_COLORS.casual
                : CHART_COLORS.default,
          ),
        },
      ],
    };
  }, [dashboardSummary]);

  const durationByHourChartData = useMemo(() => {
    if (!dashboardSummary) {
      return { datasets: [] };
    }

    const memberPoints = dashboardSummary.durationByHour
      .filter((row) => row.memberCasual === "member")
      .map((row) => ({
        x: row.hour,
        y: row.averageDurationMinutes,
        trips: row.tripCount,
      }));

    const casualPoints = dashboardSummary.durationByHour
      .filter((row) => row.memberCasual === "casual")
      .map((row) => ({
        x: row.hour,
        y: row.averageDurationMinutes,
        trips: row.tripCount,
      }));

    return {
      datasets: [
        {
          label: "member",
          data: memberPoints,
          backgroundColor: CHART_COLORS.member,
          pointRadius: memberPoints.map((point) =>
            pointRadiusFromTrips(point.trips),
          ),
        },
        {
          label: "casual",
          data: casualPoints,
          backgroundColor: CHART_COLORS.casual,
          pointRadius: casualPoints.map((point) =>
            pointRadiusFromTrips(point.trips),
          ),
        },
      ],
    };
  }, [dashboardSummary]);

  const durationBucketsHistogramChartData = useMemo(() => {
    if (bucketRows.length === 0) {
      return { labels: [], datasets: [] };
    }

    // Group by bucket, then by memberCasual
    const bucketMap = new Map<string, { member: number; casual: number }>();

    for (const row of bucketRows) {
      if (!bucketMap.has(row.bucket)) {
        bucketMap.set(row.bucket, { member: 0, casual: 0 });
      }
      const counts = bucketMap.get(row.bucket)!;
      if (row.memberCasual === "member") {
        counts.member += row.trips;
      } else {
        counts.casual += row.trips;
      }
    }

    // Order buckets numerically by their lower bound
    const labels = Array.from(bucketMap.keys()).sort((a, b) => {
      const aStart = parseInt(a.split("–")[0], 10);
      const bStart = parseInt(b.split("–")[0], 10);
      return aStart - bStart;
    });

    const memberData = labels.map(
      (bucket) => bucketMap.get(bucket)?.member ?? 0,
    );
    const casualData = labels.map(
      (bucket) => bucketMap.get(bucket)?.casual ?? 0,
    );

    return {
      labels,
      datasets: [
        {
          label: "member",
          data: memberData,
          backgroundColor: CHART_COLORS.member,
        },
        {
          label: "casual",
          data: casualData,
          backgroundColor: CHART_COLORS.casual,
        },
      ],
    };
  }, [bucketRows]);

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
        <h1>Citi Bike Ride Data Dashboard</h1>
        <p>Backed by FastAPI analytics endpoints.</p>
      </header>

      <section className="filters" aria-label="filters">
        <label>
          Month
          <select
            value={selectedMonthForMonthlyCounts}
            onChange={(event) => setSelectedMonth(event.target.value)}
            disabled={months.length === 0}
          >
            <option value="all">all</option>
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
            disabled={!effectiveSelectedMonth}
          >
            <option value="all">all</option>
            <option value="member">member</option>
            <option value="casual">casual</option>
          </select>
        </label>
      </section>

      <section className="tabs" aria-label="dashboard tabs">
        <button
          type="button"
          className={activeTab === "overview" ? "tab tab-active" : "tab"}
          onClick={() => setActiveTab("overview")}
        >
          Overview
        </button>
        <button
          type="button"
          className={activeTab === "visualizations" ? "tab tab-active" : "tab"}
          onClick={() => setActiveTab("visualizations")}
        >
          Visualizations
        </button>
      </section>

      {activeTab === "overview" ? (
        <>
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

          <section className="panel" aria-label="computed elements">
            <h2>Ride Metrics</h2>
            {dashboardSummary ? (
              <>
                <ul className="notes-list">
                  <li>
                    Ride duration:{" "}
                    {formatMinutes(
                      dashboardSummary.summary.averageActualMinutes,
                    )}{" "}
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
                    {formatMinutes(
                      dashboardSummary.summary.averageDeltaMinutes,
                    )}{" "}
                    on average.
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

          <section className="panel" aria-label="monthly trip counts">
            <div className="panel-header panel-header-split">
              <h2>Monthly Trip Counts</h2>
              <button
                type="button"
                className="toggle-button"
                onClick={() => setIsMonthlyTripsOpen((current) => !current)}
                aria-expanded={isMonthlyTripsOpen}
                aria-controls="monthly-trips-content"
              >
                {isMonthlyTripsOpen ? "Collapse" : "Expand"}
              </button>
            </div>

            {isMonthlyTripsOpen ? (
              <div id="monthly-trips-content">
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
              </div>
            ) : null}
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
            <div className="panel-header panel-header-split">
              <h2>Ride Duration by {selectedBucketMinutes}-Minute Bucket</h2>
              <button
                type="button"
                className="toggle-button"
                onClick={() => setIsDurationBucketOpen((current) => !current)}
                aria-expanded={isDurationBucketOpen}
                aria-controls="duration-bucket-content"
              >
                {isDurationBucketOpen ? "Collapse" : "Expand"}
              </button>
            </div>

            <div className="duration-bucket-controls">
              <label>
                Bucket Minutes
                <select
                  value={selectedBucketMinutes}
                  onChange={(event) =>
                    setSelectedBucketMinutes(Number(event.target.value))
                  }
                  disabled={!effectiveSelectedMonth}
                >
                  {durationBucketMinuteOptions.map((minutes) => (
                    <option key={minutes} value={minutes}>
                      {minutes} minute{minutes === 1 ? "" : "s"}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            {isDurationBucketOpen ? (
              <div id="duration-bucket-content">
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
                      <tr
                        key={`${row.tripMonth}-${row.memberCasual}-${row.bucket}`}
                      >
                        <td>{row.tripMonth}</td>
                        <td>{row.memberCasual}</td>
                        <td>{row.bucket}</td>
                        <td>{row.trips.toLocaleString()}</td>
                        <td>{row.lostBikeFeeFlag ? "yes" : "no"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </section>
        </>
      ) : null}

      {activeTab === "visualizations" ? (
        <section className="panel" aria-label="visualizations made">
          <h2>Visualizations Made</h2>
          {dashboardSummary ? (
            <>
              <h3>Histograms</h3>
              <div className="chart-grid chart-grid-2up">
                <div className="chart-card">
                  <h4>By Bike Type</h4>
                  <div className="chart-wrapper">
                    <Bar data={bikeHistogramChartData} options={barOptions} />
                  </div>
                </div>
                <div className="chart-card">
                  <h4>By Rider Type</h4>
                  <div className="chart-wrapper">
                    <Bar data={riderHistogramChartData} options={barOptions} />
                  </div>
                </div>
              </div>

              <h3>Scatter: Trip Duration vs Time of Day</h3>
              <div className="chart-wrapper">
                <Scatter
                  data={durationByHourChartData}
                  options={{
                    ...scatterOptions,
                    scales: {
                      x: {
                        ...scatterOptions.scales?.x,
                        title: { display: true, text: "Hour of Day" },
                        min: -0.5,
                        max: 23.5,
                      },
                      y: {
                        ...scatterOptions.scales?.y,
                        title: {
                          display: true,
                          text: "Average Duration (minutes)",
                        },
                      },
                    },
                  }}
                />
              </div>

              <h3>Duration Buckets by Rider Type</h3>
              <div className="chart-wrapper">
                <Bar
                  data={durationBucketsHistogramChartData}
                  options={barOptions}
                />
              </div>
            </>
          ) : (
            <p className="status-loading">Visualization data loading...</p>
          )}
        </section>
      ) : null}

      {monthsError ? (
        <p className="status-error">{monthsError.message}</p>
      ) : null}
      {feeSummaryError ? (
        <p className="status-error">{feeSummaryError.message}</p>
      ) : null}
      {dashboardSummaryError ? (
        <p className="status-error">{dashboardSummaryError.message}</p>
      ) : null}
      {durationBucketError ? (
        <p className="status-error">{durationBucketError.message}</p>
      ) : null}
      {isLoadingMonths ||
      isLoadingFeeSummary ||
      isLoadingDashboardSummary ||
      isLoadingDurationBuckets ? (
        <p className="status-loading">Loading data...</p>
      ) : null}
    </main>
  );
}

export default App;
