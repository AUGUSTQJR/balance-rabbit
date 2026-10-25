"""格式化与日期小工具（不依赖 Qt，方便单测）。"""

from __future__ import annotations

from datetime import date, datetime


def money2(value: float) -> str:
    return "¥%.2f" % value


def money_smart(value: float) -> str:
    """小额消费保留更多小数位，避免都显示成 ¥0.00。"""
    if value == 0:
        return "¥0"
    if abs(value) < 0.01:
        return "¥%.4f" % value
    if abs(value) < 1:
        return "¥%.3f" % value
    return "¥%.2f" % value


def tokens_text(value: int) -> str:
    if value >= 100_000_000:
        return "%.2f 亿" % (value / 100_000_000)
    if value >= 10_000:
        return "%.1f 万" % (value / 10_000)
    return str(value)


def time_text(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def short_date(day: date) -> str:
    return "%d/%d" % (day.month, day.day)


def parse_api_datetime(text: str | None) -> datetime | None:
    """接口里的 created_at 形如 2026-10-18T22:06:31（服务器本地时间）。"""
    if not text:
        return None
    try:
        return datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def parse_day(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
