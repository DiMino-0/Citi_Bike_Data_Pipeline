CREATE TABLE IF NOT EXISTS citibike_trips (
    id BIGSERIAL PRIMARY KEY,
    ride_id TEXT NOT NULL,
    rideable_type TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP NOT NULL,
    start_station_name TEXT,
    start_station_id TEXT,
    end_station_name TEXT,
    end_station_id TEXT,
    start_lat DOUBLE PRECISION,
    start_lng DOUBLE PRECISION,
    end_lat DOUBLE PRECISION,
    end_lng DOUBLE PRECISION,
    member_casual TEXT NOT NULL,
    trip_month VARCHAR(6) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Enforce one record per vendor ride identifier.
    CONSTRAINT uq_citibike_trips_ride_id UNIQUE (ride_id),
    -- Keep month key in YYYYMM numeric format.
    CONSTRAINT ck_citibike_trips_trip_month_format CHECK (trip_month ~ '^[0-9]{6}$')
);

-- Supports station-based lookups/joins where start_station_id is present.
CREATE INDEX IF NOT EXISTS ix_citibike_trips_start_station_id
    ON citibike_trips (start_station_id)
    WHERE start_station_id IS NOT NULL;

-- Supports station-based lookups/joins where end_station_id is present.
CREATE INDEX IF NOT EXISTS ix_citibike_trips_end_station_id
    ON citibike_trips (end_station_id)
    WHERE end_station_id IS NOT NULL;

-- Supports filters/grouping by rider type.
CREATE INDEX IF NOT EXISTS ix_citibike_trips_member_casual
    ON citibike_trips (member_casual);

-- Supports month filtering and month-based aggregates.
CREATE INDEX IF NOT EXISTS ix_citibike_trips_trip_month
    ON citibike_trips (trip_month);

-- Optimizes month-scoped recent-trip queries ordered by started_at DESC.
CREATE INDEX IF NOT EXISTS ix_citibike_trips_month_started_desc
    ON citibike_trips (trip_month DESC, started_at DESC);

-- Optimizes monthly analytics grouped/filtered by member_casual.
CREATE INDEX IF NOT EXISTS ix_citibike_trips_month_member
    ON citibike_trips (trip_month, member_casual);

-- Targets long-trip fee-review queries (> 1440 minutes) with a partial expression index.
CREATE INDEX IF NOT EXISTS ix_citibike_trips_long_duration
    ON citibike_trips (((EXTRACT(EPOCH FROM (ended_at - started_at)) / 60)))
    WHERE ended_at IS NOT NULL
      AND started_at IS NOT NULL
      AND EXTRACT(EPOCH FROM (ended_at - started_at)) / 60 > 1440;