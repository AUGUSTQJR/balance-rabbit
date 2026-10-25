"""数据模型：一个 Stats 就是气泡里要显示的全部内容。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class DayStat:
    date: date
    spend: float = 0.0
    requests: int = 0


@dataclass
class Stats:
    balance: float | None = None
    balance_at: str | None = None
    today_spend: float = 0.0
    today_requests: int = 0
    week_spend: float = 0.0
    week_requests: int = 0
    week_tokens: int = 0
    total_requests: int | None = None
    daily: list[DayStat] = field(default_factory=list)
    top_models: list[tuple[str, int]] = field(default_factory=list)
    updated_at: datetime = field(default_factory=datetime.now)
    partial: bool = False
    error: str | None = None
    account_user_id: int | None = None
    multiple_accounts: bool = False
    balance_from_api: bool = False
    account_inactive: bool = False
    week_recharged: float = 0.0
    data_source: str = "usage"

    def is_low(self, threshold: float) -> bool:
        if self.balance is None or threshold <= 0:
            return False
        return self.balance < threshold


@dataclass
class AccountBalance:
    user_id: int | None
    balance: float
    is_active: bool | None


@dataclass
class SpendingDay:
    date: date
    requests: int
    spend: float
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class SpendingReport:
    user_id: int | None
    balance: float | None
    request_count: int
    charged: float
    recharged: float
    totals_tokens: int
    days: list[SpendingDay]


@dataclass
class UsageItem:
    created_at: str | None
    model: str | None
    charged_cny: float | None
    balance_cny: float | None
    user_id: int | None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class UsagePage:
    total: int | None
    items: list[UsageItem]
