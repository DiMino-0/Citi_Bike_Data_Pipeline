-- Roll back non-constraint indexes created for citibike_trips tuning.
-- Note: Primary key and unique constraints are intentionally not dropped here.

DROP INDEX IF EXISTS ix_citibike_trips_long_duration;
DROP INDEX IF EXISTS ix_citibike_trips_month_member;
DROP INDEX IF EXISTS ix_citibike_trips_month_started_desc;
DROP INDEX IF EXISTS ix_citibike_trips_trip_month;
DROP INDEX IF EXISTS ix_citibike_trips_member_casual;
DROP INDEX IF EXISTS ix_citibike_trips_end_station_id;
DROP INDEX IF EXISTS ix_citibike_trips_start_station_id;