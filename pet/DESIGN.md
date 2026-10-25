# 余额兔 · 设计文档（含踩坑与复用清单）

> 本文记录「余额兔」从需求到实现的全过程，目的是：**以后在这个工作区做别的小工具 App 时，
> 可以直接复用这里的设计模式、代码骨架和踩坑经验。**

---

## 1. 需求沿革（决策时间线）

| 阶段 | 用户需求 | 关键决策 |
|---|---|---|
| 起点 | 「查下余额」 | 确认 rabbitj.top 的 `GET /v1/usage?status=billed` 能拿到 `balance_cny` |
| 1 | 「做个桌面宠物，点它查余额，再加点功能」 | 原生 Swift/AppKit；奶油色兔子；点开气泡；菜单栏常驻 |
| 2 | 「加个调整兔子大小」 | ⌥/⌘+滚轮缩放 + 菜单预设（96–320，默认 176）；缩放以底边居中为锚点 |
| 3 | 「到屏幕边缘自动吸附，变成扒在边缘的小图标，点一下弹出来」 | 第一版：把站立兔子裁一半 → **被否（简陋）** |
| 4 | 「吸附时换成专门趴边的兔子，左右和下面都画，我选风格」 | 画了趴边兔子三视图 → 用户又改主意 |
| 5 | 「不要兔子了，要圆圆的气泡，电子风蓝色，加点动态，只露半个」 | 做了 4 款电子风指示器方案图供选择 |
| 6 | 「不做底部吸附，只要左右」 | 吸附范围收敛为左/右 |
| 7 | 用户选定 **C · 箭头标签** | `arrowTab` 设为默认，48×48、只露一半 |
| 8 | 「打包发给同事测试」 | 通用二进制 + ad-hoc 签名 + 一键安装脚本 |

**产品原则（用户反复强化的）**：吸附态要「存在感弱、小、精致」，宁可用抽象几何图形也不要丑的兔子；
功能上要「点一下就能看余额」的低打扰挂件。

---

## 2. 整体架构

```
main.swift
 ├── CLI 分支：--stats / --render / --enable-login / --disable-login
 └── SingleInstance.claim() 失败 → requestShow() → exit
     成功 → NSApplication(.accessory) → AppDelegate

AppDelegate
 ├── 窗口：petPanel(兔子 176) / bubblePanel(气泡 300×282) / dockPanel(吸附指示器 48×48)
 ├── 查询：Timer(10min) → APIClient.loadStats() → petView.lowBalance / bubbleView.stats
 ├── 菜单：NSStatusItem（标题 ¥xx.xx）+ 右键上下文菜单 + 菜单栏菜单
 ├── 吸附：拖动结束判定边缘 → dock(to:) / undock()
 └── 通知：低余额 osascript（6h 节流）
```

数据流：`Settings(UserDefaults)` 提供配置 → `APIClient` 拉数据 → `Stats` 模型 → 两个 View 渲染。
视图全部是 `NSView` 子类 + `NSBezierPath` 自绘，没有图片资源（图标除外，由预览图生成 icns）。

---

## 3. 数据接口与统计口径

```
GET https://www.rabbitj.top/v1/usage?limit=200&offset=N&status=billed
Authorization: Bearer <key>
```

- `balance_cny`：最新一条已计费请求后的余额 → 直接当「当前余额」。
- `total`：账号累计请求数。
- 今日 / 7 天：按 `created_at`（`yyyy-MM-dd'T'HH:mm:ss`，本地时区）落在窗口内求和 `charged_cny`。
- Token：`total_tokens` 求和；模型分布：`model` 计数取前 3。
- 分页：`limit` 最大 200，超过返回空；7 天窗口最多翻 25 页（5000 条），超了置 `partial=true`，
  气泡底部提示「已统计最近 N 条」。
- 错误分类：`missingKey / http / badResponse / noRecords / decoding`，每种给不同中文提示。

API Key 读取顺序：`RABBIT_API_KEY` env → Keychain（service `top.rabbitj.balancepet`, account `api-key`）
→ `~/.dsh/.credentials.yaml`。菜单可手动设置并写入 Keychain。

---

## 4. 视觉设计

**配色（固定值，不用动态色）**

| 用途 | 值 |
|---|---|
| 兔子毛色 / 高光 | `#FDF8EF`，渐变 `#FFF9F1 → #FFEDE2` |
| 毛色阴影 | `#F0E6D8` |
| 粉色（耳朵内/鼻/腮红） | `#F6C4C4` |
| 墨色（眼睛/文字） | `#342D28` |
| 气泡卡片 | `#FEFCF9`，强调紫 `#5A57D6` |
| 低余额警示 | `#E6382F` |
| 吸附指示器（电子风） | 深蓝 `#2760FA`、浅蓝 `#6DCDFF`、青 `#9CF2FF` |

**尺寸**：兔子 176pt（可 96–320）方形窗口；气泡 300×282；吸附指示器 48×48 只露 24pt。
**动效**：24–30fps Timer，`phase` 累加；呼吸（sin 缩放/位移）、耳朵摆动（sin 角度）、
随机眨眼（每 3.9s 一周期内 0.18s 闭眼）、加载时小跳；吸附指示器箭头浮动 + 光晕呼吸 + 悬停加亮。

---

## 5. 核心实现骨架（可直接抄）

### 5.1 无边框浮动面板

```swift
let panel = NSPanel(contentRect: rect,
                    styleMask: [.borderless, .nonactivatingPanel],
                    backing: .buffered, defer: false)
panel.isOpaque = false
panel.backgroundColor = .clear
panel.hasShadow = false
panel.level = .floating
panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
panel.isReleasedWhenClosed = false
panel.hidesOnDeactivate = false
panel.appearance = NSAppearance(named: .aqua)   // 关键：避免深色模式配色崩
panel.contentView = customView
```

### 5.2 单实例（flock）

```swift
let dir = NSHomeDirectory() + "/Library/Application Support/余额兔"
try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
let fd = open(dir + "/instance.lock", O_CREAT | O_RDWR, 0o644)
if flock(fd, LOCK_EX | LOCK_NB) == 0 { /* 我是第一个 */ }
else { DistributedNotificationCenter.default().post(name: .init("top.rabbitj.balancepet.show"), object: nil); exit(0) }
```

### 5.3 离屏渲染预览（PNG）

```swift
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: w, pixelsHigh: h,
                           bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                           isPlanar: false, colorSpaceName: .deviceRGB,
                           bytesPerRow: 0, bitsPerPixel: 0)!
rep.size = bounds.size
let ctx = NSGraphicsContext(bitmapImageRep: rep)!
NSGraphicsContext.current = ctx
cacheDisplay(in: bounds, to: rep)          // 必须用这个，不要手动翻转 CTM
let data = rep.representation(using: .png, properties: [:])
```

### 5.4 边缘吸附（左右）

```swift
// 判定
let candidates: [(Edge, CGFloat)] = [
    (.left,  frame.minX - visible.minX),
    (.right, visible.maxX - frame.maxX)
]
guard let best = candidates.min(by: { $0.1 < $1.1 }), best.1 <= 28 else { return nil }

// 指示器窗口位置（48 宽，藏 24 → 只露一半，正中心落在屏幕边缘）
case .left:  x = visible.minX - 24 + peek
case .right: x = visible.maxX - 48 + 24 - peek

// 交互：mouseEntered → 窗口外探 14pt；mouseUp 未拖动 → undock；拖动 → 沿边移动 + 更新 anchor
```

### 5.5 拖动/缩放/点击共存

- 按下记录起点，移动 >2pt 才算拖动（避免点击误判）。
- 拖动中直接用 `NSWindow.setFrameOrigin` 跟随鼠标，结束后判定吸附 / 保存位置。
- `scrollWheel`：⌥ 或 ⌘ 按下才缩放，否则忽略（避免误触）。
- 所有视图 `acceptsFirstMouse → true`，否则非激活窗口第一次点击被吞。

### 5.6 打包（通用二进制 + ad-hoc）

```bash
swiftc -O -swift-version 5 -module-cache-path build/ModuleCache \
  -target arm64-apple-macos12.0 -framework Cocoa -o build/BalancePet-arm64 Sources/*.swift
swiftc ... -target x86_64-apple-macos12.0 -o build/BalancePet-x86_64 Sources/*.swift
lipo -create -output 余额兔.app/Contents/MacOS/BalancePet build/BalancePet-arm64 build/BalancePet-x86_64
xattr -cr 余额兔.app && codesign --force --deep --sign - 余额兔.app
```

---

## 6. 踩坑记录（重要，做同类项目必看）

| 现象 | 原因 | 解法 |
|---|---|---|
| swiftc 报 “SDK is not supported by the compiler” | 沙盒下默认 module cache（`/var/folders`）不可写，报错被伪装 | 加 `-module-cache-path build/ModuleCache` |
| `codesign` 报 “resource fork, Finder information…” | 文件带扩展属性 | 签名前 `xattr -cr <app>`（拷贝后也要重做） |
| 离屏渲染的图上下颠倒 / 文字 180° | 手动翻转 CTM | 用 `cacheDisplay(in:to:)`，不要手动翻转 |
| 离屏渲染颜色是白的 | 动态色（`.labelColor` 等）在离屏上下文解析为白 | 预览/固件配色一律用 `NSColor(calibrated...)` 固定色 |
| `screencapture` 失败、`ps` 无法用 | DSH 沙盒限制 | 自编译 CGWindowList 小工具（`build/winlist2`）查窗口坐标 |
| 合成 CGEvent 拖动无效 | 需要辅助功能权限 | 用临时 `UserDefaults` 自检钩子自动执行 dock/undock 并写日志 |
| 开机自启 + 手动双击 → 两只兔子 | 两个进程 | flock 单实例 + DistributedNotification 唤起 |
| 深色模式下气泡配色异常 | 系统动态外观 | 面板强制 `appearance = .aqua`，所有颜色固定值 |
| 非激活面板第一次点击无效 | `acceptsFirstMouse` 默认 false | 视图重写返回 true |
| `hdiutil create` 报「目录非空」 | 沙盒禁止挂载磁盘镜像 | 打包脚本降级为 zip（`ditto -c -k`） |
| 别人 Mac 上打不开 app | ad-hoc 签名 + 下载隔离 | 使用说明里写「右键→打开」或 `xattr -dr com.apple.quarantine` |
| 气泡显示「账号已停用」但账号实际可用（v1.2.2） | `/v1/account/balance` 的 `is_active` 字段语义不明，部分账号可用却返回 false | 不再气泡告警，只在右键菜单灰色提示；停用改由接口 403 的横幅体现。要确认语义得问服务端 |
| 朋友双击报「Apple 无法验证…」只有「完成/移到废纸篓」（v1.2.1） | macOS 15/26 取消了未签名 App 的右键打开入口，弹窗没「打开」按钮 | 用说明写清：系统设置 → 隐私与安全性 → 滚到底 →「仍要打开」；或 `xattr -dr com.apple.quarantine`。根治需 Apple Developer 签名+公证 |
| 全屏 App 下只看到兔子、看不到气泡（v1.1.1） | 气泡窗口第一次 `orderFront` 发生在全屏 Space 期间，macOS 把它分到桌面 Space；兔子是启动时就已入场，所以正常 | 气泡窗口改为**常驻**（启动即 `orderFrontRegardless`，`alphaValue=0` + `ignoresMouseEvents=true`），显隐只用 alpha；并临时 `addChildWindow` 挂到兔子窗口上，保证同 Space |

---

## 7. 分发包结构（v1.1.0 起）

`dist/` 里**只有一个**带版本号的 zip，版本号自动取 `Info.plist`：

```
余额兔-v1.1.0-macOS.zip
├── 余额兔.app            # arm64 + x86_64 通用，LSMinimumSystemVersion 12.0，ad-hoc 签名
└── 使用说明.txt          # 安装（右键打开/清隔离）+ 首次填 Key + 功能 + 卸载
```

- 不再单独发 app、不再生成 `安装.command`、不再尝试 dmg（沙盒里必然失败）。
- zip 用 `ditto -c -k --norsrc --noextattr`：不写 AppleDouble，解压后 `codesign --verify` 仍通过。
- 核对方法：解压到临时目录 → 跑 `--stats` → `codesign --verify --strict`。

---

## 8. 复用清单：在这个工作区做另一个 macOS 挂件 App

按顺序照抄即可：

1. **目录**：`<name>/Sources/*.swift` + `Info.plist` + `build.sh`（复制本项目的 build.sh 改 app 名/二进制名）。
2. **入口**：`main.swift` 保留 CLI 分支（`--stats/--render`）+ `SingleInstance.claim()` + `.accessory`。
3. **窗口**：一律用 5.1 的 `NSPanel` 配置函数化封装，浮动 + 全桌面 + 不抢焦点。
4. **绘制**：`NSView.isFlipped = true` + `NSBezierPath` 矢量绘制 + 30fps Timer 的 `phase` 动效；
   所有颜色写死，不用动态色。
5. **配置**：`Settings` 单例包一层 UserDefaults，每个属性 set 时发 `.settingsChanged` 通知。
6. **预览**：加 `--render <dir>` CLI，用 `cacheDisplay` 出 PNG，方便在无 GUI 的环境里检查设计。
7. **状态栏**：`NSStatusItem` 放金额/状态文字；右键菜单用 `NSMenu.popUpContextMenu`。
8. **打包**：`package.sh` 复制本项目；版本号取 Info.plist；通用二进制 + `xattr -cr` + ad-hoc 签名 +
   `ditto --norsrc` 出单个带版本 zip（只放 app + 使用说明）。
9. **验证**：`build/winlist2 <pid>` 查窗口坐标；临时自检钩子验证交互几何；验证完删钩子重编译。
10. **文档**：在本工作区 `AGENTS.md` 追加项目记忆（路径、命令、决策、坑）。

---

## 9. 变更记录

- v1.0：桌面兔子 + 余额气泡 + 菜单栏 + 定时刷新 + 低余额提醒 + 缩放 + 开机自启。
- v1.1：边缘吸附（左右）+ 4 种电子风指示器，默认「箭头标签」；底部吸附取消。
- v1.2：通用二进制 + 一键安装包，可分发给同事。


## 11. v1.1.0：同步 Windows v1.0.5 的全部改进（2026-10-20）

对照 `../余额兔-Windows改进记录-供macOS同步.md` 逐条落地，验收结果：

| 验收项 | macOS 做法 | 结果 |
|---|---|---|
| Key 按人隔离 | `Credentials.apiKey()` 只读 env + 当前用户 Keychain，删除 `~/.dsh/.credentials.yaml` 静默回退；首启弹「填写你自己的 rabbitj.top API Key」，旧共享 Key 仅在对话框里预填、必须点保存 | ✅ |
| 升级/换人确认 | `Settings.lastRunVersion` 与 `appVersion()` 不同 → 弹「余额兔 · 确认账号」，默认按钮「否，重新填写」 | ✅ |
| 菜单显示 Key 归属 | 「当前 Key 尾号 …XXXX」「账户 #id」「更换 API Key（换账号）…」「关于账号与 API Key…」 | ✅ |
| `/v1/balance` 优先 | `APIClient.fetchBalance()` 容忍 `data` 嵌套/`balance` 别名，失败静默；余额优先接口值，其次最新流水 `balance_cny` | ✅（线上仍 404，回退已验证） |
| 多账户过滤 | usage 项带 `user_id` 时按账户过滤，出现他人记录 → `multipleAccounts=true`、`totalRequests=nil`、气泡/菜单提示 | ✅ |
| 排版不压字 | 设计画布 300×282 定点坐标 + `fitFont` 实测宽度逐级缩字号；余额/概览/Token/模型/页脚全部实测 | ✅（预览图核对） |
| 峰值标签 | 实测宽度、居中在最高柱上方、夹在卡片内；柱最大高度 28 | ✅ |
| 柱状图交互 | 悬停高亮 + 页脚「M/d 花费 ¥x · N 次」；点击选中、再点取消；点卡片其他区域刷新；`onInteraction` 重置自动隐藏 | ✅（预览图核对 hover 态） |
| 不点穿 | `panel.ignoresMouseEvents = false` + `hitTest` 返回自身 + `orderFrontRegardless`；点尖角/边距关闭气泡 | ✅ |
| 刷新失败保留旧数据 | catch 里复制旧 `stats` 只覆盖 `error`，气泡底部红色「⚠ 刷新失败」横幅 | ✅ |
| 多屏/混合缩放 | 吸附时记 `dockScreen`，吸附/弹出/气泡/拖动都用它；监听 `didChangeScreenParametersNotification`，兔子跑出屏幕自动复位；菜单「把兔子放回屏幕右下角」、双击菜单栏金额召回当前屏 | ✅ |
| 设置降级 | `AppStorage` 依次试 Application Support → Caches → 临时目录，全不可写时内存运行 + 一次性提示；设置本身走 UserDefaults（系统保证可写） | ✅ |
| 分发 | `package.sh` 只出 `dist/余额兔-v1.1.0-macOS.zip`（app + 使用说明.txt），版本号取 Info.plist | ✅ |

关键实现点：

- 气泡坐标全部相对 `cardRect`，柱状图几何封成 `ChartGeometry`（`chartTop = 卡片顶+102`、
  `baseline = chartTop+40`、`barMaxHeight = 28`、`slot = 250/7`），绘制与命中检测共用。
- 悬停用 `NSTrackingArea(.mouseMoved, .activeAlways)` + `panel.acceptsMouseMovedEvents = true`，
  光标在图表区变手型。
- `BubbleView.draw()` 不再用「错误就整屏替换」，有旧数据时继续画内容，错误放页脚，
  只有一次性失败（没有历史数据）时才显示「—」。
- 吸附屏幕要单独存：`petPanel` 隐藏后 `screen` 不可靠，`undock()` 必须在清 `dockScreen` 前
  算好弹出坐标。


## 12. v1.1.1：修「全屏软件下看不到余额气泡」

现象：桌面 Space 下一切正常；切到全屏 App 后兔子还在，点兔子没有气泡。

根因：窗口能否出现在别人的全屏 Space 里，取决于它是否已经“加入”那个 Space。
兔子窗口在启动时就 `orderFrontRegardless`，配合 `.canJoinAllSpaces + .fullScreenAuxiliary`
会出现在所有 Space；而气泡窗口平时 `orderOut`，第一次 `orderFront` 恰好发生在全屏 Space 里，
macOS 会把它分到 App 所在的桌面 Space，于是全屏下不可见。

修法（已落地）：

1. `buildBubbleWindow()` 末尾就 `orderFrontRegardless()`：窗口常驻，`alphaValue = 0`、
   `ignoresMouseEvents = true`，视觉上不存在、也不挡鼠标，但已经进入所有 Space。
2. 显隐只动 `alphaValue`（0.16s 淡入 / 0.15s 淡出），不再 `orderOut`；
   隐藏完成后恢复 `ignoresMouseEvents = true`，否则透明窗口会挡住兔子和菜单栏点击。
3. 逻辑显隐状态单独记 `bubbleVisible`，不要再用 `bubblePanel.isVisible`（窗口现在一直 isVisible）。
4. 兜底：显示时 `addChildWindow(bubblePanel, ordered: .above)` 挂到兔子（吸附时是边缘图标）窗口上，
   子窗口必然和父窗口同 Space；隐藏时 `removeChildWindow`。
5. 布局仍用 `bubblePanel.setFrame`，常驻不影响位置计算；显示器变化时只在实际展开时重排。

验证：临时 `debugShowBubble` UserDefaults 钩子让 App 启动后自动展示/收起，
日志确认 `visible=false alpha=0.0`，CGWindowList 里气泡窗口 `onscreen=1 alpha=0.0`（常驻透明）。
全屏场景需人工确认（沙盒内无法自动进入全屏 Space）。


## 13. v1.2.0：接入官方账户接口（余额 + 按日花费）

网站开发者 2026-10 提供了两个用户态只读接口，v1.2.0 起作为主数据源：

```
GET /v1/account/balance            → user_id / balance_cny / is_active
GET /v1/account/spending?from&to   → totals{request_count, charged_cny, recharged_cny, tokens} + balance_cny + days[]
```

改动要点：

1. `APIClient.loadStats()` 分两条路：
   - **account 路径（新）**：`async let` 并发拉 balance、spending（近 7 天，含今天）、
     最近 2 页 `/v1/usage`（只为「累计请求数 total」和模型分布）。整轮刷新 5 个请求、
     实测 0.65 秒；过去翻 25 页要好几秒。
   - **usage 路径（旧，回退）**：两个新接口任一不可用（404/503）时，走原来的翻页聚合，
     保留 `partial`、多账户过滤等逻辑。
2. 余额优先级：`spending.balance_cny` → `/v1/account/balance` → `/v1/balance`（仍 404）。
3. 逐日柱状图直接用 `days[]`（服务器已按天切好、空天补 0），不再本地按 `created_at` 分组。
4. 新增展示：`recharged_cny > 0` 时菜单显示「近 7 天充值 ¥170.00」；
   `is_active` 语义未知（v1.2.2 起）不再当停用告警，只在右键菜单留一行灰色提示。
5. 模型统计改为「最近 1~2 页流水」的分布，气泡文案改成「近期主力模型」，
   不再声称是 7 天全量（7 天总额/次数由 spending 提供，准确）。
6. `Stats` 增加 `dataSource`（account/usage）、`accountInactive`、`weekRecharged`；
   `--stats` 会打印这些字段，便于核对是否走了新接口。

数据口径提醒（写入 AGENTS 第 5 节）：spending 只统计 `status = billed`；日期按服务器本地时间
切分；区间跨度 ≤366 天；余额是实时值，不由明细累加；请求落库到计费完成有短暂延迟。

## 14. v1.2.3：按服务器时区切天（2026-10-20）

Linux 版核验时发现「今日 / 近 7 天」窗口按**本机时区**算，而服务器按 Asia/Shanghai 切天；
在非东八区机器上（或跨时区出差）今天的花费会整体错一天。macOS / Windows 同步修正：

- 固定 `+08:00` 服务器时区：macOS 用 `APIClient.serverTimeZone` / `serverCalendar`，
  Windows 用 `APIClient.ServerTimeZone` / `ServerToday()`。
- 日期格式化（`yyyy-MM-dd`）、`spending.days[]` 解析、`created_at` 归类、回退翻页的
  7 天窗口全部走服务器日历；macOS 柱状图 `M/d` 标签也按服务器时区显示。
- 验证：`TZ=Pacific/Honolulu` 下 `--stats` 的日期/金额与 `TZ=Asia/Shanghai` 完全一致。

## 15. v1.2.4：桌面兔子改为圆框脸（四套造型可选）

原站立兔子在 Windows 上层窗口被裁掉耳朵（分层窗口位图固定、绘制超出即裁）。借这次重做形象：
只保留一张圆脸 + 短耳，装在圆形相框里，正方形画布内构图，三端统一。

- 设计画布仍是 160×160，圆框中心 (80, 84)，半径 63.5，脸 (36.5,59)-(123.5,142)，耳朵短胶囊
  （约 16.5×52，外倾 11°）。所有元素都在 0..160 内，不再出现负坐标。
- 四套造型共用同一套几何，只换配色/表情/描边：
  `cream` 奶油软萌（默认，暖米底 + 胡须 + ω 嘴）、`sky` 蓝色圆环 + 弯弯眼、
  `line` 细线手绘（深棕描边）、`chibi` 粉腮 + 大眼 + O 嘴。
- 菜单「兔子造型」四选一，设置项 `petFaceStyle`（macOS UserDefaults / Windows
  `pet_face_style` / Linux `pet_style`），重启保留；旧的站立兔子不再保留。
- 动画保留：呼吸、眨眼（弯弯眼款不眨眼）、耳朵轻摆、加载小跳、悬停放大；
  低余额感叹号移到圆框右上角。
- 应用图标、预览图同步改成圆脸；`--render` 现在输出 `pet_cream/sky/line/chibi.png` 四张。

## 16. v1.3.0：macOS 兔子改为固定图片（只留「蓝色圆环 · 弯弯眼」，箭头标签）

用户要求：四套造型只留 **sky（蓝色圆环 · 弯弯眼）**；吸附图标只留 **箭头标签**；
兔子形象导出成固定图片，App 里不要再逐坐标画，动画**完全静态**；先只改 macOS。

- 资源管线：`Tools/Artwork.swift`（只画 sky，含低余额 `!`）+ `Tools/main.swift`
  （离屏渲染）→ `./export_assets.sh` 产出
  `Assets/pet_sky.png`、`Assets/pet_sky_low.png`（768×768 透明 PNG，= 160 设计画布 × 4.8）
  和 `build/preview/icon_1024.png`。Tools 不参与 App 编译，`build.sh` 只编译 `Sources/*.swift`。
- 运行时：`PetView` 用 `Bundle.main` 加载两张 PNG（`Contents/Resources/`），
  `draw` 里只做 `NSImage.draw(in:from:operation:fraction:respectFlipped:true, hints:.high)`；
  没有 Timer / phase / 矢量化。低余额只是换成带 `!` 的那张图。
- 删除 `PetFaceStyle`、`DockIndicatorStyle`、`Settings.petFaceStyle/dockStyle`、
  「兔子造型」「边缘图标样式」菜单、`DockView` 另外三种样式；`--render` 输出
  `pet.png / pet_low.png / dock_arrowTab_left|right.png / icon_1024.png` + 气泡预览。
- 为什么要这样：Windows 端的耳朵错位根因是 GDI+ `Matrix` 默认 Prepend，
  `Rotate` 后 `Translate` 会变成「先平移再绕画布原点旋转」；三端绘制语义不同，靠逐端修代码永远有下次。
  图片方案把「长什么样」固定在生成阶段，三端只贴图，从根上消除这类差异。
- 版本 1.3.0；Windows / Linux 暂未同步（仍是四套造型 + 四种吸附图标的代码绘制）。
