#!/usr/bin/env python3
"""独立核对：用翻页流水重新统计 7 天数据，对比 余额兔.js 输出的快照。
用法：先跑 `TZ=Asia/Shanghai node ios/test-core.mjs`，再 `python3 ios/crosscheck.py`
（今日数据会随时间增长，允许今日差额；历史 6 天必须逐日精确一致）"""
import json
import subprocess
import sys
import urllib.request
import datetime

KEY = subprocess.check_output(
    ["bash", "-lc",
     "awk '/RABBIT_API_KEY/{print $2}' ~/.dsh/.credentials.yaml"]).decode().strip()
snap = json.load(open("/tmp/rabbit-ios-snapshot.json"))

now = datetime.datetime.now()
today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
week0 = today0 - datetime.timedelta(days=6)

days = {}
spend = req = tok = 0
items = []
off = 0
while True:
    r = urllib.request.Request(
        "https://www.rabbitj.top/v1/usage?limit=200&offset=%d&status=billed" % off,
        headers={"Authorization": "Bearer " + KEY})
    arr = json.load(urllib.request.urlopen(r, timeout=15)).get("items", [])
    if not arr:
        break
    items += arr
    off += 200
    if len(arr) < 200:
        break
    if datetime.datetime.fromisoformat(arr[-1]["created_at"]) < week0:
        break

for it in items:
    t = datetime.datetime.fromisoformat(it["created_at"])
    if t < week0:
        continue
    c = it.get("charged_cny") or 0
    tk = ((it.get("input_tokens") or 0) + (it.get("output_tokens") or 0) +
          (it.get("cache_read_tokens") or 0) + (it.get("cache_write_tokens") or 0))
    spend += c
    req += 1
    tok += tk
    e = days.setdefault(t.date().isoformat(), {"spend": 0, "requests": 0, "tokens": 0})
    e["spend"] += c
    e["requests"] += 1
    e["tokens"] += tk

fails = []


def chk(name, ok, extra=""):
    print(("✅ " if ok else "❌ ") + name + ("  " + extra if extra else ""))
    if not ok:
        fails.append(name)


today = snap["days"][-1]["key"]
past = snap["days"][:-1]
chk("历史 6 天花费逐日一致",
    abs(sum(days[d["key"]]["spend"] for d in past) - sum(d["spend"] for d in past)) < 1e-6)
chk("历史 6 天请求数逐日一致",
    all(days[d["key"]]["requests"] == d["requests"] for d in past))
for d in past:
    e = days[d["key"]]
    chk("历史日 " + d["key"],
        abs(e["spend"] - d["spend"]) < 1e-6 and e["requests"] == d["requests"])
chk("今日（独立统计 >= 快照）", days[today]["spend"] >= snap["todaySpend"] - 1e-9)
chk("总差额 == 今日新增差额",
    abs((spend - snap["weekSpend"]) - (days[today]["spend"] - snap["todaySpend"])) < 1e-6)
chk("请求差额 == 今日新增", (req - snap["weekRequests"]) == (days[today]["requests"] - snap["todayRequests"]))
def get_json(path):
    r = urllib.request.Request("https://www.rabbitj.top" + path,
                               headers={"Authorization": "Bearer " + KEY})
    return json.load(urllib.request.urlopen(r, timeout=15))


bal = get_json("/v1/account/balance")
chk("余额与 /v1/account/balance 一致（容差 0.5，期间可能有新消费）",
    abs(bal["balance_cny"] - snap["balance"]) < 0.5,
    "account=%.4f snap=%.4f" % (bal["balance_cny"], snap["balance"]))

sp = get_json("/v1/account/spending?from=%s&to=%s" %
              (snap["days"][0]["key"], snap["days"][-1]["key"]))
chk("官方 spending 的历史 6 天与翻页统计一致",
    all(abs(d["charged_cny"] - days[d["date"]]["spend"]) < 1e-6
        for d in sp["days"] if d["date"] != today))

if fails:
    sys.exit(1)
print("\n独立核对通过")
