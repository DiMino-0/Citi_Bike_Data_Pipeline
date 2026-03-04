SHOW search_path;

-- ------------------------------------------------------------
-- Month filtering / sorting
-- ------------------------------------------------------------

-- 1) Most recent trips first (all months)
SELECT ride_id, trip_month, started_at, ended_at, member_casual
FROM citibike_trips
ORDER BY trip_month DESC, started_at DESC
LIMIT 100;

-- 2) Trips for a single month (YYYYMM)
SELECT ride_id, trip_month, started_at, ended_at, member_casual
FROM citibike_trips
WHERE trip_month = '202602'
ORDER BY started_at DESC
LIMIT 200;

-- 3) Trips across a month range (inclusive)
SELECT ride_id, trip_month, started_at, ended_at
FROM citibike_trips
WHERE trip_month BETWEEN '202601' AND '202603'
ORDER BY trip_month, started_at;

-- 4) Monthly trip counts
SELECT trip_month, COUNT(*) AS trip_count
FROM citibike_trips
GROUP BY trip_month
ORDER BY trip_month;

-- ------------------------------------------------------------
-- Trip durations and bucketing
-- ------------------------------------------------------------

-- Base CTE for duration in whole minutes (ignore invalid negative durations)
WITH durations AS (
	SELECT
		ride_id,
		trip_month,
		started_at,
		ended_at,
		GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (ended_at - started_at)) / 60))::int AS duration_min
	FROM citibike_trips
	WHERE ended_at IS NOT NULL
		AND started_at IS NOT NULL
)
SELECT *
FROM durations
ORDER BY duration_min DESC
LIMIT 50;

-- 5) 2-minute duration buckets up to 24h; >24h flagged as LOST_BIKE_FEE
WITH durations AS (
	SELECT
		ride_id,
		trip_month,
		GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (ended_at - started_at)) / 60))::int AS duration_min
	FROM citibike_trips
	WHERE ended_at IS NOT NULL
		AND started_at IS NOT NULL
), bucketed AS (
	SELECT
		ride_id,
		trip_month,
		duration_min,
		CASE
			WHEN duration_min > 1440 THEN 'LOST_BIKE_FEE'
			ELSE
				CONCAT(
					LPAD(((duration_min / 2) * 2)::text, 4, '0'),
					'-',
					LPAD((((duration_min / 2) * 2) + 1)::text, 4, '0'),
					' min'
				)
		END AS bucket_2m,
		CASE WHEN duration_min > 1440 THEN true ELSE false END AS lost_bike_fee_flag
	FROM durations
)
SELECT
	bucket_2m,
	lost_bike_fee_flag,
	COUNT(*) AS trips
FROM bucketed
GROUP BY bucket_2m, lost_bike_fee_flag
ORDER BY
	CASE WHEN bucket_2m = 'LOST_BIKE_FEE' THEN 1 ELSE 0 END,
	bucket_2m;

-- 6) 5-minute duration buckets up to 24h; >24h flagged as LOST_BIKE_FEE
WITH durations AS (
	SELECT
		ride_id,
		trip_month,
		GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (ended_at - started_at)) / 60))::int AS duration_min
	FROM citibike_trips
	WHERE ended_at IS NOT NULL
		AND started_at IS NOT NULL
), bucketed AS (
	SELECT
		ride_id,
		trip_month,
		duration_min,
		CASE
			WHEN duration_min > 1440 THEN 'LOST_BIKE_FEE'
			ELSE
				CONCAT(
					LPAD(((duration_min / 5) * 5)::text, 4, '0'),
					'-',
					LPAD((((duration_min / 5) * 5) + 4)::text, 4, '0'),
					' min'
				)
		END AS bucket_5m,
		CASE WHEN duration_min > 1440 THEN true ELSE false END AS lost_bike_fee_flag
	FROM durations
)
SELECT
	bucket_5m,
	lost_bike_fee_flag,
	COUNT(*) AS trips
FROM bucketed
GROUP BY bucket_5m, lost_bike_fee_flag
ORDER BY
	CASE WHEN bucket_5m = 'LOST_BIKE_FEE' THEN 1 ELSE 0 END,
	bucket_5m;

-- 7) Detailed long-trip list for fee review (>24h)
SELECT
	ride_id,
	trip_month,
	started_at,
	ended_at,
	FLOOR(EXTRACT(EPOCH FROM (ended_at - started_at)) / 60)::int AS duration_min,
	'LOST_BIKE_FEE' AS fee_reason
FROM citibike_trips
WHERE ended_at IS NOT NULL
	AND started_at IS NOT NULL
	AND EXTRACT(EPOCH FROM (ended_at - started_at)) / 60 > 1440
ORDER BY duration_min DESC;

-- ------------------------------------------------------------
-- Grouped analytics by rider type and month
-- ------------------------------------------------------------

-- 8) 2-minute buckets by trip_month + member_casual, with fee flag bucket
WITH durations AS (
	SELECT
		trip_month,
		member_casual,
		GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (ended_at - started_at)) / 60))::int AS duration_min
	FROM citibike_trips
	WHERE ended_at IS NOT NULL
		AND started_at IS NOT NULL
), bucketed AS (
	SELECT
		trip_month,
		member_casual,
		CASE
			WHEN duration_min > 1440 THEN 'LOST_BIKE_FEE'
			ELSE CONCAT(
				LPAD(((duration_min / 2) * 2)::text, 4, '0'),
				'-',
				LPAD((((duration_min / 2) * 2) + 1)::text, 4, '0'),
				' min'
			)
		END AS bucket_2m
	FROM durations
)
SELECT
	trip_month,
	member_casual,
	bucket_2m,
	COUNT(*) AS trips
FROM bucketed
GROUP BY trip_month, member_casual, bucket_2m
ORDER BY trip_month, member_casual,
	CASE WHEN bucket_2m = 'LOST_BIKE_FEE' THEN 1 ELSE 0 END,
	bucket_2m;

-- 9) 5-minute buckets by trip_month + member_casual, with fee flag bucket
WITH durations AS (
	SELECT
		trip_month,
		member_casual,
		GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (ended_at - started_at)) / 60))::int AS duration_min
	FROM citibike_trips
	WHERE ended_at IS NOT NULL
		AND started_at IS NOT NULL
), bucketed AS (
	SELECT
		trip_month,
		member_casual,
		CASE
			WHEN duration_min > 1440 THEN 'LOST_BIKE_FEE'
			ELSE CONCAT(
				LPAD(((duration_min / 5) * 5)::text, 4, '0'),
				'-',
				LPAD((((duration_min / 5) * 5) + 4)::text, 4, '0'),
				' min'
			)
		END AS bucket_5m
	FROM durations
)
SELECT
	trip_month,
	member_casual,
	bucket_5m,
	COUNT(*) AS trips
FROM bucketed
GROUP BY trip_month, member_casual, bucket_5m
ORDER BY trip_month, member_casual,
	CASE WHEN bucket_5m = 'LOST_BIKE_FEE' THEN 1 ELSE 0 END,
	bucket_5m;

-- 10) Lost-bike-fee candidates count by month and rider type
WITH durations AS (
	SELECT
		trip_month,
		member_casual,
		GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (ended_at - started_at)) / 60))::int AS duration_min
	FROM citibike_trips
	WHERE ended_at IS NOT NULL
		AND started_at IS NOT NULL
)
SELECT
	trip_month,
	member_casual,
	COUNT(*) FILTER (WHERE duration_min > 1440) AS lost_bike_fee_trips,
	COUNT(*) AS total_trips,
	ROUND(
		100.0 * COUNT(*) FILTER (WHERE duration_min > 1440) / NULLIF(COUNT(*), 0),
		2
	) AS lost_bike_fee_pct
FROM durations
GROUP BY trip_month, member_casual
ORDER BY trip_month, member_casual;

-- 11) Pivoted month summary: member vs casual + fee candidates
WITH durations AS (
	SELECT
		trip_month,
		member_casual,
		GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (ended_at - started_at)) / 60))::int AS duration_min
	FROM citibike_trips
	WHERE ended_at IS NOT NULL
		AND started_at IS NOT NULL
)
SELECT
	trip_month,
	COUNT(*) FILTER (WHERE LOWER(member_casual) = 'member') AS member_trips,
	COUNT(*) FILTER (WHERE LOWER(member_casual) = 'casual') AS casual_trips,
	COUNT(*) FILTER (WHERE LOWER(member_casual) = 'member' AND duration_min > 1440) AS member_lost_bike_fee_trips,
	COUNT(*) FILTER (WHERE LOWER(member_casual) = 'casual' AND duration_min > 1440) AS casual_lost_bike_fee_trips,
	COUNT(*) FILTER (WHERE duration_min > 1440) AS total_lost_bike_fee_trips,
	COUNT(*) AS total_trips
FROM durations
GROUP BY trip_month
ORDER BY trip_month;

-- 12) Parameterized bucket query (change bucket_minutes in one place)
--     Example values: 2, 5, 10, 15
WITH params AS (
	SELECT
		5::int AS bucket_minutes,
		1440::int AS max_minutes
), durations AS (
	SELECT
		trip_month,
		LOWER(member_casual) AS member_casual,
		GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (ended_at - started_at)) / 60))::int AS duration_min
	FROM citibike_trips
	WHERE ended_at IS NOT NULL
		AND started_at IS NOT NULL
), bucketed AS (
	SELECT
		d.trip_month,
		d.member_casual,
		d.duration_min,
		p.bucket_minutes,
		p.max_minutes,
		CASE
			WHEN d.duration_min > p.max_minutes THEN 'LOST_BIKE_FEE'
			ELSE CONCAT(
				LPAD(((d.duration_min / p.bucket_minutes) * p.bucket_minutes)::text, 4, '0'),
				'-',
				LPAD((((d.duration_min / p.bucket_minutes) * p.bucket_minutes) + p.bucket_minutes - 1)::text, 4, '0'),
				' min'
			)
		END AS duration_bucket
	FROM durations d
	CROSS JOIN params p
)
SELECT
	trip_month,
	duration_bucket,
	COUNT(*) FILTER (WHERE member_casual = 'member') AS member_trips,
	COUNT(*) FILTER (WHERE member_casual = 'casual') AS casual_trips,
	COUNT(*) AS total_trips,
	COUNT(*) FILTER (WHERE duration_min > max_minutes) AS lost_bike_fee_trips
FROM bucketed
GROUP BY trip_month, duration_bucket
ORDER BY
	trip_month,
	CASE WHEN duration_bucket = 'LOST_BIKE_FEE' THEN 1 ELSE 0 END,
	duration_bucket;
