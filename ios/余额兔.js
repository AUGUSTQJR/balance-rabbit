// 余额兔 · iOS 小组件 v1.4.0
// 数据源：rabbitj.top 官方账户接口（Bearer API Key）
//   GET /v1/account/spending?from=&to=  一次拿余额 + 逐日花费/请求/Token
//   GET /v1/account/balance            余额（spending 没带时兜底）
//   GET /v1/usage?limit=200            最近流水（App 内：累计请求数 + 模型分布）
// 用法：Scriptable 里运行本脚本 → 填 Key → 主屏/锁屏加组件；点组件看明细
// 速度：组件刷新只发 1 个请求（~100ms），不会触发 Scriptable 超时；
//       两个官方接口不可用时自动回退到旧的 /v1/usage/summary 按天汇总方案。

// ===== CORE BEGIN =====
// 纯数据逻辑（不依赖 Scriptable 界面 API，方便用 Node 测试）
const API_BASE = "https://www.rabbitj.top";
const REFRESH_MINUTES = 10;     // 期望刷新间隔（iOS 可能延后）
const LOW_THRESHOLD = 20;       // 余额低于此值变红（元）
const SCRIPT_VERSION = "1.4.0";
const CACHE_VERSION = 4;
const MAX_MODELS = 8;           // 明细里最多列出的模型数
const CONCURRENCY = 4;          // 并发请求数
const KEYCHAIN_NAME = "rabbitj-api-key";
const KEY_FILE = "余额兔-key.txt";
const CACHE_FILE = "余额兔-cache.json";

const WEEKDAY_CN = ["日", "一", "二", "三", "四", "五", "六"];

function pad2(n) {
  return n < 10 ? "0" + n : String(n);
}

function startOfDay(d) {
  const x = new Date(d.getTime());
  x.setHours(0, 0, 0, 0);
  return x;
}

function addDays(d, n) {
  const x = new Date(d.getTime());
  x.setDate(x.getDate() + n);
  return x;
}

function dayKeyOf(d) {
  return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
}

// 汇总接口要 "YYYY-MM-DDTHH:mm:ss"（服务器按本地时间切天）
function fmtMoment(d, suffix) {
  return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate()) + "T" + suffix;
}

// 官方 spending / usage 记录里的 token 字段
function tokensOf(o) {
  if (!o) return 0;
  return (Number(o.input_tokens) || 0) +
    (Number(o.output_tokens) || 0) +
    (Number(o.cache_read_tokens) || 0) +
    (Number(o.cache_write_tokens) || 0);
}

// /v1/usage/summary 的字段（旧方案 / 模型汇总用）
function tokensFromSummary(d) {
  return (Number(d.sum_input_tokens) || 0) +
    (Number(d.sum_output_tokens) || 0) +
    (Number(d.sum_cache_read_tokens) || 0) +
    (Number(d.sum_cache_write_tokens) || 0);
}

async function httpJSON(pathname, key, timeout) {
  const req = new Request(API_BASE + pathname);
  req.headers = { "Authorization": "Bearer " + key, "Accept": "application/json" };
  req.timeoutInterval = timeout || 12;
  const text = await req.loadString();
  const status = req.response ? req.response.statusCode : 0;
  if (status !== 200) {
    const e = new Error("HTTP " + status);
    e.status = status;
    throw e;
  }
  return JSON.parse(text);
}

// 并发执行一串无参函数，保持返回顺序
async function pool(fns, limit) {
  const out = new Array(fns.length);
  let next = 0;
  async function worker() {
    while (true) {
      const i = next++;
      if (i >= fns.length) return;
      out[i] = await fns[i]();
    }
  }
  const ws = [];
  const n = Math.min(limit || CONCURRENCY, fns.length);
  for (let i = 0; i < n; i++) ws.push(worker());
  await Promise.all(ws);
  return out;
}

// ---------- 官方账户接口（2026-10 起首选） ----------
async function fetchAccountBalance(key, timeout) {
  const d = await httpJSON("/v1/account/balance", key, timeout || 6);
  if (!d || typeof d.balance_cny !== "number") return null;
  return { userId: d.user_id != null ? d.user_id : null, balance: d.balance_cny };
}

async function fetchSpending(key, fromDate, toDate, timeout) {
  const q = "?from=" + dayKeyOf(fromDate) + "&to=" + dayKeyOf(toDate);
  const d = await httpJSON("/v1/account/spending" + q, key, timeout || 6);
  if (!d || !Array.isArray(d.days)) throw new Error("spending 返回异常");
  return d;
}

// 一次 spending 请求拼出组件所需的全部数字
async function snapshotFromAccount(key, cache, opts) {
  const light = !!opts.light;
  const reqTimeout = opts.reqTimeout || (light ? 6 : 12);
  const now = new Date();
  const todayStart = startOfDay(now);
  const dates = [];
  for (let i = 6; i >= 0; i--) dates.push(addDays(todayStart, -i));
  const from = dates[0];
  const to = dates[dates.length - 1];

  const rep = await fetchSpending(key, from, to, reqTimeout);
  const byDate = {};
  for (const it of rep.days) {
    if (it && it.date) byDate[String(it.date)] = it;
  }

  const days = dates.map(function (d) {
    const k = dayKeyOf(d);
    const it = byDate[k];
    return {
      key: k,
      label: (d.getMonth() + 1) + "/" + d.getDate(),
      weekday: WEEKDAY_CN[d.getDay()],
      isToday: k === dayKeyOf(to),
      spend: it ? (Number(it.charged_cny) || 0) : 0,
      requests: it ? (Number(it.request_count) || 0) : 0,
      tokens: it ? tokensOf(it) : 0,
    };
  });

  let todaySpend = 0, todayRequests = 0, todayTokens = 0;
  let weekSpend = 0, weekRequests = 0, weekTokens = 0;
  for (const d of days) {
    weekSpend += d.spend;
    weekRequests += d.requests;
    weekTokens += d.tokens;
    if (d.isToday) {
      todaySpend = d.spend;
      todayRequests = d.requests;
      todayTokens = d.tokens;
    }
  }
  const totals = rep.totals || {};
  // 区间汇总优先用 totals（服务器口径，含当天全部已计费记录）
  if (totals.charged_cny != null) weekSpend = Number(totals.charged_cny) || 0;
  if (totals.request_count != null) weekRequests = Number(totals.request_count) || 0;
  if (totals.input_tokens != null) weekTokens = tokensOf(totals);

  // 最近流水：只有 App 内需要（累计请求数 + 模型分布）
  let items = [];
  let totalRequests = null;
  if (!light) {
    try {
      const page = await httpJSON("/v1/usage?limit=200&offset=0&status=billed", key, reqTimeout);
      items = page && Array.isArray(page.items) ? page.items : [];
      totalRequests = page && page.total != null ? page.total : null;
    } catch (e) {}
  }
  const modelNames = uniqueModels(items, (cache && cache.modelNames) || [], MAX_MODELS);
  const modelTasks = light ? [] : modelNames.map(function (name) {
    return function () {
      return modelSummary(key, name, fmtMoment(from, "00:00:00"), fmtMoment(to, "23:59:59"))
        .catch(function () { return null; });
    };
  });
  let modelResults = [];
  if (modelTasks.length) {
    modelResults = (await pool(modelTasks, CONCURRENCY))
      .filter(function (m) { return m && m.requests > 0; });
    modelResults.sort(function (a, b) { return b.spend - a.spend; });
  }

  let balance = typeof rep.balance_cny === "number" ? rep.balance_cny : null;
  let userId = rep.user_id != null ? rep.user_id : null;
  let balanceSource = "spending";
  if (balance == null) {
    try {
      const b = await fetchAccountBalance(key, light ? 4 : 6);
      if (b) {
        balance = b.balance;
        if (b.userId != null) userId = b.userId;
        balanceSource = "balance";
      }
    } catch (e) {}
  }
  if (balance == null && items.length) {
    balance = latestBalance(items);
    balanceSource = "usage";
  }

  return {
    cacheVersion: CACHE_VERSION,
    fetchedAt: now.toISOString(),
    balance: balance,
    userId: userId,
    balanceSource: balanceSource,
    totalRequests: totalRequests,
    days: days,
    todaySpend: todaySpend,
    todayRequests: todayRequests,
    todayTokens: todayTokens,
    weekSpend: weekSpend,
    weekRequests: weekRequests,
    weekTokens: weekTokens,
    models: modelResults.slice(0, MAX_MODELS),
    modelNames: modelNames,
    topModelName: (modelResults[0] && modelResults[0].name) || modelNames[0] || null,
  };
}

// 最新一条已计费记录的余额（兜底）
function latestBalance(items) {
  let iso = null;
  let value = null;
  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    if (it.balance_cny == null) continue;
    if (!iso || (it.created_at && it.created_at > iso)) {
      iso = it.created_at;
      value = Number(it.balance_cny);
    }
  }
  return isFinite(value) ? value : null;
}

function uniqueModels(items, cached, cap) {
  const names = [];
  function add(n) {
    if (n && names.indexOf(n) < 0 && names.length < cap) names.push(n);
  }
  for (let i = 0; i < items.length; i++) add(items[i].model);
  for (let i = 0; i < cached.length; i++) add(cached[i]);
  return names;
}

// ---------- 旧方案（官方接口不可用时回退） ----------
async function daySummary(key, dayDate, timeout) {
  const from = fmtMoment(dayDate, "00:00:00");
  const to = fmtMoment(dayDate, "23:59:59");
  const d = await httpJSON(
    "/v1/usage/summary?status=billed&from=" + from + "&to=" + to, key, timeout || 12);
  return {
    spend: Number(d.sum_charged_cny) || 0,
    requests: Number(d.request_count) || 0,
    tokens: tokensFromSummary(d),
  };
}

async function modelSummary(key, model, fromISO, toISO) {
  const d = await httpJSON(
    "/v1/usage/summary?status=billed&from=" + fromISO + "&to=" + toISO +
    "&model=" + encodeURIComponent(model), key, 12);
  return {
    name: model,
    spend: Number(d.sum_charged_cny) || 0,
    requests: Number(d.request_count) || 0,
    tokens: tokensFromSummary(d),
  };
}

async function snapshotFromUsageSummary(key, cache, opts) {
  const light = !!opts.light;
  const reqTimeout = light ? 5 : 12;
  const now = new Date();
  const todayStart = startOfDay(now);
  const dates = [];
  for (let i = 6; i >= 0; i--) dates.push(addDays(todayStart, -i));

  const pageTasks = [
    function () {
      return httpJSON("/v1/usage?limit=" + (light ? 1 : 200) + "&offset=0&status=billed", key, reqTimeout);
    },
  ];
  if (!light) {
    pageTasks.push(function () {
      return httpJSON("/v1/usage?limit=200&offset=200&status=billed", key, reqTimeout)
        .catch(function () { return { items: [] }; });
    });
  }
  const pages = await pool(pageTasks, pageTasks.length);
  const page = pages[0];
  const items = [];
  for (const p of pages) {
    const arr = p && Array.isArray(p.items) ? p.items : [];
    for (const it of arr) items.push(it);
  }
  if (!items.length) throw new Error("接口没有返回已计费流水");
  const totalRequests = page && page.total == null ? null : page.total;

  let balance = latestBalance(items);
  let userId = null;
  try {
    const b = await httpJSON("/v1/account/balance", key, light ? 4 : 6);
    if (b && typeof b.balance_cny === "number") {
      balance = b.balance_cny;
      if (b.user_id != null) userId = b.user_id;
    }
  } catch (e) {}

  const cachedNames = (cache && cache.modelNames) || [];
  const modelNames = uniqueModels(items, cachedNames, MAX_MODELS);
  const weekFrom = fmtMoment(dates[0], "00:00:00");
  const weekTo = fmtMoment(now, "23:59:59");

  const cachedDays = {};
  if (cache && cache.cacheVersion === CACHE_VERSION && Array.isArray(cache.days)) {
    for (const cd of cache.days) {
      if (cd && cd.key) cachedDays[cd.key] = cd;
    }
  }
  const days = dates.map(function (d, i) {
    const key = dayKeyOf(d);
    const isToday = i === dates.length - 1;
    const cached = cachedDays[key];
    if (light && !isToday && cached) {
      return {
        key: key,
        label: (d.getMonth() + 1) + "/" + d.getDate(),
        weekday: WEEKDAY_CN[d.getDay()],
        isToday: false,
        spend: Number(cached.spend) || 0,
        requests: Number(cached.requests) || 0,
        tokens: Number(cached.tokens) || 0,
        needFetch: false,
      };
    }
    return {
      key: key,
      label: (d.getMonth() + 1) + "/" + d.getDate(),
      weekday: WEEKDAY_CN[d.getDay()],
      isToday: isToday,
      spend: 0,
      requests: 0,
      tokens: 0,
      needFetch: true,
    };
  });
  const pending = [];
  days.forEach(function (info, i) {
    if (info.needFetch) pending.push(i);
  });
  const dayTasks = pending.map(function (i) {
    return function () { return daySummary(key, dates[i], reqTimeout); };
  });
  const modelTasks = light ? [] : modelNames.map(function (name) {
    return function () {
      return modelSummary(key, name, weekFrom, weekTo).catch(function () { return null; });
    };
  });
  const all = await Promise.all([pool(dayTasks, CONCURRENCY), pool(modelTasks, CONCURRENCY)]);
  const dayResults = all[0];
  const modelResults = all[1].filter(function (m) { return m && m.requests > 0; });
  pending.forEach(function (dayIndex, k) {
    const r = dayResults[k];
    days[dayIndex].spend = r.spend;
    days[dayIndex].requests = r.requests;
    days[dayIndex].tokens = r.tokens;
  });
  days.forEach(function (info) { delete info.needFetch; });

  let todaySpend = 0, todayRequests = 0, todayTokens = 0;
  let weekSpend = 0, weekRequests = 0, weekTokens = 0;
  for (const d of days) {
    weekSpend += d.spend;
    weekRequests += d.requests;
    weekTokens += d.tokens;
    if (d.isToday) {
      todaySpend = d.spend;
      todayRequests = d.requests;
      todayTokens = d.tokens;
    }
  }
  modelResults.sort(function (a, b) { return b.spend - a.spend; });

  return {
    cacheVersion: CACHE_VERSION,
    fetchedAt: now.toISOString(),
    balance: balance,
    userId: userId,
    balanceSource: "usage-summary",
    totalRequests: totalRequests,
    days: days,
    todaySpend: todaySpend,
    todayRequests: todayRequests,
    todayTokens: todayTokens,
    weekSpend: weekSpend,
    weekRequests: weekRequests,
    weekTokens: weekTokens,
    models: modelResults.slice(0, MAX_MODELS),
    modelNames: modelNames,
    topModelName: (modelResults[0] && modelResults[0].name) || modelNames[0] || null,
  };
}

// 统一入口：优先官方账户接口，失败回退旧汇总方案
async function fetchSnapshot(key, cache, opts) {
  opts = opts || {};
  try {
    return await snapshotFromAccount(key, cache, opts);
  } catch (e) {
    return await snapshotFromUsageSummary(key, cache, opts);
  }
}
// ===== CORE END =====

// ============ 配色 ============
const COLORS = {
  bgTop: "#F2F7FF",
  bgBottom: "#DCE8FF",
  title: "#5B6B8C",
  ink: "#16233D",
  sub: "#5B6B8C",
  accent: "#2F6BFF",
  bar: "#7FA6FF",
  barPeak: "#FF7A45",
  warn: "#D43F3F",
};

// ============ 本机存储 ============
function fm() {
  return FileManager.local();
}

function docPath(name) {
  return fm().joinPath(fm().documentsDirectory(), name);
}

function readTextFile(name) {
  try {
    const p = docPath(name);
    if (fm().fileExists(p)) return fm().readString(p);
  } catch (e) {}
  return null;
}

function writeTextFile(name, text) {
  try {
    fm().writeString(docPath(name), text);
  } catch (e) {}
}

function loadKey() {
  try {
    if (Keychain.contains(KEYCHAIN_NAME)) {
      const k = Keychain.get(KEYCHAIN_NAME);
      if (k && k.trim()) return k.trim();
    }
  } catch (e) {}
  const fromFile = readTextFile(KEY_FILE);
  return fromFile && fromFile.trim() ? fromFile.trim() : null;
}

function saveKey(key) {
  const k = String(key).trim();
  try {
    Keychain.set(KEYCHAIN_NAME, k);
  } catch (e) {}
  writeTextFile(KEY_FILE, k);
}

function clearKey() {
  try {
    if (Keychain.contains(KEYCHAIN_NAME)) Keychain.remove(KEYCHAIN_NAME);
  } catch (e) {}
  try {
    const p = docPath(KEY_FILE);
    if (fm().fileExists(p)) fm().remove(p);
  } catch (e) {}
}

function keyTail(key) {
  return key ? "…" + key.slice(-4) : "";
}

function readCache() {
  const raw = readTextFile(CACHE_FILE);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (e) {
    return null;
  }
}

function writeCache(data) {
  writeTextFile(CACHE_FILE, JSON.stringify(data));
}

async function loadData(opts) {
  opts = opts || {};
  const key = loadKey();
  if (!key) return { error: "no-key" };
  const cache = readCache();
  // 组件里 3 分钟内的缓存直接复用，避免 iOS 反复渲染时重复请求
  if (opts.light && cache && cache.cacheVersion === CACHE_VERSION &&
      cache.days && cache.days.length === 7 && cache.fetchedAt) {
    const age = Date.now() - Date.parse(cache.fetchedAt);
    if (isFinite(age) && age >= 0 && age < 3 * 60 * 1000) {
      return { data: cache, stale: false };
    }
  }
  try {
    const data = await fetchSnapshot(key, cache, opts);
    writeCache(data);
    return { data: data, stale: false };
  } catch (e) {
    if (cache && cache.cacheVersion === CACHE_VERSION && cache.days && cache.days.length === 7) {
      return { data: JSON.parse(JSON.stringify(cache)), stale: true, staleReason: e.message || String(e) };
    }
    return { error: e.message || String(e) };
  }
}

// ============ 文本工具 ============
function money(v) {
  const n = Number(v);
  return "¥" + (isFinite(n) ? n.toFixed(2) : "--");
}

function fmtTokens(n) {
  n = Number(n) || 0;
  if (n >= 1e8) return (n / 1e8).toFixed(2) + " 亿";
  if (n >= 1e4) return (n / 1e4).toFixed(1) + " 万";
  return String(n);
}

function clock(iso) {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "--:--";
  return pad2(d.getHours()) + ":" + pad2(d.getMinutes());
}

// ============ 组件绘制 ============
function applyBackground(w) {
  const g = new LinearGradient();
  g.colors = [Color.hex(COLORS.bgTop), Color.hex(COLORS.bgBottom)];
  g.locations = [0, 1];
  w.backgroundGradient = g;
}

function addLabel(stack, str, size, color, bold) {
  const t = stack.addText(str);
  t.font = bold ? Font.boldSystemFont(size) : Font.systemFont(size);
  t.textColor = Color.hex(color);
  t.lineLimit = 1;
  t.minimumScaleFactor = 0.45;
  return t;
}

function balanceColor(data) {
  if (data.balance != null && data.balance < LOW_THRESHOLD) return COLORS.warn;
  return COLORS.ink;
}

// 7 天柱状图（离屏绘制成图片）
function drawChart(days) {
  const W = 116, H = 64, gap = 4, padX = 1;
  const ctx = new DrawContext();
  ctx.size = new Size(W, H);
  ctx.opaque = false;
  ctx.respectScreenScale = true;

  const max = Math.max.apply(null, days.map(function (d) { return d.spend; }).concat([0]));
  const n = days.length;
  const barW = (W - padX * 2 - gap * (n - 1)) / n;
  const chartTop = 8;
  const chartBottom = H - 13;
  const span = chartBottom - chartTop;

  for (let i = 0; i < n; i++) {
    const d = days[i];
    const x = padX + i * (barW + gap);
    let h = max > 0 ? (d.spend / max) * span : 0;
    if (h < 2) h = 2;
    const y = chartBottom - h;

    let color = COLORS.bar;
    if (max > 0 && d.spend === max) color = COLORS.barPeak;
    if (d.isToday) color = COLORS.accent;

    ctx.setFillColor(Color.hex(color));
    ctx.addPath(Path.roundedRect(new Rect(x, y, barW, h), Math.min(2.5, barW / 2)));
    ctx.fillPath();

    ctx.setFont(Font.systemFont(8));
    ctx.setTextColor(Color.hex(COLORS.sub));
    ctx.setTextAlignedCenter();
    ctx.drawTextInRect(d.weekday, new Rect(x - 2, chartBottom + 3, barW + 4, 9));
  }
  return ctx.getImage();
}

function smallWidget(info) {
  const data = info.data;
  const w = new ListWidget();
  applyBackground(w);
  w.setPadding(12, 12, 12, 12);
  w.url = URLScheme.forRunningScript();
  w.refreshAfterDate = new Date(Date.now() + REFRESH_MINUTES * 60 * 1000);

  addLabel(w, "🐰 余额兔", 9, COLORS.title);
  w.addSpacer(3);
  addLabel(w, money(data.balance), 25, balanceColor(data), true);
  w.addSpacer(3);
  addLabel(w, "今日 " + money(data.todaySpend), 10, COLORS.sub);
  addLabel(w, "7天 " + money(data.weekSpend), 10, COLORS.sub);
  w.addSpacer(2);
  if (info.stale) addLabel(w, "⚠️ 离线缓存", 8, COLORS.warn);
  return w;
}

function mediumWidget(info) {
  const data = info.data;
  const w = new ListWidget();
  applyBackground(w);
  w.setPadding(12, 14, 12, 14);
  w.url = URLScheme.forRunningScript();
  w.refreshAfterDate = new Date(Date.now() + REFRESH_MINUTES * 60 * 1000);

  const row = w.addStack();
  row.layoutDirection = "row";

  const left = row.addStack();
  left.layoutDirection = "column";
  left.spacing = 1;

  addLabel(left, "🐰 余额兔", 9, COLORS.title);
  addLabel(left, money(data.balance), 23, balanceColor(data), true);
  addLabel(left, "今日 " + money(data.todaySpend) + " · 7天 " + money(data.weekSpend), 9.5, COLORS.sub);
  addLabel(left, "Token 7天 " + fmtTokens(data.weekTokens), 9, COLORS.sub);
  if (info.stale) {
    addLabel(left, "⚠️ 更新失败·缓存", 8, COLORS.warn);
  } else {
    addLabel(left, data.topModelName || "暂无用量", 8, COLORS.title);
  }

  row.addSpacer(4);
  const img = row.addImage(drawChart(data.days));
  img.imageSize = new Size(116, 60);
  return w;
}

function lockWidget(family, info) {
  const data = info.data;
  const w = new ListWidget();
  w.addAccessoryWidgetBackground = true;
  w.url = URLScheme.forRunningScript();

  if (family === "accessoryInline") {
    w.addText("余额 " + money(data.balance) + " · 今日 " + money(data.todaySpend));
    return w;
  }
  if (family === "accessoryCircular") {
    const t = w.addText(money(data.balance).replace(".00", ""));
    t.font = Font.boldSystemFont(12);
    t.minimumScaleFactor = 0.5;
    t.centerAlignText();
    return w;
  }
  const col = w.addStack();
  col.layoutDirection = "column";
  col.spacing = 1;
  addLabel(col, "余额 " + money(data.balance), 13, "#FFFFFF", true);
  addLabel(col, "今日 " + money(data.todaySpend) + " · 7天 " + money(data.weekSpend), 9, "#FFFFFF");
  return w;
}

function errorWidget(info) {
  const w = new ListWidget();
  applyBackground(w);
  w.setPadding(12, 12, 12, 12);
  w.url = URLScheme.forRunningScript();
  w.refreshAfterDate = new Date(Date.now() + REFRESH_MINUTES * 60 * 1000);

  addLabel(w, "🐰 余额兔", 11, COLORS.title, true);
  w.addSpacer(4);
  if (info.error === "no-key") {
    addLabel(w, "未配置 API Key", 12, COLORS.ink, true);
    w.addSpacer(2);
    addLabel(w, "点我填写", 9, COLORS.accent);
  } else {
    addLabel(w, "更新失败", 12, COLORS.warn, true);
    w.addSpacer(2);
    addLabel(w, String(info.error).slice(0, 40), 8, COLORS.sub);
  }
  return w;
}

function buildWidget(info) {
  if (info.error) return errorWidget(info);
  const family = config.widgetFamily || "medium";
  if (family.indexOf("accessory") === 0) return lockWidget(family, info);
  if (family === "small") return smallWidget(info);
  return mediumWidget(info);
}

// ============ 硬超时（组件里防止网络卡死） ============
// Timer.timeInterval 单位是毫秒
function withDeadline(promise, ms) {
  return new Promise(function (resolve) {
    let done = false;
    let timer = null;
    try {
      timer = new Timer();
      timer.timeInterval = ms;
      timer.schedule(function () {
        if (!done) {
          done = true;
          resolve({ ok: false, error: new Error("本地超时") });
        }
      });
    } catch (e) {}
    promise.then(function (v) {
      if (done) return;
      done = true;
      try { if (timer) timer.invalidate(); } catch (e) {}
      resolve({ ok: true, value: v });
    }, function (e) {
      if (done) return;
      done = true;
      try { if (timer) timer.invalidate(); } catch (e2) {}
      resolve({ ok: false, error: e });
    });
  });
}

// 组件里给整个取数过程兜底：到点就用手头缓存，绝不让组件被杀掉
async function loadDataBounded(opts, deadlineMs) {
  const res = await withDeadline(loadData(opts), deadlineMs || 5000);
  if (res.ok) return res.value;
  const cache = readCache();
  if (cache && cache.cacheVersion === CACHE_VERSION && cache.days && cache.days.length === 7) {
    return { data: cache, stale: true, staleReason: "本地超时" };
  }
  return { error: res.error && res.error.message ? res.error.message : "本地超时" };
}

// ============ App 内详情 ============
async function askForKey(message) {
  const a = new Alert();
  a.title = "填写 rabbitj.top API Key";
  a.message = message ||
    "在 Mac 终端执行下面命令把 Key 复制到剪贴板，再用手机「通用剪贴板」粘贴：\n\n" +
    "awk '/RABBIT_API_KEY/{print $2}' ~/.dsh/.credentials.yaml | pbcopy\n\n" +
    "（Key 只保存在本机，不会上传）";
  a.addTextField("sk-...");
  a.addAction("保存");
  a.addCancelAction("取消");
  const choice = await a.presentAlert();
  if (choice !== 0) return null;
  let k = (a.textFieldValue(0) || "").trim();
  k = k.replace(/^Bearer\s+/i, "").trim();
  return k || null;
}

async function presentDetail(res) {
  const data = res.data;
  const table = new UITable();
  table.showSeparators = false;

  function addRow(title, detail, height) {
    const r = new UITableRow();
    r.height = height || 44;
    r.addText(String(title), detail == null ? "" : String(detail));
    table.addRow(r);
    return r;
  }
  function addSection(title) {
    const r = new UITableRow();
    r.height = 30;
    r.addText(title);
    table.addRow(r);
  }

  let sub = "更新 " + clock(data.fetchedAt);
  if (data.userId != null) sub += " · 账户 #" + data.userId;
  if (res.stale) sub += " · ⚠️ 离线缓存";
  addRow("余额 " + money(data.balance), sub, 56);

  addRow("今日花费", money(data.todaySpend) + " · " + data.todayRequests + " 次");
  addRow("近 7 天花费", money(data.weekSpend) + " · " + data.weekRequests + " 次");
  addRow("今日 Token", fmtTokens(data.todayTokens));
  addRow("近 7 天 Token", fmtTokens(data.weekTokens));
  if (data.totalRequests != null) addRow("累计请求", data.totalRequests + " 次");

  addSection("每日花费");
  for (const d of data.days) {
    addRow(d.label + " 周" + d.weekday, money(d.spend) + " · " + d.requests + " 次 · " + fmtTokens(d.tokens) + " tok", 40);
  }

  if (data.models && data.models.length) {
    addSection("模型（近 7 天）");
    for (const m of data.models) {
      addRow(m.name, money(m.spend) + " · " + m.requests + " 次 · " + fmtTokens(m.tokens) + " tok", 40);
    }
  }

  addSection("操作");
  const copyRow = addRow("复制余额", money(data.balance), 42);
  copyRow.onSelect = function () {
    Pasteboard.copy(Number(data.balance).toFixed(2));
  };
  const webRow = addRow("打开 rabbitj.top", "充值 / 网页版", 42);
  webRow.onSelect = function () {
    Safari.open("https://www.rabbitj.top/");
  };
  addRow("当前 Key 尾号", keyTail(loadKey()), 40);

  addSection("余额兔 v" + SCRIPT_VERSION + " · 点组件即刷新");
  await table.present();
}

async function runInApp() {
  let key = loadKey();
  if (!key) {
    key = await askForKey();
    if (!key) return;
    saveKey(key);
  }

  let res = await loadData();
  while (res.error && res.error !== "no-key") {
    const a = new Alert();
    a.title = "查询失败";
    a.message = "错误：" + res.error + "\n\n请检查网络，或更换 API Key 后重试。";
    a.addAction("重试");
    a.addAction("更换 Key");
    a.addCancelAction("退出");
    const idx = await a.presentAlert();
    if (idx === 0) {
      res = await loadData();
      continue;
    }
    if (idx === 1) {
      const k = await askForKey("粘贴新的 Key（会覆盖旧的）：");
      if (k) {
        clearKey();
        saveKey(k);
        res = await loadData();
        continue;
      }
    }
    return;
  }

  const data = res.data;
  Script.setShortcutOutput(
    "余额 " + money(data.balance) +
    " · 今日 " + money(data.todaySpend) +
    " · 7天 " + money(data.weekSpend) +
    " · Token " + fmtTokens(data.weekTokens)
  );

  if (!config.runsInApp) return;
  try {
    await presentDetail(res);
  } catch (e) {
    // 后台运行时无法弹窗，忽略
  }
}

// ============ 入口 ============
async function main() {
  if (config.runsInWidget) {
    const info = await loadDataBounded({ light: true }, 5000);
    const w = buildWidget(info);
    Script.setWidget(w);
    Script.complete();
    return;
  }
  await runInApp();
  Script.complete();
}

main().catch(async function (e) {
  if (config.runsInWidget) {
    const w = errorWidget({ error: e.message || String(e) });
    Script.setWidget(w);
  } else {
    try {
      const a = new Alert();
      a.title = "出错了";
      a.message = e.message || String(e);
      a.addAction("好");
      await a.presentAlert();
    } catch (err) {}
  }
  Script.complete();
});
