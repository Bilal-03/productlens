from __future__ import annotations

from datetime import date, timedelta

from app.models.contracts import DateRange

DATASET_AS_OF = date(2026, 8, 24)


def resolve_period(name: str, as_of: date = DATASET_AS_OF) -> DateRange:
    if name in {"last_week", "week_over_week"}:
        end = as_of - timedelta(days=as_of.weekday())
        start = end - timedelta(days=7)
        return DateRange(start=start, end=end, label="Last completed week")
    if name == "previous_week":
        current = resolve_period("last_week", as_of)
        return DateRange(
            start=current.start - timedelta(days=7),
            end=current.start,
            label="Previous completed week",
        )
    if name == "last_month":
        current_month = as_of.replace(day=1)
        previous_end = current_month
        previous_start = (current_month - timedelta(days=1)).replace(day=1)
        return DateRange(start=previous_start, end=previous_end, label="Last completed month")
    if name == "previous_month":
        last = resolve_period("last_month", as_of)
        end = last.start
        start = (end - timedelta(days=1)).replace(day=1)
        return DateRange(start=start, end=end, label="Previous completed month")
    if name == "this_month":
        return DateRange(start=as_of.replace(day=1), end=as_of, label="Month to date")
    if name == "previous_month_to_date":
        current = resolve_period("this_month", as_of)
        previous_start = (current.start - timedelta(days=1)).replace(day=1)
        days = (current.end - current.start).days
        return DateRange(
            start=previous_start,
            end=previous_start + timedelta(days=days),
            label="Previous month, same elapsed days",
        )
    rolling_days = {"last_7_days": 7, "last_30_days": 30, "last_90_days": 90}.get(name)
    if rolling_days:
        return DateRange(start=as_of - timedelta(days=rolling_days), end=as_of, label=name.replace("_", " ").title())
    raise ValueError(f"Unsupported period: {name}")


def default_comparison(period: str, as_of: date = DATASET_AS_OF) -> DateRange | None:
    mapping = {
        "last_week": "previous_week",
        "week_over_week": "previous_week",
        "last_month": "previous_month",
        "this_month": "previous_month_to_date",
    }
    if period in mapping:
        return resolve_period(mapping[period], as_of)
    current = resolve_period(period, as_of)
    duration = current.end - current.start
    return DateRange(
        start=current.start - duration,
        end=current.start,
        label="Previous equal-length period",
    )
