"""rabbitj.top 账户接口客户端。

优先使用官方账户接口（余额 + 逐日花费），/v1/usage 只取最近 1~2 页做模型分布
与累计请求数；两个账户接口都不可用时，回退到旧版翻页聚合。
"""

from __future__ import annotations

import json
import math
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from .models import (
    AccountBalance,
    DayStat,
    SpendingDay,
    SpendingReport,
    Stats,
    UsageItem,
    UsagePage,
)
from .util import parse_api_datetime, parse_day

DEFAULT_BASE = "https://www.rabbitj.top"
USER_AGENT = "BalanceRabbit-Linux/1.0 (+https://www.rabbitj.top)"
# 服务器按 Asia/Shanghai 切天；固定 +08:00，避免本机时区不同导致“今日”错位。
SERVER_TZ = timezone(timedelta(hours=8))


def server_today() -> date:
    return datetime.now(SERVER_TZ).date()


class APIError(Exception):
    """带中文提示的接口错误。"""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.message = message
        self.status = status

    def __str__(self) -> str:
        return self.message


def _number(value) -> float | None:
    if isinstance(value, bool):
        return None
    number: float | None = None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    if number is None or not math.isfinite(number):
        return None
    return number


def _integer(value) -> int | None:
    number = _number(value)
    if number is None:
        return None
    return int(number)


def parse_account_balance(payload) -> AccountBalance | None:
    """GET /v1/account/balance 的解析（兼容 data 嵌套）。"""
    for _ in range(3):
        if not isinstance(payload, dict):
            return None
        balance = _number(payload.get("balance_cny"))
        if balance is None:
            balance = _number(payload.get("balance"))
        if balance is not None:
            return AccountBalance(
                user_id=_integer(payload.get("user_id")) or _integer(payload.get("account_user_id")),
                balance=balance,
                is_active=payload.get("is_active") if isinstance(payload.get("is_active"), bool) else None,
            )
        payload = payload.get("data")
    return None


def parse_spending(payload) -> SpendingReport | None:
    if not isinstance(payload, dict):
        return None
    totals = payload.get("totals")
    if not isinstance(totals, dict):
        return None
    days: list[SpendingDay] = []
    for item in payload.get("days") or []:
        if not isinstance(item, dict):
            continue
        day = parse_day(item.get("date"))
        if day is None:
            continue
        days.append(
            SpendingDay(
                date=day,
                requests=_integer(item.get("request_count")) or 0,
                spend=_number(item.get("charged_cny")) or 0.0,
                input_tokens=_integer(item.get("input_tokens")) or 0,
                output_tokens=_integer(item.get("output_tokens")) or 0,
                cache_read_tokens=_integer(item.get("cache_read_tokens")) or 0,
                cache_write_tokens=_integer(item.get("cache_write_tokens")) or 0,
            )
        )
    tokens = sum(
        _integer(totals.get(name)) or 0
        for name in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
    )
    return SpendingReport(
        user_id=_integer(payload.get("user_id")),
        balance=_number(payload.get("balance_cny")),
        request_count=_integer(totals.get("request_count")) or 0,
        charged=_number(totals.get("charged_cny")) or 0.0,
        recharged=_number(totals.get("recharged_cny")) or 0.0,
        totals_tokens=tokens,
        days=days,
    )


def parse_usage_page(payload) -> UsagePage:
    if not isinstance(payload, dict):
        raise APIError("接口返回格式异常")
    items: list[UsageItem] = []
    for raw in payload.get("items") or []:
        if not isinstance(raw, dict):
            continue
        items.append(
            UsageItem(
                created_at=raw.get("created_at") if isinstance(raw.get("created_at"), str) else None,
                model=raw.get("model") if isinstance(raw.get("model"), str) else None,
                charged_cny=_number(raw.get("charged_cny")),
                balance_cny=_number(raw.get("balance_cny")),
                user_id=_integer(raw.get("user_id")),
                input_tokens=_integer(raw.get("input_tokens")) or 0,
                output_tokens=_integer(raw.get("output_tokens")) or 0,
                cache_read_tokens=_integer(raw.get("cache_read_tokens")) or 0,
                cache_write_tokens=_integer(raw.get("cache_write_tokens")) or 0,
            )
        )
    return UsagePage(total=_integer(payload.get("total")), items=items)


class ApiClient:
    def __init__(self, base: str = DEFAULT_BASE, timeout: float = 20.0):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self._context = ssl.create_default_context()

    # ------------------------------------------------------------------ HTTP

    def _get_json(self, path: str, key: str, params: dict | None = None) -> object:
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": "Bearer " + key,
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=self._context) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            status = error.code
            if status == 401:
                raise APIError("未携带 API Key（HTTP 401）", status) from error
            if status == 403:
                raise APIError("API Key 无效或已被删除（HTTP 403）", status) from error
            if status == 422:
                raise APIError("日期参数不合法（HTTP 422）", status) from error
            if status == 503:
                raise APIError("服务器数据库暂不可用（HTTP 503）", status) from error
            raise APIError("接口返回 HTTP %d" % status, status) from error
        except urllib.error.URLError as error:
            reason = getattr(error, "reason", error)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                raise APIError("网络请求超时，请检查网络") from error
            raise APIError("网络请求失败：%s" % reason) from error
        except (socket.timeout, TimeoutError) as error:
            # Python 3.9 的读超时是 socket.timeout（OSError 子类），不是 TimeoutError
            raise APIError("网络请求超时，请检查网络") from error
        except OSError as error:
            raise APIError("网络请求失败：%s" % error) from error

        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise APIError("接口返回的不是合法 JSON") from error

    # --------------------------------------------------------------- 官方接口

    def fetch_account_balance(self, key: str) -> AccountBalance | None:
        try:
            payload = self._get_json("/v1/account/balance", key)
        except APIError:
            return None
        return parse_account_balance(payload)

    def fetch_spending(self, key: str, start: date, end: date) -> SpendingReport | None:
        try:
            payload = self._get_json(
                "/v1/account/spending",
                key,
                {"from": start.isoformat(), "to": end.isoformat()},
            )
        except APIError:
            return None
        return parse_spending(payload)

    def fetch_legacy_balance(self, key: str) -> AccountBalance | None:
        try:
            payload = self._get_json("/v1/balance", key)
        except APIError:
            return None
        return parse_account_balance(payload)

    # ------------------------------------------------------------- 流水页

    def fetch_usage_page(self, key: str, offset: int, limit: int = 200) -> UsagePage:
        payload = self._get_json(
            "/v1/usage",
            key,
            {"limit": str(limit), "offset": str(offset), "status": "billed"},
        )
        return parse_usage_page(payload)

    def fetch_usage_digest(
        self, key: str, pages: int = 2, account_user_id: int | None = None
    ) -> tuple[dict[str, int], int | None] | None:
        """最近 1~2 页：模型分布 + 累计请求数；失败返回 None，不影响主数据。

        account_user_id 已知时过滤掉其他账户的流水（管理员 Key 会带回多账户记录）；
        total 是接口全站口径，无法按账户过滤，保持原值。
        """
        models: dict[str, int] = {}
        total: int | None = None
        offset = 0
        limit = 200
        for page_index in range(max(1, pages)):
            try:
                page = self.fetch_usage_page(key, offset, limit)
            except APIError:
                return None if page_index == 0 else (models, total)
            if page_index == 0:
                total = page.total
            for item in page.items:
                if account_user_id is not None and item.user_id is not None and item.user_id != account_user_id:
                    continue
                if item.model:
                    models[item.model] = models.get(item.model, 0) + 1
            if len(page.items) < limit:
                break
            offset += limit
        return models, total

    # ---------------------------------------------------------------- 汇总

    def load_stats(self, key: str) -> Stats:
        if not key:
            raise APIError("还没有填写 API Key")
        try:
            stats = self._load_from_account(key)
            if stats is not None:
                return stats
            return self._load_from_usage(key)
        except APIError:
            raise
        except Exception as error:  # 兜底：任何解析/网络异常都要变成可展示的中文错误
            raise APIError("刷新失败：%s" % error) from error

    def _load_from_account(self, key: str) -> Stats | None:
        today = server_today()
        week_start = today - timedelta(days=6)

        spending = self.fetch_spending(key, week_start, today)
        if spending is None:
            return None
        # 账户接口正常但 days 缺失时，柱状图/今日会全 0 与 totals 矛盾，回退 usage 路径。
        if not spending.days and (spending.charged > 0 or spending.request_count > 0):
            return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            account_future = pool.submit(self.fetch_account_balance, key)
            digest_future = pool.submit(self.fetch_usage_digest, key, 2, spending.user_id)
            account = account_future.result()
            digest = digest_future.result()

        fallback_balance = account.balance if account else None
        if fallback_balance is None:
            legacy = self.fetch_legacy_balance(key)
            fallback_balance = legacy.balance if legacy else None
        balance = spending.balance if spending.balance is not None else fallback_balance
        if balance is None:
            return None

        stats = Stats(updated_at=datetime.now())
        stats.data_source = "account"
        stats.balance_from_api = True
        stats.balance = balance
        stats.account_user_id = spending.user_id if spending.user_id is not None else (account.user_id if account else None)
        stats.account_inactive = account.is_active is False if account else False
        stats.week_spend = spending.charged
        stats.week_requests = spending.request_count
        stats.week_recharged = spending.recharged
        stats.week_tokens = spending.totals_tokens
        if digest is not None:
            models, total = digest
            stats.total_requests = total
            stats.top_models = sorted(models.items(), key=lambda pair: (-pair[1], pair[0]))[:3]

        # 正常接口每天只有一行；万一出现重复日期，按天累加，保证与 totals 口径一致。
        day_map: dict[date, DayStat] = {}
        for day in spending.days:
            existing = day_map.get(day.date)
            if existing is None:
                day_map[day.date] = DayStat(date=day.date, spend=day.spend, requests=day.requests)
            else:
                existing.spend += day.spend
                existing.requests += day.requests

        stats.daily = []
        for index in range(7):
            day = week_start + timedelta(days=index)
            source = day_map.get(day)
            stats.daily.append(
                DayStat(date=day, spend=source.spend if source else 0.0, requests=source.requests if source else 0)
            )
        today_stat = day_map.get(today)
        stats.today_spend = today_stat.spend if today_stat else 0.0
        stats.today_requests = today_stat.requests if today_stat else 0
        return stats

    def _load_from_usage(self, key: str) -> Stats:
        today = server_today()
        week_start = today - timedelta(days=6)
        legacy = self.fetch_legacy_balance(key)
        account_user_id = legacy.user_id if legacy else None

        day_map: dict[date, DayStat] = {}
        for index in range(7):
            day = week_start + timedelta(days=index)
            day_map[day] = DayStat(date=day)

        stats = Stats(updated_at=datetime.now())
        stats.data_source = "usage"
        stats.account_user_id = account_user_id
        model_counts: dict[str, int] = {}
        offset = 0
        limit = 200
        max_pages = 25
        page_index = 0
        reached_older = False
        latest_balance: float | None = None
        latest_balance_at: str | None = None
        seen_user_ids: set[int] = set()
        saw_other_account = False

        while not reached_older and page_index < max_pages:
            page = self.fetch_usage_page(key, offset, limit)
            if page_index == 0:
                stats.total_requests = page.total
            if page_index == 0 and account_user_id is None:
                # /v1/balance 线上 404 时用第一页第一条的 user_id 作为过滤基准，
                # 避免管理员 Key 的流水被多账户混算。
                for item in page.items:
                    if item.user_id is not None:
                        account_user_id = item.user_id
                        stats.account_user_id = account_user_id
                        break
            if not page.items:
                break

            for item in page.items:
                if item.user_id is not None:
                    seen_user_ids.add(item.user_id)
                    if account_user_id is not None and item.user_id != account_user_id:
                        saw_other_account = True
                        continue

                created = parse_api_datetime(item.created_at)
                if created is None:
                    continue
                if latest_balance is None:
                    latest_balance = item.balance_cny
                    latest_balance_at = item.created_at
                if created.date() < week_start:
                    reached_older = True
                    continue
                day = created.date()
                charged = item.charged_cny or 0.0
                if day in day_map:
                    day_map[day].spend += charged
                    day_map[day].requests += 1
                stats.week_spend += charged
                stats.week_requests += 1
                stats.week_tokens += (
                    item.input_tokens + item.output_tokens + item.cache_read_tokens + item.cache_write_tokens
                )
                if item.model:
                    model_counts[item.model] = model_counts.get(item.model, 0) + 1

            page_index += 1
            offset += limit
            if len(page.items) < limit:
                break

        if not reached_older and page_index >= max_pages:
            stats.partial = True

        if account_user_id is not None:
            stats.multiple_accounts = saw_other_account
        elif len(seen_user_ids) > 1:
            stats.multiple_accounts = True
        if stats.multiple_accounts:
            stats.total_requests = None

        if legacy is not None:
            stats.balance = legacy.balance
            stats.balance_from_api = True
        elif latest_balance is not None:
            stats.balance = latest_balance
            stats.balance_at = latest_balance_at

        if stats.balance is None:
            raise APIError("没有找到已计费用量记录")

        stats.today_spend = day_map[today].spend
        stats.today_requests = day_map[today].requests
        stats.daily = [day_map[week_start + timedelta(days=index)] for index in range(7)]
        stats.top_models = sorted(model_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:3]
        return stats
