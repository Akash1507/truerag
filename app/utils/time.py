from datetime import UTC, datetime


def current_month_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m")
