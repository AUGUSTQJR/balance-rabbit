# 余额兔 · Windows 版

macOS 版「余额兔」的 Windows 移植：桌面兔子 + 余额气泡 + 托盘常驻，功能对齐 `pet/DESIGN.md`。
纯 .NET Framework 4.8 WinForms，无第三方依赖、无运行时安装包（Win10 1903+ / Win11 自带 4.8）；
兔子形象自 v1.3.0 起与 macOS 共用同一份静态 PNG（编译进 exe），运行时不画矢量路径、无动画。

## 目录

```
windows/
├── BalanceRabbit/          # 应用本体（net48，WinExe）
│   ├── LayeredForm.cs      # 逐像素透明 + 置顶 + 不抢焦点窗口基类（UpdateLayeredWindow）
│   ├── PetWindow.cs        # 兔子窗口：只贴静态图片 + 拖动 / 点击 / 右键 / Ctrl+滚轮缩放
│   ├── PetImages.cs        # 加载内嵌的 pet_sky*.png（与 macOS 版同一份图，无矢量绘制）
│   ├── BubbleWindow.cs     # 余额气泡窗口
│   ├── BubblePainter.cs    # 气泡绘制：余额 / 今日 / 7 天柱状图 / Token / 模型
│   ├── DockWindow.cs       # 边缘吸附指示器窗口
│   ├── Painters2.cs        # DockPainter：箭头标签样式（深蓝渐变 + 白色箭头 + 呼吸光晕）
│   ├── App.cs              # 控制器：托盘 / 菜单 / 定时刷新 / 低余额通知 / 吸附状态机
│   ├── ApiClient.cs        # 官方账户接口（余额/逐日花费）+ usage 摘要，旧翻页聚合兜底
│   ├── Models.cs / Json.cs # 数据模型 + 极简 JSON 解析（不依赖 System.Web）
│   ├── Settings.cs         # ini 配置 + DPAPI 加密 Key + HKCU 开机自启
│   ├── Program.cs          # 单实例（Mutex + EventWaitHandle 唤出）
│   └── KeyDialog.cs        # 设置 API Key 对话框
├── Setup/                  # 安装包（net48，WinExe，内嵌应用 exe）
│   ├── Installer.cs        # 安装/卸载核心（当前用户、无需管理员）
│   ├── InstallerForm.cs    # 一屏安装向导
│   └── Program.cs          # /uninstall、/S 参数
├── tests/                  # 纯逻辑测试（net8，可在 macOS 跑真实接口）
└── build.sh                # 一键构建 → dist/
```

## 构建（在 macOS 上交叉编译）

```bash
# 一次性：下载 .NET 8 SDK 到 tools/dotnet
cd tools && mkdir -p dotnet && tar -xzf dotnet-sdk.tar.gz -C dotnet

cd windows && ./build.sh
# 产物（只有一个文件）：
#   dist/余额兔-vX.Y.Z-Windows-免安装.zip （内含 余额兔-vX.Y.Z.exe + 使用说明.txt）
#   版本号自动取 csproj；安装包默认不构建（WITH_INSTALLER=1 才会出，且不再分发）
```

`net48` 的引用程序集通过 NuGet 包 `Microsoft.NETFramework.ReferenceAssemblies` 自动还原，因此
**不需要 Windows、Wine 或 Mono**；产物是 PE32 的 .NET Framework 程序集，仅依赖系统自带的 4.8。

## 逻辑测试

```bash
cd windows/tests
DOTNET_CLI_HOME=../tools/home ../../tools/dotnet/dotnet run -c Release
```

覆盖：JSON 解析、`created_at` / 账户接口日期解析、`/v1/account/balance` 与
`/v1/account/spending` 的字段解析、真实账户接口的余额 / 逐日 / Token / 模型 / 账户 id 校验
（读本机 Key）。2026-10-20 v1.3.0 实测通过（含 `TZ=Pacific/Honolulu` 与东八区结果一致）。

## 安装包行为

- 安装界面可点「更改安装位置…」自选目录（装在所选文件夹下的 BalanceRabbit 子目录，
  可装 D 盘）；不选时默认 `%LOCALAPPDATA%\Programs\BalanceRabbit`（当前用户，不需要 UAC）。
  若目录不可写（权限/安全软件拦截），自动改试 `%LOCALAPPDATA%\BalanceRabbit`、
  `%APPDATA%\BalanceRabbitApp`、`%USERPROFILE%\BalanceRabbitApp`
- 安装失败时写日志到 `%TEMP%\BalanceRabbit-install.log`，并可一键「以管理员身份重试」
- 被安全软件全局拦截时：安装程序依次尝试 9 个位置（用户目录、程序旁下载目录、ProgramData、%TEMP%）；
  应用设置依次尝试 `%APPDATA%` → exe 旁 `BalanceRabbit-data` → `%LOCALAPPDATA%` → `%TEMP%`，
  全不可写时内存运行并提示
- API Key 只认当前 Windows 用户自己保存的（DPAPI 加密），不再读取 `.dsh/.credentials.yaml`
  等别人的配置；安装后首次启动会确认已有 Key 是否属于当前使用者，菜单可「更换 API Key（换账号）」
- 创建桌面 + 开始菜单快捷方式、卸载快捷方式
- 写 `HKCU\...\Uninstall\BalanceRabbit`（设置 → 应用 里可卸载）
- 可选开机自启（HKCU Run），可选安装后立即运行
- 卸载保留 `%APPDATA%\BalanceRabbit` 配置（含加密 Key），便于重装
- 支持静默：`余额兔-...-安装包.exe /S`，卸载：`uninstall.exe /uninstall /S`

## 与 macOS 版的差异

- 托盘显示的是悬停提示（Windows 托盘不支持常驻文字），托盘菜单左键 = 气泡
- 气泡不抢焦点、30 秒无操作自动收起（Windows 没有等价于 NSPanel 的非激活 + 失焦关闭）
- 兔子形象与吸附图标都只有一种（固定图片 + 箭头标签），与 macOS v1.3.0 一致
- 通知用系统气泡通知（`NotifyIcon.ShowBalloonTip`），低余额 6 小时节流

## 注意

- 未购买代码签名证书，首次运行 SmartScreen 会提示「更多信息 → 仍要运行」
- 应用界面/吸附/托盘交互以 Windows 实机反馈为准（构建环境是 macOS，UI 无法本地验证）
- 数据优先走官方账户接口 `/v1/account/balance` + `/v1/account/spending`，
  `/v1/usage` 只取最近 1~2 页做模型分布与累计请求数；接口不可用时自动回退旧翻页聚合
