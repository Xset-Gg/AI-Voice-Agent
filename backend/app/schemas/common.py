import re
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, ConfigDict

E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")
HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _e164(v: str) -> str:
    v = re.sub(r"[\s\-().]", "", v)
    if not E164_RE.match(v):
        raise ValueError("Phone number must be in E.164 format, e.g. +15551234567")
    return v


def _tz(v: str) -> str:
    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Unknown timezone '{v}'")
    return v


def _hours(v: dict) -> dict:
    out: dict[str, list[list[str]]] = {}
    for day in WEEKDAYS:
        ranges = v.get(day, [])
        cleaned = []
        for r in ranges:
            if len(r) != 2 or not all(isinstance(x, str) and HHMM_RE.match(x) for x in r):
                raise ValueError(f"Invalid time range for {day}: {r!r} (expected ['HH:MM','HH:MM'])")
            if r[0] >= r[1]:
                raise ValueError(f"Range start must be before end for {day}: {r!r}")
            cleaned.append([r[0], r[1]])
        out[day] = sorted(cleaned)
    unknown = set(v) - set(WEEKDAYS)
    if unknown:
        raise ValueError(f"Unknown weekday keys: {sorted(unknown)}")
    return out


E164 = Annotated[str, AfterValidator(_e164)]
Timezone = Annotated[str, AfterValidator(_tz)]
WorkingHours = Annotated[dict, AfterValidator(_hours)]
