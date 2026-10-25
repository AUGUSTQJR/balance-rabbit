// 余额兔 · 诊断 v1
// 用途：判断"组件超时"是 Scriptable 组件环境的问题，还是网络/脚本的问题。
// 用法：
//   1. 作为独立脚本粘贴到 Scriptable，命名「诊断」。
//   2. 在 App 里手动运行 → 弹出诊断结果（网络是否通、缓存/Key 是否在、耗时）。
//   3. 再加一个小号组件选「诊断」→ 组件里应该显示"✅ 组件能运行"（不发任何网络请求）。

const KEYCHAIN_NAME = "rabbitj-api-key";
const KEY_FILE = "余额兔-key.txt";
const CACHE_FILE = "余额兔-cache.json";

function docPath(name) {
  const fm = FileManager.local();
  return fm.joinPath(fm.documentsDirectory(), name);
}

function readText(name) {
  try {
    const fm = FileManager.local();
    const p = docPath(name);
    if (fm.fileExists(p)) return fm.readString(p);
  } catch (e) {}
  return null;
}

function getKey() {
  try {
    if (Keychain.contains(KEYCHAIN_NAME)) {
      const k = Keychain.get(KEYCHAIN_NAME);
      if (k && k.trim()) return k.trim();
    }
  } catch (e) {}
  const f = readText(KEY_FILE);
  return f && f.trim() ? f.trim() : null;
}

function hhmm() {
  const d = new Date();
  return ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2);
}

async function main() {
  if (config.runsInWidget) {
    // 组件里绝不发网络请求，只验证"组件能不能把东西画出来"
    const w = new ListWidget();
    w.backgroundColor = Color.white();
    w.setPadding(10, 10, 10, 10);
    const title = w.addText("✅ 组件能运行");
    title.font = Font.boldSystemFont(11);
    title.textColor = Color.black();
    const t = w.addText(hhmm() + " · v1");
    t.font = Font.systemFont(9);
    t.textColor = Color.gray();
    const keyText = w.addText(getKey() ? "Key: 已保存" : "Key: 未配置");
    keyText.font = Font.systemFont(9);
    keyText.textColor = Color.gray();
    const cache = readText(CACHE_FILE);
    const cacheText = w.addText(cache ? "缓存: 有" : "缓存: 无");
    cacheText.font = Font.systemFont(9);
    cacheText.textColor = Color.gray();
    Script.setWidget(w);
    Script.complete();
    return;
  }

  const lines = [];
  lines.push("时间: " + hhmm());
  lines.push("Key: " + (getKey() ? "已保存（尾号 …" + getKey().slice(-4) + "）" : "未配置"));
  const cacheRaw = readText(CACHE_FILE);
  if (cacheRaw) {
    try {
      const c = JSON.parse(cacheRaw);
      lines.push("缓存: 有，版本 " + (c.cacheVersion || "?") + "，更新于 " + (c.fetchedAt || "?"));
    } catch (e) {
      lines.push("缓存: 有但解析失败");
    }
  } else {
    lines.push("缓存: 无");
  }

  // 网络测试 1：不带 Key 的公开接口
  const t0 = Date.now();
  try {
    const req = new Request("https://www.rabbitj.top/v1/models");
    req.timeoutInterval = 10;
    const text = await req.loadString();
    lines.push("网络(models): OK " + (Date.now() - t0) + "ms，" + text.length + " 字节");
  } catch (e) {
    lines.push("网络(models): 失败 " + (Date.now() - t0) + "ms，" + (e.message || e));
  }

  // 网络测试 2：带 Key 的流水接口
  const key = getKey();
  if (key) {
    const t1 = Date.now();
    try {
      const req = new Request("https://www.rabbitj.top/v1/usage?limit=1&status=billed");
      req.headers = { Authorization: "Bearer " + key };
      req.timeoutInterval = 10;
      const text = await req.loadString();
      lines.push("网络(usage): OK " + (Date.now() - t1) + "ms，" + text.length + " 字节");
    } catch (e) {
      lines.push("网络(usage): 失败 " + (Date.now() - t1) + "ms，" + (e.message || e));
    }

    // 汇总接口测试
    const t2 = Date.now();
    try {
      const d = new Date();
      const p = (n) => (n < 10 ? "0" + n : "" + n);
      const from = d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + "T00:00:00";
      const to = d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + "T23:59:59";
      const req = new Request("https://www.rabbitj.top/v1/usage/summary?status=billed&from=" + from + "&to=" + to);
      req.headers = { Authorization: "Bearer " + key };
      req.timeoutInterval = 10;
      const text = await req.loadString();
      const j = JSON.parse(text);
      lines.push("网络(summary): OK " + (Date.now() - t2) + "ms，今日 " + j.request_count + " 次 / ¥" + j.sum_charged_cny);
    } catch (e) {
      lines.push("网络(summary): 失败 " + (Date.now() - t2) + "ms，" + (e.message || e));
    }
  }

  lines.push("");
  lines.push("如果上面三行网络都 OK，加到主屏的组件却仍超时，");
  lines.push("说明是 Scriptable 组件环境的问题（重装 App 或重启手机）。");

  const a = new Alert();
  a.title = "余额兔 · 诊断结果";
  a.message = lines.join("\n");
  a.addAction("好");
  await a.presentAlert();
  Script.complete();
}

main().catch(async function (e) {
  if (config.runsInWidget) {
    const w = new ListWidget();
    w.backgroundColor = Color.white();
    const t = w.addText("诊断组件出错: " + (e.message || e));
    t.textColor = Color.red();
    Script.setWidget(w);
  } else {
    const a = new Alert();
    a.title = "诊断失败";
    a.message = String(e.message || e);
    a.addAction("好");
    await a.presentAlert();
  }
  Script.complete();
});
