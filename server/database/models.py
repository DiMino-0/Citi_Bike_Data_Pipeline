from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlmodel import Field, SQLModel


NEW_YORK_TZ = ZoneInfo("America/New_York")


def _new_york_now_naive() -> datetime:
    return datetime.now(NEW_YORK_TZ).replace(tzinfo=None)


class CitiBikeTrip(SQLModel, table=True):
    __tablename__ = "citibike_trips"  # pyright: ignore[reportAssignmentType]

    id: Optional[int] = Field(default=None, primary_key=True)
    ride_id: str = Field(index=True, unique=True)
    rideable_type: str
    started_at: datetime
    ended_at: datetime
    start_station_name: Optional[str] = None
    start_station_id: Optional[str] = Field(default=None, index=True)
    end_station_name: Optional[str] = None
    end_station_id: Optional[str] = Field(default=None, index=True)
    start_lat: Optional[float] = None
    start_lng: Optional[float] = None
    end_lat: Optional[float] = None
    end_lng: Optional[float] = None
    member_casual: str = Field(index=True)
    trip_month: str = Field(index=True, max_length=6)
    created_at: datetime = Field(default_factory=_new_york_now_naive, nullable=False)
