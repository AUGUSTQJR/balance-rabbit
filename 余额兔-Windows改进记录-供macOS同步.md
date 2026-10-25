# 余额兔 Windows 版改进记录（供 macOS 版同步）

> **macOS 落地状态（2026-10-20，v1.1.0）**：本文 12 条验收项已全部在 macOS 版实现并通过核对，
> 产物 `pet/dist/余额兔-v1.1.0-macOS.zip`；逐条做法与验证见 `pet/DESIGN.md` 第 11 节。


> 用途：本文件把「从 macOS 版移植到 Windows 之后，用户提的每一条意见 + 根因 + 最终做法 + 关键数值」
> 完整记录下来。macOS 版要让用户达到和现在 Windows 版一样的效果，按本文第 4 节逐文件改即可。
>
> 当前 Windows 版：v1.0.5；分发只有一个文件 `余额兔-v1.0.5-Windows-免安装.zip`
> （内含 `余额兔-v1.0.5.exe` + `使用说明.txt`）。

---

## 0. 一句话结论

Windows 版 = macOS 原版功能 + 下列改动：**Key 严格按人隔离**、**余额优先走 `/v1/balance` 并按
`user_id` 过滤流水**、**高 DPI/任意分辨率下文字不压不截**、**峰值标签实测定位**、**柱状图可悬停/点击
查看当天花费**、**气泡卡片不点穿**、**多屏/混合 DPI/显示器变化不跑丢**、**刷新失败保留旧数据**、
**设置目录不可写时降级并提示**、**只发带版本号的免安装 zip**。

---

## 1. 最终用户可见效果（验收口径）

| # | 效果 | 验收方法 |
|---|---|---|
| 1 | 每台电脑/每个 Windows 用户用自己的 Key，不会再显示别人的余额 | 新机器首启必须填 Key；菜单能看到「当前 Key 尾号」 |
| 2 | 用旧 Key 升级/换人使用时会被询问是否换 Key | 安装/升级后首启弹「确认账号」，默认按钮是「否」 |
| 3 | 换 Key 后余额立即按新账号显示 | 菜单「更换 API Key（换账号）…」→ 保存后刷新 |
| 4 | 任意 DPI/分辨率下气泡文字不截断、不重叠 | 125% / 150% / 200% 缩放、4K 屏各看一次 |
| 5 | 「峰值 ¥xx」永远在最高柱上方，不压柱子 | 最高柱在左/中/右三种情况各看一次 |
| 6 | 柱状图可悬停/点击，显示「10/14 花费 ¥0.32 · 24 次」 | 鼠标移过柱子、点击柱子；再点一次取消 |
| 7 | 点气泡卡片不会点到背后的窗口 | 气泡盖在记事本/浏览器上连点，背后不应有反应 |
| 8 | 多显示器/混合 DPI 下气泡缩放正确、吸附在兔子所在屏 | 双屏不同缩放拖动兔子、左右吸附 |
| 9 | 拔显示器/改分辨率后兔子不会跑出屏幕 | 菜单「把兔子放回屏幕右下角」可复位 |
| 10 | 断网刷新时保留上一次数据并提示错误 | 断网后点刷新/等自动刷新 |
| 11 | 设置/Key 存不下时仍能用（内存模式）并托盘提示 | 把程序放无写权限目录运行 |
| 12 | 分发只有一个带版本号的 zip，双击 exe 即用 | 解压 → 双击 → 过 SmartScreen → 填 Key |

---

## 2. 变更明细（问题 → 根因 → 最终做法）

### A. 账号与 Key（最重要）

**A1. 朋友装完显示的是发送人的余额（2026-10-19）**
- 根因：旧版 Key 解析除了本机保存的 Key，还会回退读共享文件 `~/.dsh/.credentials.yaml`；
  同一台电脑沿用旧 Key 时也没有任何确认，安装包不区分使用者。
- 最终做法（Windows）：
  1. **删除 `~/.dsh/.credentials.yaml` 回退**；
  2. 优先级只剩：当前用户在**本机 DPAPI（CurrentUser）加密保存的 Key** → 环境变量 `RABBIT_API_KEY`；
  3. 安装/升级时安装器写 `%APPDATA%\BalanceRabbit\just-installed.txt`，应用首启读取后删除；
     若已存在 Key，弹「余额兔 · 确认账号」：
     「检测到本机已保存 API Key（尾号 …XXXX）。如果这台电脑现在换别人使用，继续用这个 Key 会显示
     原来账号的余额。要继续使用这个 Key 吗？」默认按钮为「否」，选「否」→ 重填；
  4. 菜单显示「当前 Key 尾号 …XXXX」（后 4 位）；
  5. 有 Key 时菜单项为「更换 API Key（换账号）…」，无 Key 时「设置 API Key…」；
  6. Key 对话框标题「填写你自己的 rabbitj.top API Key」，说明「每个 Windows 用户 / 每台电脑都要填
     自己的 Key…填了别人的 Key 就会显示别人的余额」。
- macOS 落点：`Credentials.swift` 删 yaml 兜底；`AppDelegate` 首次启动确认；菜单项与文案；
  Keychain item 本身按用户隔离，无需额外处理。

**A2. 站长/管理员 Key 会看到多账户流水，余额显示成别人（2026-10-20）**
- 背景：网站开发者反馈：换了站长 Key 仍显示用户的余额（¥82.96）。站长的 `/v1/usage`
  会返回多个账户的记录；app 取「最新一条流水的 balance_cny」当余额，最新的一条恰好是别人的。
- 站长确认：网站**没有**单独的余额查询接口，余额只能从 usage 流水推断；同意新增
  `GET /v1/balance`（Bearer Key）返回 `{"user_id":132,"balance_cny":82.96}`。
- 最终做法（Windows v1.0.5，已预接，接口上线自动生效）：
  1. 每次刷新先试 `GET /v1/balance`；解析 `balance_cny`（兼容 `balance`），`user_id`（兼容
     `account_user_id`），支持 `{"data":{...}}` 嵌套；404/失败**静默回退**旧逻辑；
  2. 有账户 id 时，`/v1/usage` 的记录按 `user_id` 过滤后再聚合（今日/7 天/token/模型/余额）；
     多账户时 `TotalRequests` 置空（全站口径没意义）；
  3. `/v1/balance` 存在时余额以它为准，usage 没记录也不再报「无记录」；
  4. 菜单显示「账户 #132」；多账户时显示
     「⚠ 当前 Key 可见多个账户数据（余额以 /v1/balance 为准）」。
- macOS 落点：`APIClient.swift` 加 `fetchBalance` + 过滤；`Models.swift` 加 `AccountUserId` /
  `MultipleAccounts` / `UsageItem.UserId` / `BalanceInfo`；菜单加账户行。

### B. 网络与数据聚合

- 刷新失败时**保留上一次成功的数据**（余额/今日/7 天/token/模型），只把 `Error` 显示出来；
  不要清空成「—」。
- `/v1/usage?limit=200&offset=N&status=billed`，每页 200，最多 25 页（>5000 条标 `partial`）。
- 余额 = 最新一条已计费记录的 `balance_cny`（无 `/v1/balance` 时）；有接口则用接口值。
- 今日/近 7 天 = 按 `created_at` 落在窗口内的 `charged_cny` 求和；token = input+output+cache_read+cache_write；
  模型次数取 top3，主力模型显示「模型（N 次）」。
- `partial` 时气泡底部显示「记录过多，近 7 天统计已截断」。
- macOS 落点：`APIClient.swift` + `Models.swift`；`AppDelegate` 错误分支改为复制旧 stats 再写 Error。

### C. 高 DPI / 文字截断（2026-10-19 截图反馈）

- 症状：125%/150% 缩放下气泡里余额、概览、底部文字被截断或互相压。
- 根因：字体按 point 设计又乘了 DPI（`*72/96`），等于二次放大；位图没固定 96 dpi。
- 最终做法：
  1. `Paint.Font` 全部用 `GraphicsUnit.Pixel`，删掉 `*72/96`；
  2. `CreateCanvas` 对位图 `SetResolution(96f, 96f)`；
  3. 整个气泡按设计画布 **300×282** 统一 `ScaleTransform(scale, scale)`，所有坐标都是设计像素；
  4. 窗口尺寸 = 设计尺寸 × `DpiScale`；`DpiScale` 用 `GetDpiForWindow`；
     跨屏/气泡定位用 `GetDpiForMonitor`（shcore）+ `MonitorFromRect`（`LayeredForm.ScaleForRectangle`）；
  5. 文本矩形按实测留余量（示意）：余额 `top+31` 高 48；概览 `top+80` 高 20；
     底部行 `top+238` 高 15；日期标签 `baseline+4` 高 14。
- macOS 落点：`BubbleView` 用 `NSString.size(withAttributes:)` 实测后布局，不再写死宽度；
  retina 用 `convertToBacking`，不要二次缩放。

### D. 「峰值」标签压柱子（2026-10-20 截图）

- 症状：`峰值 ¥83.06` 和最高柱（10/19）重叠；换台电脑也可能叠，只是位置不同。
- 根因：标签写死在 `(200, chartTop-4, 74×12)`，最高柱可到 `chartTop+2`，天然重叠；
  **与分辨率无关，是固定坐标问题**。
- 最终做法（v1.0.5）：
  1. 柱最大高度 **38 → 28**；
  2. 峰值文字先测量（`Graphics.MeasureString`），宽 = `min(250, 实测宽+2)`，高 = `clamp(12..16)`；
  3. 位置：右对齐 `x = 24 + 250 - 宽`，`y = baseline - 28 - 高 - 2`（永远在最高柱上方 2px）；
  4. 右对齐且不越出左右边界，数字再长也不会裁掉。
- macOS 落点：`BubbleView` 同样「实测 + clamp + 柱高 28」。

### E. 柱状图交互（2026-10-20 需求）

- 需求：点击某天的柱子，显示当天消耗；鼠标悬停也要有反馈。
- 最终做法：
  1. 几何（设计坐标）：图表左 24、宽 250、`chartTop = 卡片顶+102`、基线 `chartTop+40`、
     柱宽 18、最大高 28、日期标签 `baseline+4`；
  2. 命中区：`x ∈ [24,274]`、`y ∈ [chartTop-4, baseline+16]`（含日期行），
     `day = (x-24) / (250/7)`；
  3. 悬停：柱子变蓝（今天本来就是蓝）、日期变深、底部左侧显示
     「10/14 花费 ¥0.32 · 24 次」；光标变手型；
  4. 点击：固定选中，再点同一天取消；点图表外仍走原来的「刷新」；
  5. 选中/悬停都高亮，气泡关闭时清空状态。
- macOS 落点：`BubbleView` 加 `NSTrackingArea` + `mouseMoved`/`mouseDown`，`BubbleWindow` 对应
  `hoverDay/selectedDay`；绘制函数加两个参数。

### F. 气泡点击穿透（2026-10-20 反馈）

- 症状：点信息框，背后的窗口也响应（分层窗口按像素 alpha 做命中，系统/驱动/远程桌面下不一致）。
- 最终做法：
  1. 覆写 `WM_NCHITTEST`：卡片矩形（`x 2..298`，`y cardTop..cardTop+256`）和尖角包围盒内返回
     `HTCLIENT`，其余返回 `HTTRANSPARENT`（圆角/阴影外才放行）；
  2. `ShowAt` 后 `BringToFront()`，避免被别的置顶窗口压住/抢点击。
- macOS 落点：确认 `NSPanel.ignoresMouseEvents = false`、`NSView.hitTest` 覆盖卡片、
  `orderFrontRegardless()`；不要给气泡设 `ignoresMouseEvents`。

### G. 托盘 / 多屏 / 吸附 / 显示器变化

- 托盘双击：用 `SystemInformation.DoubleClickTime` 定时器区分单击/双击，双击把兔子显示到当前屏；
  避免一次双击触发两次。
- 吸附：开始吸附时记录 `dockWorkArea`（兔子当前所在屏的工作区），之后 `PositionDock`/`Undock`/
  拖动都用它 + `ScaleForRectangle`，不用 `Screen.FromRectangle`（混合 DPI 会取错屏）；
  气泡也按目标工作区缩放。
- 显示器变化：订阅 `SystemEvents.DisplaySettingsChanged`（退出时取消订阅）；
  实现 `ClampPetOnScreen`（部分可见即可）、`IsPetVisibleOnAnyScreen`、`ShowPetAnywhere`、
  `ResetPetPosition`（主屏右下角）；菜单加「把兔子放回屏幕右下角」。
- 混合 DPI：`GetDpiForMonitor` + `MonitorFromRect`。
- macOS 落点：`NSApplication.didChangeScreenParametersNotification`；吸附用当时 `NSScreen`；
  clamp 兔子坐标；菜单项；`NSStatusItem` 双击检测。

### H. 设置存储与开机自启可靠性

- 设置目录探测顺序（Windows）：
  `%APPDATA%\BalanceRabbit` → **exe 旁 `BalanceRabbit-data`（便携）** →
  `%LOCALAPPDATA%\BalanceRabbit` → `%TEMP%\BalanceRabbit`；
  每个候选写 `.write-test-<guid>` 探针，成功才用；全部失败 → 用默认路径并把 `StorageWritable=false`，
  **内存运行**（能查余额，设置/Key 不保留）。
- 不可写时托盘气泡：
  「当前安全策略禁止写入设置文件，API Key 与设置只能本次运行有效。建议把 BalanceRabbit.exe
  放到下载 / 桌面 / D 盘等可写目录，或让安全软件放行。」
- 保存用原子写：先写 `.tmp`，再 `File.Replace(..., ".bak")`，失败回退删除/移动。
- 开机自启写 HKCU Run；判断是否启用时对注册表路径 `Trim('"')` + `Path.GetFullPath` 与当前 exe 比较。
- macOS 落点：Application Support 写失败 → Caches → 内存 + 提示；`NSUserDefaults` 原子写；
  LoginItem 校验当前路径。

### I. 分发方式（Windows 特有，记录演变）

- 安装包历史：默认装 `%LOCALAPPDATA%\Programs\BalanceRabbit` → 被安全软件拦 →
  9 个候选目录 + 日志 `%TEMP%\BalanceRabbit-install.log` + 管理员重试 + 安装界面「更改安装位置…」
  （可选 D 盘）→ 仍可能被拒（受控文件夹访问/360/火绒/公司 EDR/WDAC）。
- **最终决定：不再分发安装包**。只发带版本号的免安装 zip：
  `余额兔-vX.Y.Z-Windows-免安装.zip`（内含 `余额兔-vX.Y.Z.exe` + `使用说明.txt`）；
  `dist/` 里不再单独放 exe，也不默认构建安装包（`WITH_INSTALLER=1` 才构建）。
- `build.sh` 从 csproj `<Version>` 取版本号命名，旧版本文件不会被覆盖，一眼能看出版本。
- 使用说明要点：先建 `D:\余额兔\` 这类非系统盘目录再放 exe；不要放桌面/C 盘（安全软件易拦写入、
  易误删）；升级时换新 exe，设置保留；SmartScreen「更多信息 → 仍要运行」。
- macOS 落点：`package.sh` 产物改成 `余额兔-vX.Y.Z-macOS.zip`（内含 app + 使用说明）；
  说明同样写版本号；不要单独分发 app 或旧的无版本文件。

### J. 版本历史（Windows）

- **1.0.0**：初版移植（WinForms 分层窗口、托盘、气泡、左右吸附、开机自启、单实例、安装包）。
- **1.0.2**：高 DPI 字体/布局修复；安装目录可选；失败日志 + 管理员重试。
- **1.0.3**：Key 按 Windows 用户隔离（删共享文件回退）、首启确认、菜单 Key 尾号、更换 Key。
- **1.0.4**：安全软件拦截下的安装/存储降级（便携数据目录、内存模式、托盘提示）。
- **1.0.5**：预接 `/v1/balance` + 多账户过滤（账户 #id）；峰值标签实测定位；柱状图悬停/点击；
  气泡卡片显式命中不穿透；只发版本化免安装 zip。

---

## 3. 手动验收清单

1. 新机器（无 Key）：首启必须弹出 Key 对话框；填完显示自己余额。
2. 换 Key：菜单「更换 API Key（换账号）…」→ 尾号变化；不同账户余额应变化。
3. 带旧 Key 升级：存在安装标记 → 弹「确认账号」；选「否」能重填。
4. 125% / 150% / 200% 缩放、4K：气泡文字不截断、不重叠；「峰值」不压柱。
5. 柱子悬停：出现「M/d 花费 ¥x · N 次」；点击固定；再点取消；点空白刷新。
6. 气泡盖在记事本/浏览器上连点：背后窗口不响应。
7. 双屏不同缩放：气泡在兔子所在屏正确大小；吸附在正确屏边缘。
8. 拔显示器/改分辨率：兔子不出屏；菜单可复位到右下角。
9. 断网刷新：保留旧数据 + 错误提示，不清空。
10. 设置目录不可写：托盘警告；程序仍能本次使用。
11. 重启：设置/Key 保留；开机自启路径正确。
12. 解压 zip → 双击 exe → SmartScreen 仍要运行 → 填 Key，即可用。

---

## 4. macOS 版逐文件同步清单

> 前提：macOS 版现有功能（吸附只左右、箭头标签、菜单栏金额、Keychain、单实例、开机自启）
> **不要破坏**，只在其上增改。

**`pet/Sources/APIClient.swift`**
- 新增 `fetchBalance(key)`：GET `/v1/balance`，解析 `balance_cny`/`balance`、`user_id`/`account_user_id`，
  支持 `data` 嵌套；失败返回 nil，不抛错。
- `loadStats`：先取 balance（拿 accountUserId）；有 id 时过滤 usage 记录的 `user_id`；
  余额优先用接口值；无记录但有余额接口时不再报「无记录」；多账户时总请求数置空。
- 刷新失败：保留上一次 stats，仅写 error。

**`pet/Sources/Models.swift`**
- `Stats` 加 `accountUserId: Int?`、`multipleAccounts: Bool`。
- `UsageItem` 加 `userId: Int?`（解析 `user_id`）。
- 新增 `BalanceInfo { balance: Double; userId: Int? }`。

**`pet/Sources/Credentials.swift`**
- 删除 `~/.dsh/.credentials.yaml` 回退；只读当前用户 Keychain（+ `RABBIT_API_KEY` 环境变量）。
- 提供 `hasKey`、`keyHint`（后 4 位，形如 `…4590`）。

**`pet/Sources/AppDelegate.swift`**
- 首启：若已有 Key 且是「刚安装/更新」（可用安装标记或版本变化判断），弹确认框，默认「否」→ 重填。
- 菜单：「更换 API Key（换账号）…」/「设置 API Key…」+「当前 Key 尾号 …」+「账户 #…」；
  多账户时提示。Key 对话框文案同第 A1 条。
- 刷新失败保留旧 stats。
- 显示器变化通知 → clamp 兔子、允许复位；菜单「把兔子放回屏幕右下角」。
- 托盘双击（双击显示兔子），单击/双击用系统双击间隔区分。
- 吸附开始记录所在 `NSScreen`，后续吸附/拖拽/气泡都用它，避免混合缩放取错屏。

**`pet/Sources/BubbleView.swift`**
- 峰值标签：实测文字宽高（`NSString.size(withAttributes:)`），右对齐、clamp 在气泡内；
  柱最大高度 28（设计点），标签画在最高柱上方 2pt。
- 柱状图交互：`NSTrackingArea` + `mouseMoved`/`mouseDown`；命中 `x∈[24,274]`、
  `y∈[chartTop-4, baseline+16]`；底部显示「M/d 花费 ¥x · N 次」；选中高亮、再点取消。
- 文本布局全部按实测宽度，不要写死会压字的矩形；设计画布 300×282，retina 只做整体 scale。
- 卡片 hitTest 返回自身（尖角范围内也算），确保点击不穿透到背后窗口。

**`pet/Sources/Support.swift`**
- 设置原子写；数据目录写失败降级（Application Support → Caches → 内存）并提示一次；
- 统一 `BalanceRabbit/1.0 (Windows)` 之外的 User-Agent 不需要改。

**`pet/package.sh`**
- 产物命名 `余额兔-vX.Y.Z-macOS.zip`；zip 内含使用说明；版本号来源统一（避免旧文件覆盖）。
- `DESIGN.md` / `README` 里补充 vX.Y.Z 变更说明。

**`pet/Sources/` 里不要动的既有行为**
- 吸附只有左右边缘；吸附图标为箭头标签；点击兔子弹气泡；菜单栏 `¥xx.xx`；单实例；
  边缘图标样式菜单；`Esc`/点击别处行为等。

---

## 5. 构建与验证备注

- Windows：`cd windows && ./build.sh`（macOS 交叉编译，net48 参考程序集由 NuGet 还原）；
  产物只有 `dist/余额兔-vX.Y.Z-Windows-免安装.zip`；`cd windows/tests && ... dotnet run` 跑真实接口测试。
- 本机没有 Windows/Wine/VM，**Windows UI 无法本地验证**，只能靠用户截图 + 代码审查；
  因此任何布局改动都用「实测 + clamp」而不是固定坐标。
- macOS：`./build.sh`、`./package.sh`、`--render build/preview` 可离线出预览图，
  改完气泡/柱状图务必先看 PNG 预览再实机。
- 外部依赖：`GET /v1/balance` 由站长实现，返回
  `{"user_id":132,"balance_cny":82.96}`；未上线时 app 必须能回退到旧逻辑。

---

## 6. v1.2.0 反向同步（Windows 对齐 macOS 1.2.0，2026-10-20）

macOS 版先升级到 1.2.0（官方账户接口 + 底部错误横幅等），Windows 版已同步到相同行为：

- **数据接口**：优先 `GET /v1/account/balance` + `GET /v1/account/spending?from=&to=`
  （一次拿到实时余额、逐日花费、区间 totals、近 7 天充值）；
  `/v1/usage` 只取最近 1~2 页做「模型分布 + 累计请求数」；两个账户接口失败时回退旧翻页聚合，
  `/v1/balance` 仅作余额兜底。刷新请求数从 ~20 页降到 3 个。
- **账户/状态**：气泡底部优先显示「累计 N 次请求」，没有累计数时显示「账户 #id」；
  菜单显示账户 id、近 7 天充值、账号已停用提示、多账户过滤提示。
- **错误横幅**：刷新失败时保留上一次数据，在气泡底部一行显示「⚠ 刷新失败：…」（红色）；
  只有完全没有数据时才显示整块「查询失败」。
- **刷新体验**：刷新过程中保留旧内容（只有首次加载且无数据时才显示「查询中…」）；
  刷新成功后清空柱状图的悬停/选中状态。
- **峰值标签**：改为「实测宽高 → 居中在最高柱上方 → 夹在左右边界内」，
  柱最大高度 28、标签高度 12~16（与 macOS 完全相同）。
- **首启确认**：改用 settings 的 `last_run_version` 判断升级（安装包 `just-installed.txt` 仍兼容），
  已保存 Key 的机器在版本变化时弹「确认账号」，默认「否」。
- **文案**：主力模型 →「近期主力模型」；底部「标签/累计/账户」与 macOS 一致。
- **版本/分发**：版本升到 1.2.0，产物 `余额兔-v1.2.0-Windows-免安装.zip`
  （内含 `余额兔-v1.2.0.exe` + 使用说明.txt），仍只发这一个 zip。

macOS 版后续不再需要从本文反向同步；两端现在行为一致。改任一端时，
保持上面这些约束（接口优先级、错误横幅、峰值定位、交互、按人隔离 Key）。
