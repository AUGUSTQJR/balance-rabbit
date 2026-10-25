"""余额兔 Linux 版数据层测试。

离线部分不依赖网络和 Qt；`LiveApiTest` 会读 RABBIT_API_KEY（或本机仅供测试的
~/.dsh/.credentials.yaml）打真实接口核对余额 / 逐日 / Token。
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from balance_rabbit.api import (  # noqa: E402
    ApiClient,
    parse_account_balance,
    parse_spending,
    parse_usage_page,
)
from balance_rabbit.models import AccountBalance, SpendingDay, SpendingReport, UsageItem, UsagePage  # noqa: E402
from balance_rabbit.util import money2, money_smart, short_date, tokens_text  # noqa: E402


def _today() -> date:
    return date.today()


class FormattingTest(unittest.TestCase):
    def test_money(self) -> None:
        self.assertEqual(money2(88.6), "¥88.60")
        self.assertEqual(money_smart(0), "¥0")
        self.assertEqual(money_smart(0.0032), "¥0.0032")
        self.assertEqual(money_smart(0.4128), "¥0.413")
        self.assertEqual(money_smart(12.5), "¥12.50")

    def test_tokens(self) -> None:
        self.assertEqual(tokens_text(999), "999")
        self.assertEqual(tokens_text(45_213), "4.5 万")
        self.assertEqual(tokens_text(123_456_789), "1.23 亿")

    def test_short_date(self) -> None:
        self.assertEqual(short_date(date(2026, 3, 9)), "3/9")


class ParsingTest(unittest.TestCase):
    def test_account_balance(self) -> None:
        parsed = parse_account_balance({"user_id": 132, "balance_cny": 74.5075, "currency": "CNY", "is_active": True})
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.user_id, 132)
        self.assertAlmostEqual(parsed.balance, 74.5075)
        self.assertTrue(parsed.is_active)

    def test_account_balance_nested(self) -> None:
        parsed = parse_account_balance({"data": {"balance": "12.34", "account_user_id": 7}})
        assert parsed is not None
        self.assertAlmostEqual(parsed.balance, 12.34)
        self.assertEqual(parsed.user_id, 7)

    def test_spending(self) -> None:
        payload = {
            "user_id": 132,
            "balance_cny": 76.6517,
            "totals": {
                "request_count": 9,
                "charged_cny": 0.21,
                "recharged_cny": 50,
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_read_tokens": 3,
                "cache_write_tokens": 4,
            },
            "days": [
                {
                    "date": "2026-10-19",
                    "request_count": 4,
                    "charged_cny": 0.1,
                    "input_tokens": 50,
                    "output_tokens": 10,
                    "cache_read_tokens": 1,
                    "cache_write_tokens": 2,
                },
                {
                    "date": "2026-10-20",
                    "request_count": 5,
                    "charged_cny": 0.11,
                    "input_tokens": 50,
                    "output_tokens": 10,
                    "cache_read_tokens": 2,
                    "cache_write_tokens": 2,
                },
            ],
        }
        report = parse_spending(payload)
        assert report is not None
        self.assertEqual(report.user_id, 132)
        self.assertAlmostEqual(report.balance, 76.6517)
        self.assertEqual(report.request_count, 9)
        self.assertAlmostEqual(report.charged, 0.21)
        self.assertAlmostEqual(report.recharged, 50)
        self.assertEqual(report.totals_tokens, 127)
        self.assertEqual([day.date for day in report.days], [date(2026, 10, 19), date(2026, 10, 20)])

    def test_usage_page(self) -> None:
        page = parse_usage_page(
            {
                "total": 3,
                "items": [
                    {
                        "created_at": "2026-10-20T10:11:12",
                        "model": "deepseek-flash-1017",
                        "charged_cny": 0.02,
                        "balance_cny": 88.1,
                        "user_id": 132,
                        "input_tokens": 10,
                        "output_tokens": 2,
                        "cache_read_tokens": 1,
                        "cache_write_tokens": 0,
                    }
                ],
            }
        )
        self.assertEqual(page.total, 3)
        self.assertEqual(page.items[0].model, "deepseek-flash-1017")
        self.assertEqual(page.items[0].user_id, 132)
        self.assertAlmostEqual(page.items[0].balance_cny or 0, 88.1)


class _FakeClient(ApiClient):
    """用固定数据模拟官方接口，验证汇总逻辑不依赖网络。"""

    def __init__(self, spending: SpendingReport | None, account: AccountBalance | None, usage: UsagePage | None):
        super().__init__()
        self._spending = spending
        self._account = account
        self._usage = usage

    def fetch_spending(self, key, start, end):  # noqa: ANN001
        return self._spending

    def fetch_account_balance(self, key):  # noqa: ANN001
        return self._account

    def fetch_legacy_balance(self, key):  # noqa: ANN001
        return None

    def fetch_usage_digest(self, key, pages=2, account_user_id=None):  # noqa: ANN001
        return None

    def fetch_usage_page(self, key, offset, limit=200):  # noqa: ANN001
        return self._usage or UsagePage(total=0, items=[])


class AggregationTest(unittest.TestCase):
    def test_account_path(self) -> None:
        today = _today()
        week_start = today - timedelta(days=6)
        days = [
            SpendingDay(date=week_start + timedelta(days=index), requests=index, spend=index * 0.01)
            for index in range(7)
        ]
        spending = SpendingReport(
            user_id=132,
            balance=42.5,
            request_count=sum(day.requests for day in days),
            charged=sum(day.spend for day in days),
            recharged=100,
            totals_tokens=1234,
            days=days,
        )
        client = _FakeClient(spending, AccountBalance(132, 42.5, True), None)
        stats = client.load_stats("sk-test")
        self.assertEqual(stats.data_source, "account")
        self.assertTrue(stats.balance_from_api)
        self.assertAlmostEqual(stats.balance, 42.5)
        self.assertEqual(len(stats.daily), 7)
        self.assertAlmostEqual(stats.week_spend, sum(day.spend for day in days))
        self.assertAlmostEqual(stats.today_spend, days[-1].spend)
        self.assertEqual(stats.today_requests, days[-1].requests)
        self.assertEqual(stats.account_user_id, 132)
        self.assertFalse(stats.account_inactive)
        self.assertAlmostEqual(stats.week_recharged, 100)
        self.assertEqual(stats.week_tokens, 1234)

    def test_usage_fallback(self) -> None:
        today = _today()
        now = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        items = [
            UsageItem(
                created_at=(now - timedelta(days=offset)).strftime("%Y-%m-%dT%H:%M:%S"),
                model="deepseek-flash-1017",
                charged_cny=0.02,
                balance_cny=10.0 - offset,
                user_id=132,
                input_tokens=100,
                output_tokens=10,
                cache_read_tokens=1,
                cache_write_tokens=2,
            )
            for offset in range(3)
        ]
        client = _FakeClient(None, None, UsagePage(total=3, items=items))
        stats = client.load_stats("sk-test")
        self.assertEqual(stats.data_source, "usage")
        self.assertEqual(len(stats.daily), 7)
        self.assertAlmostEqual(stats.week_spend, 0.06)
        self.assertEqual(stats.week_requests, 3)
        self.assertEqual(stats.week_tokens, 3 * 113)
        self.assertAlmostEqual(stats.balance or 0, 10.0)
        self.assertEqual(stats.top_models[0][0], "deepseek-flash-1017")
        self.assertEqual(stats.top_models[0][1], 3)
        self.assertAlmostEqual(stats.today_spend, 0.02)


def _live_key() -> str | None:
    key = os.environ.get("RABBIT_API_KEY", "").strip()
    if key:
        return key
    path = Path.home() / ".dsh" / ".credentials.yaml"
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("RABBIT_API_KEY:"):
                value = line.split(":", 1)[1].strip().strip("\"'")
                if value:
                    return value
    except OSError:
        return None
    return None


class LiveApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.key = _live_key()

    def setUp(self) -> None:
        if not self.key:
            self.skipTest("没有可用的 RABBIT_API_KEY，跳过真实接口测试")

    def test_real_account(self) -> None:
        # 这个 Key 可能正被其他进程并发消费：用「前后快照包络」比较，避免跨请求严格相等而 flaky。
        client = ApiClient()
        today = _today()
        week_start = today - timedelta(days=6)
        before = client.fetch_spending(self.key, week_start, today)
        stats = client.load_stats(self.key)
        after = client.fetch_spending(self.key, week_start, today)
        assert before is not None and after is not None

        self.assertIsNotNone(stats.balance)
        self.assertEqual(len(stats.daily), 7)
        self.assertGreaterEqual(stats.week_requests, 0)
        self.assertGreater(stats.week_tokens, 0)
        self.assertAlmostEqual(stats.week_spend, sum(day.spend for day in stats.daily), places=6)
        self.assertAlmostEqual(stats.today_spend, stats.daily[-1].spend, places=6)
        self.assertAlmostEqual(stats.today_requests, stats.daily[-1].requests)

        # billed 流水只增不减：product 的周汇总必须落在前后两次快照之间。
        self.assertGreaterEqual(stats.week_spend + 1e-9, before.charged)
        self.assertLessEqual(stats.week_spend - 1e-9, after.charged)
        self.assertGreaterEqual(stats.week_tokens, before.totals_tokens)
        self.assertLessEqual(stats.week_tokens, after.totals_tokens)
        self.assertGreaterEqual(stats.week_recharged + 1e-9, before.recharged)
        self.assertLessEqual(stats.week_recharged - 1e-9, after.recharged)

        balance = client.fetch_account_balance(self.key)
        assert balance is not None
        # 余额会因为并发消费/充值实时变化，留 1 元容差并核对账户号
        self.assertAlmostEqual(stats.balance or 0, balance.balance, delta=1.0)
        self.assertEqual(stats.account_user_id, balance.user_id)

    def test_real_usage_digest_consistency(self) -> None:
        client = ApiClient()
        digest = client.fetch_usage_digest(self.key, 1)
        self.assertIsNotNone(digest)
        assert digest is not None
        models, total = digest
        page = client.fetch_usage_page(self.key, 0, 200)
        self.assertIsNotNone(page.total)
        self.assertEqual(total, page.total)
        counted = {}
        for item in page.items:
            if item.model:
                counted[item.model] = counted.get(item.model, 0) + 1
        for name, count in counted.items():
            self.assertLessEqual(count, models.get(name, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
