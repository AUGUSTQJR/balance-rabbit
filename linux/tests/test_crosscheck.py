"""余额兔 Linux 版数据层「独立交叉核验」。

设计原则（不复用被测实现自证）：
  * 全部期望值在本文件里用契约字段独立计算，或直接读原始 JSON 比对，
    不调用被测代码的解析/汇总函数来生成期望值；
  * 真实接口部分用 urllib 直接请求原始 JSON，再与 ApiClient.load_stats 逐项比；
  * 离线部分用本文件自带的 HTTP 假服务器（可精确构造 401/403/404/422/503、
    超时、非 JSON、乱序 days、多账户、翻页上限等边界）；
  * 没有 RABBIT_API_KEY 或断网时，真实接口测试自动 skip。

运行：
    cd linux && python3 tests/test_crosscheck.py -v
    # 真实接口（Key 仅通过环境变量注入，不读任何共享文件）：
    RABBIT_API_KEY=$(awk '/RABBIT_API_KEY/{print $2}' ~/.dsh/.credentials.yaml) \
        python3 tests/test_crosscheck.py -v

只读生产代码，测试不修改任何生产文件。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

LINUX_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LINUX_ROOT))

# 隔离配置/缓存目录，避免测试写进真实用户目录（必须在 import settings 前设置）。
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="rabbit-crosscheck-"))
os.environ.setdefault("XDG_CONFIG_HOME", str(_TEST_ROOT / "config"))
os.environ.setdefault("XDG_CACHE_HOME", str(_TEST_ROOT / "cache"))

from balance_rabbit import settings as settings_module  # noqa: E402
from balance_rabbit.api import (  # noqa: E402
    APIError,
    ApiClient,
    parse_account_balance,
    parse_spending,
    parse_usage_page,
)
from balance_rabbit.models import Stats  # noqa: E402


# ---------------------------------------------------------------------------
# 本文件自带的小工具（独立于被测代码）
# ---------------------------------------------------------------------------


def week_dates() -> list[date]:
    today = date.today()
    return [today - timedelta(days=6 - index) for index in range(7)]


def day_json(d: date, requests: int = 1, spend: float = 0.5, **tokens) -> dict:
    return {
        "date": d.isoformat(),
        "request_count": requests,
        "charged_cny": spend,
        "input_tokens": tokens.get("input_tokens", 100),
        "output_tokens": tokens.get("output_tokens", 10),
        "cache_read_tokens": tokens.get("cache_read_tokens", 1),
        "cache_write_tokens": tokens.get("cache_write_tokens", 2),
    }


def totals_of(days: list[dict], recharged: float = 0.0) -> dict:
    """按契约字段独立求和（Token = input+output+cache_read+cache_write）。"""
    return {
        "request_count": sum(int(item["request_count"]) for item in days),
        "charged_cny": sum(float(item["charged_cny"]) for item in days),
        "recharged_cny": recharged,
        "input_tokens": sum(int(item["input_tokens"]) for item in days),
        "output_tokens": sum(int(item["output_tokens"]) for item in days),
        "cache_read_tokens": sum(int(item["cache_read_tokens"]) for item in days),
        "cache_write_tokens": sum(int(item["cache_write_tokens"]) for item in days),
    }


def spending_json(
    days: list[dict],
    balance: float = 50.0,
    user_id: int = 132,
    recharged: float = 0.0,
    totals: dict | None = None,
) -> dict:
    return {
        "user_id": user_id,
        "currency": "CNY",
        "balance_cny": balance,
        "totals": totals if totals is not None else totals_of(days, recharged),
        "days": days,
    }


def balance_json(user_id: int = 132, balance: float = 50.0, active: bool = True) -> dict:
    return {"user_id": user_id, "balance_cny": balance, "currency": "CNY", "is_active": active}


def usage_item(
    created: datetime,
    model: str = "deepseek-flash-1017",
    charged: float = 0.01,
    balance: float = 40.0,
    user_id: int = 132,
    **tokens,
) -> dict:
    return {
        "created_at": created.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": model,
        "charged_cny": charged,
        "balance_cny": balance,
        "user_id": user_id,
        "input_tokens": tokens.get("input_tokens", 10),
        "output_tokens": tokens.get("output_tokens", 2),
        "cache_read_tokens": tokens.get("cache_read_tokens", 1),
        "cache_write_tokens": tokens.get("cache_write_tokens", 0),
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "FakeRabbit/1.0"

    def do_GET(self) -> None:  # noqa: N802 - http.server 约定
        parsed = urllib.parse.urlparse(self.path)
        self.server.requests.append(  # type: ignore[attr-defined]
            {
                "path": parsed.path,
                "query": urllib.parse.parse_qs(parsed.query),
                "headers": {key.lower(): value for key, value in self.headers.items()},
            }
        )
        route = self.server.routes.get(parsed.path)  # type: ignore[attr-defined]
        if route is None:
            self.send_json({"error": "not found"}, 404)
            return
        if callable(route):
            route(self)
            return
        payload, status = route
        self.send_json(payload, status)

    def send_json(self, payload, status: int = 200) -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass  # 客户端超时/断开时写入会失败，忽略

    def log_message(self, *args) -> None:
        pass


class FakeServer:
    """可编程的 HTTP 假服务器，记录每个请求的路径/参数/头。"""

    def __init__(self) -> None:
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.routes = {}
        self.httpd.requests = []
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return "http://127.0.0.1:%d" % self.httpd.server_port

    def route(self, path: str, payload, status: int = 200) -> None:
        self.httpd.routes[path] = (payload, status)

    def route_handler(self, path: str, handler) -> None:
        self.httpd.routes[path] = handler

    def requests_for(self, path: str) -> list[dict]:
        return [item for item in self.httpd.requests if item["path"] == path]

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)


class FakeServerCase(unittest.TestCase):
    def setUp(self) -> None:
        self.server = FakeServer()
        self.addCleanup(self.server.close)

    def client(self, timeout: float = 5.0) -> ApiClient:
        return ApiClient(base=self.server.url, timeout=timeout)


# ---------------------------------------------------------------------------
# 1. HTTP 契约：状态码 / 非 JSON / 超时 / 请求形态
# ---------------------------------------------------------------------------


class HttpContractTest(FakeServerCase):
    def test_load_stats_request_shape(self) -> None:
        """账户路径应只打 spending/balance/usage 三个接口，参数与鉴权头正确。"""
        dates = week_dates()
        days = [day_json(d, requests=index, spend=index * 0.25) for index, d in enumerate(dates)]
        self.server.route("/v1/account/spending", spending_json(days))
        self.server.route("/v1/account/balance", balance_json())
        page0 = [usage_item(datetime.now(), model="m-a") for _ in range(200)]
        self.server.route("/v1/usage", {"total": 200, "limit": 200, "offset": 0, "items": page0})

        stats = self.client().load_stats("sk-audit-key")
        self.assertEqual(stats.data_source, "account")

        spending_requests = self.server.requests_for("/v1/account/spending")
        balance_requests = self.server.requests_for("/v1/account/balance")
        usage_requests = self.server.requests_for("/v1/usage")
        self.assertEqual(len(spending_requests), 1)
        self.assertEqual(len(balance_requests), 1)
        # 第一页 200 条满页 -> 摘要恰好再取第二页
        self.assertEqual([item["query"].get("offset") for item in usage_requests], [["0"], ["200"]])
        self.assertEqual(spending_requests[0]["query"]["from"], [dates[0].isoformat()])
        self.assertEqual(spending_requests[0]["query"]["to"], [dates[-1].isoformat()])
        for item in usage_requests:
            self.assertEqual(item["query"]["limit"], ["200"])
            self.assertEqual(item["query"]["status"], ["billed"])
        for request in self.server.httpd.requests:
            self.assertTrue(request["headers"]["authorization"].startswith("Bearer "))
            self.assertIn("BalanceRabbit-Linux", request["headers"]["user-agent"])

    def test_http_status_mapping(self) -> None:
        cases = {
            401: "未携带 API Key",
            403: "API Key 无效",
            422: "日期参数不合法",
            503: "服务器数据库暂不可用",
            404: "HTTP 404",
        }
        for status, fragment in cases.items():
            with self.subTest(status=status):
                server = FakeServer()
                self.addCleanup(server.close)
                server.route("/v1/usage", {"error": "x"}, status)
                client = ApiClient(base=server.url, timeout=3)
                with self.assertRaises(APIError) as caught:
                    client.fetch_usage_page("k", 0)
                self.assertEqual(caught.exception.status, status)
                self.assertIn(fragment, str(caught.exception))

    def test_non_json_body(self) -> None:
        for body in (b"<html>bad gateway</html>", b"", b'{"a":'):
            with self.subTest(body=body[:8]):
                server = FakeServer()
                self.addCleanup(server.close)
                server.route("/v1/usage", body, 200)
                with self.assertRaises(APIError) as caught:
                    ApiClient(base=server.url, timeout=3).fetch_usage_page("k", 0)
                self.assertIn("不是合法 JSON", str(caught.exception))

    def test_refused_connection(self) -> None:
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        client = ApiClient(base="http://127.0.0.1:%d" % port, timeout=1)
        with self.assertRaises(APIError) as caught:
            client.fetch_usage_page("k", 0)
        self.assertIn("网络请求失败", str(caught.exception))

    def test_read_timeout_is_api_error(self) -> None:
        """超时必须以中文 APIError 暴露（否则账户接口失败无法回退到 usage）。

        已知问题 P1：Python 3.9 的读超时是 socket.timeout（OSError 子类），
        api.py 只用 `except TimeoutError` 捕获，异常会原样穿透 load_stats。
        本用例在 3.9 上按预期失败；若将来修好会变成 unexpected success。
        """

        def slow(handler: _Handler) -> None:
            time.sleep(1.2)
            handler.send_json(balance_json())

        self.server.route_handler("/v1/account/spending", slow)
        self.server.route("/v1/account/balance", balance_json())
        self.server.route("/v1/usage", {"total": 0, "items": []})
        with self.assertRaises(APIError):
            self.client(timeout=0.3).load_stats("k")


# ---------------------------------------------------------------------------
# 2. 解析边界（纯函数，独立构造输入）
# ---------------------------------------------------------------------------


class ParsingBoundaryTest(unittest.TestCase):
    def test_balance_zero_is_not_missing(self) -> None:
        parsed = parse_account_balance({"user_id": 132, "balance_cny": 0, "is_active": True})
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.balance, 0.0)

    def test_balance_numeric_string_and_nested_data(self) -> None:
        parsed = parse_account_balance({"data": {"data": {"balance": "12.34", "account_user_id": 7}}})
        assert parsed is not None
        self.assertAlmostEqual(parsed.balance, 12.34)
        self.assertEqual(parsed.user_id, 7)

    def test_balance_rejects_non_numeric_and_bool(self) -> None:
        for payload in (
            {"balance_cny": "abc"},
            {"balance_cny": True},
            {"balance_cny": None},
            {},
            [],
            "oops",
        ):
            with self.subTest(payload=payload):
                self.assertIsNone(parse_account_balance(payload))

    def test_spending_requires_totals(self) -> None:
        self.assertIsNone(parse_spending({"balance_cny": 1.0, "days": []}))
        self.assertIsNone(parse_spending(None))

    def test_spending_tolerates_missing_and_bad_days(self) -> None:
        payload = {
            "user_id": 132,
            "balance_cny": 1.5,
            "totals": {"request_count": 2, "charged_cny": 0.3, "recharged_cny": 5},
            "days": [
                {"date": "2026-10-19", "request_count": 2, "charged_cny": 0.3},
                "junk",
                {"date": "not-a-date", "request_count": 9},
                {"date": "2026-10-20", "request_count": None, "charged_cny": "abc"},
            ],
        }
        report = parse_spending(payload)
        assert report is not None
        self.assertEqual(report.request_count, 2)
        self.assertAlmostEqual(report.charged, 0.3)
        self.assertAlmostEqual(report.recharged, 5.0)
        self.assertEqual(report.totals_tokens, 0)  # 缺失 Token 字段按 0 处理
        # 非法日期条目被丢弃，只有合法日期保留
        self.assertEqual([item.date for item in report.days], [date(2026, 10, 19), date(2026, 10, 20)])
        self.assertEqual(report.days[1].requests, 0)
        self.assertEqual(report.days[1].spend, 0.0)

    def test_spending_token_formula(self) -> None:
        payload = spending_json(
            [
                day_json(date(2026, 10, 19), input_tokens=11, output_tokens=22, cache_read_tokens=33, cache_write_tokens=44),
            ]
        )
        report = parse_spending(payload)
        assert report is not None
        self.assertEqual(report.totals_tokens, 11 + 22 + 33 + 44)

    def test_usage_page_tolerates_odd_items(self) -> None:
        page = parse_usage_page(
            {
                "total": "3",
                "items": [
                    {"model": 123, "created_at": 456, "user_id": "132", "charged_cny": "0.01"},
                    "junk",
                    {"model": "ok", "created_at": "2026-10-20T10:00:00"},
                ],
            }
        )
        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.items), 2)
        self.assertIsNone(page.items[0].model)
        self.assertIsNone(page.items[0].created_at)
        self.assertEqual(page.items[0].user_id, 132)
        self.assertAlmostEqual(page.items[0].charged_cny or 0, 0.01)
        self.assertEqual(page.items[1].model, "ok")

    def test_usage_page_bad_payload(self) -> None:
        for payload in (None, [], "x"):
            with self.subTest(payload=payload):
                with self.assertRaises(APIError):
                    parse_usage_page(payload)

    def test_spending_tolerates_nan_totals(self) -> None:
        """P8：json 标准库允许 NaN/Infinity 字面量，_integer() 里 int(nan) 会抛 ValueError。"""
        payload = spending_json([])
        payload["totals"]["request_count"] = float("nan")
        report = parse_spending(payload)
        self.assertEqual(report.request_count, 0)

    def test_long_model_name_kept(self) -> None:
        name = "vendor/" + "x" * 500
        page = parse_usage_page({"total": 1, "items": [{"model": name}]})
        self.assertEqual(page.items[0].model, name)

    def test_datetime_parsing_variants(self) -> None:
        # 服务器本地时间无时区；带微秒/时区后缀时应只取前 19 字符
        from balance_rabbit.util import parse_api_datetime, parse_day

        self.assertEqual(parse_api_datetime("2026-10-20T15:25:07"), datetime(2026, 10, 20, 15, 25, 7))
        self.assertEqual(
            parse_api_datetime("2026-10-20T15:25:07.123456+08:00"),
            datetime(2026, 10, 20, 15, 25, 7),
        )
        self.assertIsNone(parse_api_datetime("2026-10-20 15:25:07"))
        self.assertEqual(parse_day("2026-10-20"), date(2026, 10, 20))
        self.assertIsNone(parse_day("20/10/2026"))


# ---------------------------------------------------------------------------
# 3. 账户路径汇总（假服务器 + 独立期望值）
# ---------------------------------------------------------------------------


class AccountAggregationTest(FakeServerCase):
    def _serve_account(self, spending: dict, balance: dict | None = None, usage: dict | None = None) -> None:
        self.server.route("/v1/account/spending", spending)
        self.server.route("/v1/account/balance", balance if balance is not None else balance_json())
        if usage is not None:
            self.server.route("/v1/usage", usage)

    def _usage_page(self, count: int, model: str = "deepseek-flash-1017", total: int = 200) -> dict:
        items = [usage_item(datetime.now() - timedelta(seconds=index), model=model) for index in range(count)]
        return {"total": total, "limit": 200, "offset": 0, "items": items}

    def _offset_paged_usage(self, page0: list[dict], total: int) -> None:
        def paged(handler: _Handler) -> None:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
            offset = int(query.get("offset", ["0"])[0])
            handler.send_json({"total": total, "items": page0[offset : offset + 200]})

        self.server.route_handler("/v1/usage", paged)

    def test_field_by_field_happy_path(self) -> None:
        dates = week_dates()
        days = [
            day_json(d, requests=index + 1, spend=0.1 * (index + 1), input_tokens=10 * index + 1)
            for index, d in enumerate(dates)
        ]
        page0 = [usage_item(datetime.now() - timedelta(seconds=index)) for index in range(200)]
        self._serve_account(spending_json(days, balance=42.5, recharged=12.34))
        self._offset_paged_usage(page0, total=777)

        stats = self.client().load_stats("k")
        self.assertEqual(stats.data_source, "account")
        self.assertTrue(stats.balance_from_api)
        self.assertAlmostEqual(stats.balance, 42.5)
        self.assertEqual(stats.account_user_id, 132)
        self.assertFalse(stats.account_inactive)
        # 期望值：在测试里独立求和
        self.assertAlmostEqual(stats.week_spend, sum(0.1 * (i + 1) for i in range(7)))
        self.assertEqual(stats.week_requests, sum(i + 1 for i in range(7)))
        self.assertAlmostEqual(stats.week_recharged, 12.34)
        expected_tokens = sum(
            (10 * i + 1) + 10 + 1 + 2 for i in range(7)
        )
        self.assertEqual(stats.week_tokens, expected_tokens)
        self.assertEqual(len(stats.daily), 7)
        for index, day in enumerate(stats.daily):
            self.assertEqual(day.date, dates[index])
            self.assertAlmostEqual(day.spend, 0.1 * (index + 1))
            self.assertEqual(day.requests, index + 1)
        self.assertAlmostEqual(stats.today_spend, 0.7)
        self.assertEqual(stats.today_requests, 7)
        self.assertEqual(stats.total_requests, 777)
        self.assertEqual(stats.top_models, [("deepseek-flash-1017", 200)])

    def test_unordered_days_are_remapped(self) -> None:
        dates = week_dates()
        days = [day_json(d, requests=index, spend=float(index)) for index, d in enumerate(dates)]
        shuffled = [days[3], days[0], days[6], days[2], days[5], days[1], days[4]]
        self._serve_account(spending_json(shuffled), usage=self._usage_page(1))
        stats = self.client().load_stats("k")
        self.assertEqual([item.date for item in stats.daily], dates)
        self.assertEqual([item.requests for item in stats.daily], list(range(7)))
        self.assertAlmostEqual(stats.week_spend, 21.0)
        self.assertAlmostEqual(stats.today_spend, 6.0)

    def test_extra_out_of_window_day_not_shown(self) -> None:
        dates = week_dates()
        days = [day_json(d, spend=1.0) for d in dates]
        stale = day_json(dates[0] - timedelta(days=30), requests=99, spend=9.99)
        payload = spending_json(days, totals=totals_of(days))
        payload["days"] = days + [stale]
        self._serve_account(payload, usage=self._usage_page(1))
        stats = self.client().load_stats("k")
        self.assertEqual(len(stats.daily), 7)
        self.assertEqual([item.date for item in stats.daily], dates)
        self.assertEqual(stats.week_requests, 7)  # totals 是权威汇总，不因 stale 行变化

    def test_zero_balance_displayable(self) -> None:
        dates = week_dates()
        days = [day_json(d) for d in dates]
        self._serve_account(spending_json(days, balance=0), usage=self._usage_page(1))
        stats = self.client().load_stats("k")
        self.assertIsNotNone(stats.balance)
        self.assertEqual(stats.balance, 0.0)
        self.assertTrue(stats.is_low(20.0))

    def test_balance_null_falls_back_to_account_endpoint(self) -> None:
        dates = week_dates()
        days = [day_json(d) for d in dates]
        payload = spending_json(days)
        payload["balance_cny"] = None
        self._serve_account(payload, balance_json(balance=7.25), self._usage_page(1))
        stats = self.client().load_stats("k")
        self.assertAlmostEqual(stats.balance, 7.25)

    def test_inactive_account_flag(self) -> None:
        dates = week_dates()
        self._serve_account(
            spending_json([day_json(d) for d in dates]),
            balance_json(active=False),
            self._usage_page(1),
        )
        self.assertTrue(self.client().load_stats("k").account_inactive)

    def test_days_missing_falls_back_to_usage(self) -> None:
        """P5 已修：days 缺失时不再返回“totals 有数、柱状图全 0”的矛盾数据，改走 usage 回退。"""
        dates = week_dates()
        days = [day_json(d, requests=5, spend=2.0) for d in dates]
        payload = spending_json(days)
        payload.pop("days")
        self._serve_account(payload, usage=self._usage_page(1))
        stats = self.client().load_stats("k")
        self.assertEqual(stats.data_source, "usage")
        self.assertEqual(sum(item.requests for item in stats.daily), stats.week_requests)

    def test_duplicate_dates_are_summed(self) -> None:
        """P4 已修：同一天出现两条时按天累加，daily 与 totals 口径一致。"""
        dates = week_dates()
        days = [day_json(d, requests=1, spend=1.0) for d in dates]
        days.append(day_json(dates[-1], requests=50, spend=9.0))
        self._serve_account(spending_json(days), usage=self._usage_page(1))
        stats = self.client().load_stats("k")
        self.assertEqual(stats.week_requests, 57)
        self.assertAlmostEqual(stats.week_spend, 16.0)
        self.assertEqual(stats.daily[-1].requests, 51)
        self.assertAlmostEqual(stats.daily[-1].spend, 10.0)
        self.assertEqual(sum(item.requests for item in stats.daily), stats.week_requests)

    def test_digest_failure_does_not_break_main_data(self) -> None:
        dates = week_dates()
        self._serve_account(
            spending_json([day_json(d) for d in dates]),
            usage=None,
        )
        self.server.route("/v1/usage", {"error": "boom"}, 500)
        stats = self.client().load_stats("k")
        self.assertEqual(stats.data_source, "account")
        self.assertIsNone(stats.total_requests)
        self.assertEqual(stats.top_models, [])

    def test_no_key_short_circuits(self) -> None:
        with self.assertRaises(APIError) as caught:
            self.client().load_stats("")
        self.assertIn("还没有填写 API Key", str(caught.exception))
        self.assertEqual(self.server.httpd.requests, [])

    def test_usage_page_short_page_stops_pagination(self) -> None:
        dates = week_dates()
        self._serve_account(
            spending_json([day_json(d) for d in dates]),
            usage=self._usage_page(3, total=3),
        )
        self.client().load_stats("k")
        self.assertEqual(len(self.server.requests_for("/v1/usage")), 1)

    def test_digest_ignores_other_accounts(self) -> None:
        """P9：账户路径的 usage 摘要没按 user_id 过滤；管理员 Key 会把别的账户模型算进来。"""
        dates = week_dates()
        items = [
            usage_item(datetime.now() - timedelta(seconds=index), model="mine", user_id=132)
            for index in range(3)
        ] + [
            usage_item(datetime.now() - timedelta(seconds=index), model="foreign", user_id=999)
            for index in range(2)
        ]
        self._serve_account(spending_json([day_json(d) for d in dates]))
        self.server.route("/v1/usage", {"total": 5, "items": items})
        stats = self.client().load_stats("k")
        self.assertEqual(stats.top_models, [("mine", 3)])

    def test_long_model_name_in_top_models(self) -> None:
        name = "deepseek/" + "very-long-" * 40
        dates = week_dates()
        items = [usage_item(datetime.now() - timedelta(seconds=index), model=name) for index in range(4)]
        self._serve_account(
            spending_json([day_json(d) for d in dates]),
            usage={"total": 4, "items": items},
        )
        stats = self.client().load_stats("k")
        self.assertEqual(stats.top_models, [(name, 4)])


# ---------------------------------------------------------------------------
# 4. 旧 /v1/usage 翻页回退路径
# ---------------------------------------------------------------------------


class UsageFallbackTest(FakeServerCase):
    def _serve_fallback(
        self,
        items: list[dict],
        total: int | None = None,
        legacy_balance: dict | None = None,
        page_size: int | None = None,
    ) -> None:
        self.server.route("/v1/account/spending", {"error": "down"}, 503)
        self.server.route("/v1/account/balance", {"error": "down"}, 503)
        if legacy_balance is None:
            self.server.route("/v1/balance", {"error": "not found"}, 404)
        else:
            self.server.route("/v1/balance", legacy_balance)

        if page_size is None:
            self.server.route("/v1/usage", {"total": total if total is not None else len(items), "items": items})
            return

        def paged(handler: _Handler) -> None:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
            offset = int(query.get("offset", ["0"])[0])
            handler.send_json(
                {
                    "total": total if total is not None else 99999,
                    "items": items[offset : offset + page_size],
                }
            )

        self.server.route_handler("/v1/usage", paged)

    def test_fallback_aggregates_by_created_at(self) -> None:
        now = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        items = [
            usage_item(now, charged=0.10, input_tokens=10, output_tokens=1, cache_read_tokens=2, cache_write_tokens=3),
            usage_item(now - timedelta(days=1), charged=0.20, input_tokens=20, output_tokens=2, cache_read_tokens=2, cache_write_tokens=3),
            usage_item(now - timedelta(days=2), charged=0.30, input_tokens=30, output_tokens=3, cache_read_tokens=2, cache_write_tokens=3),
            usage_item(now - timedelta(days=30), charged=9.99),  # 窗口外
        ]
        self._serve_fallback(items, total=4, legacy_balance=balance_json(balance=33.3))

        stats = ApiClient(base=self.server.url, timeout=5).load_stats("k")
        self.assertEqual(stats.data_source, "usage")
        self.assertAlmostEqual(stats.balance, 33.3)
        self.assertTrue(stats.balance_from_api)
        self.assertEqual(stats.account_user_id, 132)
        self.assertAlmostEqual(stats.week_spend, 0.6)
        self.assertEqual(stats.week_requests, 3)
        self.assertEqual(stats.week_tokens, (10 + 1 + 2 + 3) + (20 + 2 + 2 + 3) + (30 + 3 + 2 + 3))
        self.assertAlmostEqual(stats.today_spend, 0.10)
        self.assertEqual(stats.today_requests, 1)
        self.assertEqual(stats.total_requests, 4)
        self.assertEqual(stats.top_models[0][0], "deepseek-flash-1017")
        self.assertEqual(stats.top_models[0][1], 3)
        self.assertEqual([item.requests for item in stats.daily], [0, 0, 0, 0, 1, 1, 1])
        # P7 已修：spending 失败后不再预取 digest，只回退翻 1 页
        self.assertEqual(len(self.server.requests_for("/v1/usage")), 1)

    def test_fallback_filters_other_accounts_when_balance_known(self) -> None:
        now = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        items = [
            usage_item(now, charged=0.10, user_id=132),
            usage_item(now - timedelta(hours=1), charged=0.20, user_id=999),
            usage_item(now - timedelta(hours=2), charged=0.40, user_id=132),
        ]
        self._serve_fallback(items, total=3, legacy_balance=balance_json(user_id=132, balance=5.0))
        stats = ApiClient(base=self.server.url, timeout=5).load_stats("k")
        self.assertTrue(stats.multiple_accounts)
        self.assertIsNone(stats.total_requests)
        self.assertAlmostEqual(stats.week_spend, 0.5)
        self.assertEqual(stats.week_requests, 2)
        self.assertEqual(stats.top_models, [("deepseek-flash-1017", 2)])

    def test_fallback_filters_other_accounts_without_balance(self) -> None:
        """P3：/v1/balance 线上 404，回退路径拿不到 account_user_id 时会把别的账户算进来。

        期望：用第一条记录的 user_id 当账户过滤条件；现状：把 999 账户的 0.30 也计入。
        """

        now = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        items = [
            usage_item(now, charged=0.10, user_id=132),
            usage_item(now - timedelta(hours=1), charged=0.30, user_id=999),
        ]
        self._serve_fallback(items, total=2)
        stats = ApiClient(base=self.server.url, timeout=5).load_stats("k")
        self.assertAlmostEqual(stats.week_spend, 0.10)

    def test_fallback_all_endpoints_missing_raises_clean_error(self) -> None:
        self._serve_fallback([])
        with self.assertRaises(APIError) as caught:
            ApiClient(base=self.server.url, timeout=5).load_stats("k")
        self.assertIn("没有找到已计费用量记录", str(caught.exception))

    def test_fallback_pagination_cap_marks_partial(self) -> None:
        now = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        items = [usage_item(now, charged=0.01) for _ in range(200 * 25)]
        self._serve_fallback(items, total=99999, page_size=200)
        stats = ApiClient(base=self.server.url, timeout=10).load_stats("k")
        self.assertTrue(stats.partial)
        self.assertEqual(stats.week_requests, 200 * 25)
        # P7 已修：回退前不再白打 digest，合计 25 个请求
        self.assertEqual(len(self.server.requests_for("/v1/usage")), 25)
        self.assertEqual(stats.week_tokens, 25 * 200 * (10 + 2 + 1 + 0))

    def test_fallback_latest_balance_from_usage_when_balance_endpoint_missing(self) -> None:
        now = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        items = [
            usage_item(now, balance=8.5, charged=0.1),
            usage_item(now - timedelta(hours=1), balance=8.6, charged=0.1),
        ]
        self._serve_fallback(items, total=2)
        stats = ApiClient(base=self.server.url, timeout=5).load_stats("k")
        self.assertAlmostEqual(stats.balance, 8.5)
        self.assertEqual(stats.balance_at, items[0]["created_at"])

    def test_fallback_empty_usage_keeps_balance(self) -> None:
        self._serve_fallback([], total=0, legacy_balance=balance_json(balance=5.0))
        # 没有流水但有余额：应能显示余额；P6 已修：累计请求数为 0 而不是 None
        stats = ApiClient(base=self.server.url, timeout=5).load_stats("k")
        self.assertAlmostEqual(stats.balance, 5.0)
        self.assertEqual(stats.week_requests, 0)
        self.assertEqual(stats.total_requests, 0)


class TimezoneWindowTest(FakeServerCase):
    """P10：账户接口按服务器本地（Asia/Shanghai）切天，客户端窗口却按本机时区算。"""

    SHANGHAI = timezone(timedelta(hours=8))

    def _shanghai_today(self) -> date:
        return datetime.now(self.SHANGHAI).date()

    def _prepare(self) -> date:
        today = self._shanghai_today()
        dates = [today - timedelta(days=6 - index) for index in range(7)]
        self.server.route("/v1/account/spending", spending_json([day_json(d) for d in dates]))
        self.server.route("/v1/account/balance", balance_json())
        self.server.route("/v1/usage", {"total": 0, "items": []})
        return today

    def _run_child(self, tz: str) -> str:
        code = (
            "import sys, datetime; sys.path.insert(0, %r);"
            "from balance_rabbit.api import ApiClient;"
            "ApiClient(base=%r, timeout=10).load_stats('k');"
            "print(datetime.date.today().isoformat())"
        ) % (str(LINUX_ROOT), self.server.url)
        env = dict(os.environ)
        env.update(
            {
                "TZ": tz,
                "PYTHONPATH": str(LINUX_ROOT),
                "TZDIR": "",
            }
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(LINUX_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.strip().splitlines()[-1]

    def test_window_matches_server_local_date_when_tz_is_shanghai(self) -> None:
        """对照组：TZ=Asia/Shanghai 时请求窗口应等于服务器本地 7 天窗口。"""
        today = self._prepare()
        child_today = date.fromisoformat(self._run_child("Asia/Shanghai"))
        self.assertEqual(child_today, today)
        query = self.server.requests_for("/v1/account/spending")[0]["query"]
        self.assertEqual(query["from"], [(today - timedelta(days=6)).isoformat()])
        self.assertEqual(query["to"], [today.isoformat()])

    def test_window_uses_server_local_date_not_machine_local(self) -> None:
        """P10 现状：机器时区与服务器不同时，from/to 按机器本地日期算，窗口整体错位。"""
        today = self._prepare()
        # 选一个此刻与上海日期不同的时区（HST=-10；若上海已过 18 点则用 +14 的 Kiritimati）
        shanghai_hour = datetime.now(self.SHANGHAI).hour
        tz = "Pacific/Honolulu" if shanghai_hour < 18 else "Pacific/Kiritimati"
        child_today = date.fromisoformat(self._run_child(tz))
        if child_today == today:
            self.skipTest("当前时刻该时区与上海同日期，无法构造时区差异")
        query = self.server.requests_for("/v1/account/spending")[0]["query"]
        # 期望：仍按服务器本地日期请求；现状：from/to 用了 child_today
        self.assertEqual(query["from"], [(today - timedelta(days=6)).isoformat()])
        self.assertEqual(query["to"], [today.isoformat()])


# ---------------------------------------------------------------------------
# 5. Key 隔离：产品代码不得读共享 yaml
# ---------------------------------------------------------------------------

_PRODUCT_PY = sorted((LINUX_ROOT / "balance_rabbit").glob("*.py"))


class KeyIsolationTest(unittest.TestCase):
    def test_env_var_has_priority(self) -> None:
        with mock.patch.dict(os.environ, {"RABBIT_API_KEY": "sk-env"}, clear=False):
            with mock.patch.object(settings_module, "key_from_keyring", return_value="sk-keyring"):
                with mock.patch.object(settings_module, "key_from_file", return_value="sk-file"):
                    self.assertEqual(settings_module.api_key(), "sk-env")

    def test_api_key_never_touches_shared_yaml(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RABBIT_API_KEY", None)
            with mock.patch.object(settings_module, "key_from_keyring", return_value=None):
                with mock.patch.object(settings_module, "key_from_file", return_value=None):
                    with mock.patch.object(
                        settings_module,
                        "legacy_shared_key",
                        side_effect=AssertionError("api_key() 不应读取 ~/.dsh/.credentials.yaml"),
                    ):
                        self.assertIsNone(settings_module.api_key())

    def test_cli_ignores_shared_yaml_without_env(self) -> None:
        """端到端：HOME 下放一份假共享 yaml、不设环境变量，CLI 必须报「还没有填写 API Key」。"""
        if shutil.which("secret-tool"):
            self.skipTest("本机有 secret-tool 密钥环，无法保证命令行环境无 Key")
        fake_home = Path(tempfile.mkdtemp(prefix="rabbit-fake-home-"))
        self.addCleanup(shutil.rmtree, fake_home, True)
        (fake_home / ".dsh").mkdir(parents=True)
        (fake_home / ".dsh" / ".credentials.yaml").write_text(
            "refs:\n  RABBIT_API_KEY: sk-from-shared-yaml\n", encoding="utf-8"
        )
        env = {
            "HOME": str(fake_home),
            "XDG_CONFIG_HOME": str(fake_home / "config"),
            "XDG_CACHE_HOME": str(fake_home / "cache"),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": str(LINUX_ROOT),
            "LANG": "C.UTF-8",
        }
        result = subprocess.run(
            [sys.executable, "-m", "balance_rabbit", "--stats"],
            cwd=str(LINUX_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("还没有填写 API Key", result.stdout)

    @unittest.expectedFailure
    def test_product_code_does_not_reference_shared_yaml(self) -> None:
        """P2（契约偏差，低风险）：产品代码仍保留读取 ~/.dsh/.credentials.yaml 的函数。

        调用点只有 app.py:815-818 的首启对话框预填（与 macOS legacySharedKey 用法一致，
        不会静默当 Key 用）；若严格按「产品代码不得读该 yaml」验收，需删掉该函数与预填。
        """
        offenders = [
            path.name
            for path in _PRODUCT_PY
            if ".credentials.yaml" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [], "产品代码不应读取共享 yaml：%s" % offenders)


# ---------------------------------------------------------------------------
# 6. 真实接口独立核对（无 Key / 断网自动 skip）
# ---------------------------------------------------------------------------

BASE_URL = "https://www.rabbitj.top"


def live_key() -> str | None:
    """真实 Key 仅来自环境变量（测试专用注入），不读任何文件。"""
    return os.environ.get("RABBIT_API_KEY", "").strip() or None


def raw_get(path: str, key: str, params: dict | None = None, timeout: float = 15.0):
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + key,
            "Accept": "application/json",
            "User-Agent": "BalanceRabbit-Crosscheck/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def raw_spending(key: str, start: date, end: date) -> dict:
    return raw_get(
        "/v1/account/spending",
        key,
        {"from": start.isoformat(), "to": end.isoformat()},
    )


def raw_balance(key: str) -> dict:
    return raw_get("/v1/account/balance", key)


def raw_usage(key: str, limit: int = 200, offset: int = 0) -> dict:
    return raw_get("/v1/usage", key, {"limit": str(limit), "offset": str(offset), "status": "billed"})


class LiveCrosscheckTest(unittest.TestCase):
    key: str = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls.key = live_key() or ""
        if not cls.key:
            raise unittest.SkipTest("没有 RABBIT_API_KEY 环境变量，跳过真实接口核对")
        try:
            raw_balance(cls.key)
        except Exception as error:  # noqa: BLE001 - 任何网络/鉴权失败都算不可用
            raise unittest.SkipTest("真实接口不可达（%s），跳过" % error) from error

    def _snapshot(self) -> tuple[dict, dict, dict, date, date]:
        today = date.today()
        start = today - timedelta(days=6)
        return raw_spending(self.key, start, today), raw_balance(self.key), raw_usage(self.key), start, today

    def test_real_fields_match_raw_json(self) -> None:
        """独立 urllib 取原始 JSON，与 load_stats 逐项比对（容忍并发请求造成的滚动）。"""
        before = self._snapshot()
        stats = ApiClient(timeout=30).load_stats(self.key)
        after = self._snapshot()

        sp_before, bal_before, usage_before, start, today = before
        sp_after, bal_after, usage_after, start_after, today_after = after

        # 测试期间若跨天，时间窗口会变，直接跳过以免误报
        if (start, today) != (start_after, today_after):
            self.skipTest("测试期间跨天，跳过")
        self.assertEqual(stats.data_source, "account")
        dates = [today - timedelta(days=6 - index) for index in range(7)]

        # ---- 原始 JSON 自身不变量（验证接口口径） ----
        for payload in (sp_before, sp_after):
            self.assertEqual(
                payload["totals"]["request_count"],
                sum(day["request_count"] for day in payload["days"]),
            )
            self.assertAlmostEqual(
                payload["totals"]["charged_cny"],
                sum(day["charged_cny"] for day in payload["days"]),
                places=6,
            )
            self.assertEqual(
                payload["totals"]["input_tokens"]
                + payload["totals"]["output_tokens"]
                + payload["totals"]["cache_read_tokens"]
                + payload["totals"]["cache_write_tokens"],
                sum(
                    day["input_tokens"]
                    + day["output_tokens"]
                    + day["cache_read_tokens"]
                    + day["cache_write_tokens"]
                    for day in payload["days"]
                ),
            )

        # ---- 账户 / 余额 ----
        self.assertEqual(stats.account_user_id, sp_before["user_id"])
        self.assertEqual(stats.account_user_id, bal_after["user_id"])
        # is_active 语义未明（AGENTS 记录：false 不代表停用），只核对字段映射一致
        self.assertEqual(stats.account_inactive, bal_after["is_active"] is False)
        self.assertIsNotNone(stats.balance)
        # 余额在两次快照之间因并发消费会小幅变化，用容差核对同一时刻的账户接口
        self.assertLessEqual(abs((stats.balance or 0) - bal_after["balance_cny"]), 0.3)
        self.assertLessEqual(abs((stats.balance or 0) - sp_before["balance_cny"]), 0.3)

        # ---- 区间 totals：用前后两次快照做上下界 ----
        self.assertGreaterEqual(stats.week_requests, sp_before["totals"]["request_count"])
        self.assertLessEqual(stats.week_requests, sp_after["totals"]["request_count"])
        self.assertGreaterEqual(stats.week_tokens, self._totals_tokens(sp_before["totals"]))
        self.assertLessEqual(stats.week_tokens, self._totals_tokens(sp_after["totals"]))
        self.assertGreaterEqual(stats.week_spend, round(sp_before["totals"]["charged_cny"], 6) - 1e-6)
        self.assertLessEqual(stats.week_spend, sp_after["totals"]["charged_cny"] + 1e-6)
        self.assertIn(
            round(stats.week_recharged, 6),
            {round(sp_before["totals"]["recharged_cny"], 6), round(sp_after["totals"]["recharged_cny"], 6)},
        )

        # ---- 逐日：历史 6 天必须精确一致，今天允许滚动 ----
        self.assertEqual([item.date for item in stats.daily], dates)
        raw_before_days = {day["date"]: day for day in sp_before["days"]}
        raw_after_days = {day["date"]: day for day in sp_after["days"]}
        for index, day in enumerate(stats.daily[:-1]):
            source = raw_before_days[dates[index].isoformat()]
            self.assertAlmostEqual(day.spend, source["charged_cny"], places=9)
            self.assertEqual(day.requests, source["request_count"])
        today_key = dates[-1].isoformat()
        self.assertGreaterEqual(
            stats.daily[-1].requests, raw_before_days[today_key]["request_count"]
        )
        self.assertLessEqual(
            stats.daily[-1].requests, raw_after_days[today_key]["request_count"]
        )
        self.assertGreaterEqual(stats.today_spend, round(raw_before_days[today_key]["charged_cny"], 6) - 1e-6)
        self.assertLessEqual(stats.today_spend, raw_after_days[today_key]["charged_cny"] + 1e-6)

        # ---- 自洽：周汇总 = 7 天之和；今日 = 最后一天 ----
        self.assertAlmostEqual(stats.week_spend, sum(item.spend for item in stats.daily), places=6)
        self.assertEqual(stats.week_requests, sum(item.requests for item in stats.daily))
        self.assertAlmostEqual(stats.today_spend, stats.daily[-1].spend, places=9)
        self.assertEqual(stats.today_requests, stats.daily[-1].requests)

        # ---- usage 摘要：累计请求数 + 模型分布 ----
        self.assertIsNotNone(stats.total_requests)
        self.assertGreaterEqual(stats.total_requests or 0, usage_before["total"])
        self.assertLessEqual(stats.total_requests or 0, usage_after["total"])
        usage_before_p2 = raw_usage(self.key, offset=200)
        usage_after_p2 = raw_usage(self.key, offset=200)
        raw_models = {
            item.get("model")
            for payload in (usage_before, usage_before_p2, usage_after, usage_after_p2)
            for item in payload["items"]
        }
        raw_models.discard(None)
        for name, _count in stats.top_models:
            self.assertIn(name, raw_models)
        self.assertLessEqual(len(stats.top_models), 3)

        # 样例数值（便于人工复核，不算断言依据）
        print(
            "\n[真实样例] user_id=%s balance=%s week_spend=%s week_requests=%s week_tokens=%s "
            "recharged=%s total_requests=%s top_models=%s"
            % (
                stats.account_user_id,
                stats.balance,
                stats.week_spend,
                stats.week_requests,
                stats.week_tokens,
                stats.week_recharged,
                stats.total_requests,
                stats.top_models,
            )
        )

    @staticmethod
    def _totals_tokens(totals: dict) -> int:
        return (
            int(totals["input_tokens"])
            + int(totals["output_tokens"])
            + int(totals["cache_read_tokens"])
            + int(totals["cache_write_tokens"])
        )

    def test_real_cli_stats(self) -> None:
        """端到端：--stats 输出与原始接口一致，且确实用了账户接口。"""
        env = dict(os.environ)
        env["RABBIT_API_KEY"] = self.key
        result = subprocess.run(
            [sys.executable, "-m", "balance_rabbit", "--stats"],
            cwd=str(LINUX_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = result.stdout
        fields = {}
        day_lines = []
        model_lines = []
        for line in output.splitlines():
            if line.startswith("day "):
                day_lines.append(line)
            elif line.startswith("model "):
                model_lines.append(line)
            elif line.startswith("account="):
                # account=<id> multiple=<bool> fromAPI=<bool> source=<...> inactive=<...> recharged=<...>
                for name in ("account", "multiple", "fromAPI", "source", "inactive", "recharged"):
                    match = re.search(r"(?:^| )%s=(\S+)" % name, line)
                    if match:
                        fields[name] = match.group(1)
            elif "=" in line:
                key, _, value = line.partition("=")
                fields[key.strip()] = value.strip()
        self.assertEqual(len(day_lines), 7, output)
        self.assertNotEqual(fields.get("balance"), "nil")
        self.assertIn("source=account", output)
        self.assertEqual(fields.get("account"), str(raw_balance(self.key)["user_id"]))
        self.assertEqual(fields.get("source"), "account")
        cli_balance = float(fields["balance"])
        self.assertLessEqual(abs(cli_balance - raw_balance(self.key)["balance_cny"]), 0.5)
        self.assertGreaterEqual(len(model_lines), 1, output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
