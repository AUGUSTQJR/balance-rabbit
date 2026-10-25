#!/usr/bin/env node
// 数据层测试：抽出 余额兔.js 的 CORE 段，用 Node fetch 模拟 Scriptable Request。
// 核对：官方账户接口 /v1/account/spending 的逐日数字 == 独立重算；
//       组件轻量模式只发 1 个请求；旧 /v1/usage/summary 回退方案数字一致。
// 用法：TZ=Asia/Shanghai node ios/test-core.mjs
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const dir = path.dirname(new URL(import.meta.url).pathname);
const src = fs.readFileSync(path.join(dir, "余额兔.js"), "utf8");
const core = src.split("// ===== CORE BEGIN =====")[1].split("// ===== CORE END =====")[0];
if (!core) throw new Error("找不到 CORE 段");

let requestCount = 0;

globalThis.Request = class {
  constructor(url) {
    this.url = url;
    this.headers = {};
    this.response = null;
  }
  async loadString() {
    requestCount += 1;
    const r = await fetch(this.url, { headers: this.headers });
    this.response = { statusCode: r.status };
    return await r.text();
  }
};

const api = new Function(
  core +
  "\nreturn { fetchSnapshot, snapshotFromAccount, snapshotFromUsageSummary, fetchAccountBalance, pool, daySummary, dayKeyOf, startOfDay, addDays, fmtMoment };"
)();

function credKey() {
  if (process.env.RABBIT_KEY) return process.env.RABBIT_KEY.trim();
  const yaml = fs.readFileSync(path.join(os.homedir(), ".dsh/.credentials.yaml"), "utf8");
  const m = yaml.match(/RABBIT_API_KEY:\s*(\S+)/);
  if (!m) throw new Error("找不到 RABBIT_API_KEY");
  return m[1].trim();
}

const fails = [];
function check(name, ok, extra) {
  console.log((ok ? "✅" : "❌") + " " + name + (extra ? "  " + extra : ""));
  if (!ok) fails.push(name);
}

// ---------- 1. 并发池保序 ----------
const order = await api.pool([
  async () => { await new Promise((r) => setTimeout(r, 30)); return "a"; },
  async () => { await new Promise((r) => setTimeout(r, 5)); return "b"; },
  async () => "c",
], 2);
check("pool 并发但保持顺序", JSON.stringify(order) === JSON.stringify(["a", "b", "c"]), JSON.stringify(order));

const key = credKey();

// ---------- 2. App 内完整快照（官方 spending + usage + 模型） ----------
requestCount = 0;
const t0 = Date.now();
const snap = await api.fetchSnapshot(key, null);
const ms = Date.now() - t0;
const fullReq = requestCount;
console.log(`\n完整快照：${ms} ms，${fullReq} 个请求，余额 ${snap.balance}，7 天 ${snap.weekRequests} 次 / ¥${snap.weekSpend.toFixed(2)}`);
check("完整快照：数据源为官方 spending", snap.balanceSource === "spending");
check("7 天数组", snap.days.length === 7 && snap.days[6].isToday);
check("今日 == 今天那格", Math.abs(snap.days[6].spend - snap.todaySpend) < 1e-9);
check("7 天总额 == 每日之和",
  Math.abs(snap.days.reduce((a, d) => a + d.spend, 0) - snap.weekSpend) < 1e-6,
  `${snap.days.reduce((a, d) => a + d.spend, 0).toFixed(4)} vs ${snap.weekSpend.toFixed(4)}`);
check("请求数同理", snap.days.reduce((a, d) => a + d.requests, 0) === snap.weekRequests);
check("余额非空", snap.balance != null && snap.balance > 0, String(snap.balance));
check("模型列表非空", snap.models.length > 0, snap.models.map((m) => m.name).join(","));
check("模型请求数不超过 7 天请求数",
  snap.models.reduce((a, m) => a + m.requests, 0) <= snap.weekRequests);
check("累计请求数非空", snap.totalRequests != null, String(snap.totalRequests));

// 余额以 /v1/account/balance 为准（并发跑测试期间可能又花了钱，放宽容差）
const bal = await api.fetchAccountBalance(key, 6);
check("余额与账户接口一致", !!bal && Math.abs(snap.balance - bal.balance) < 0.5,
  `spending=${snap.balance} balance=${bal && bal.balance}`);

// ---------- 3. 组件轻量模式：只发 1 个请求 ----------
requestCount = 0;
const t2 = Date.now();
const light = await api.fetchSnapshot(key, null, { light: true });
const lightMs = Date.now() - t2;
const lightReq = requestCount;
console.log(`组件刷新：${lightMs} ms，${lightReq} 个请求`);
check("组件刷新：只发 1~2 个请求", lightReq <= 2, String(lightReq));
check("组件刷新：7 天数字齐全",
  light.days.length === 7 && light.weekRequests > 0 && light.weekSpend > 0);
check("组件刷新：不查模型明细", light.models.length === 0);
check("组件刷新：与完整快照历史日一致",
  JSON.stringify(light.days.slice(0, 6).map((d) => [d.key, d.requests, +d.spend.toFixed(4)])) ===
  JSON.stringify(snap.days.slice(0, 6).map((d) => [d.key, d.requests, +d.spend.toFixed(4)])));

// ---------- 4. 旧方案回退：/v1/usage/summary 按天汇总，数字应一致 ----------
const fb = await api.snapshotFromUsageSummary(key, null, {});
console.log(`回退方案（summary）：7 天 ${fb.weekRequests} 次 / ¥${fb.weekSpend.toFixed(2)}`);
check("回退方案：历史 6 天与官方接口一致",
  fb.days.slice(0, 6).every((d, i) =>
    d.requests === snap.days[i].requests && Math.abs(d.spend - snap.days[i].spend) < 1e-6));

// ---------- 5. 带缓存再跑（模型清单复用） ----------
const snap2 = await api.fetchSnapshot(key, JSON.parse(JSON.stringify(snap)));
check("缓存复用后数字自洽",
  snap2.days.length === 7 && Math.abs(snap2.weekSpend - snap2.days.reduce((a, d) => a + d.spend, 0)) < 1e-6);
check("缓存复用后模型清单不丢", snap2.models.length >= Math.min(snap.models.length, 1));

// ---------- 6. 交给 Python 独立核对 ----------
fs.writeFileSync("/tmp/rabbit-ios-snapshot.json", JSON.stringify(snap, null, 2));

if (fails.length) {
  console.error("\n失败项：" + fails.join(", "));
  process.exit(1);
}
console.log("\n全部通过");
