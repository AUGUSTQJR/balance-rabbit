# 余额兔 · BalanceRabbit

一只常驻桌面、置顶悬浮的小兔子：点它就能看 API 余额、今日 / 近 7 天消费趋势、Token 用量和主力模型。

支持 **macOS / Windows / Linux 三端**。全部是本机原生程序，不依赖 Electron 环境，体积小、内存低、API Key 只存本机。

<p align="center">
  <img src="docs/screenshots/pet.png" width="150" alt="余额兔">
  <img src="docs/screenshots/bubble.png" width="330" alt="余额气泡">
</p>

<p align="center">
  <img src="docs/screenshots/dock_left.png" width="180" alt="吸附到左边缘">
  <img src="docs/screenshots/dock_right.png" width="180" alt="吸附到右边缘">
  <br><sub>拖到屏幕边缘会自动吸附，只露出半个箭头标签；点一下变回大兔子</sub>
</p>

## 下载

点击文件名直接下载：

| 系统 | 下载文件 | 版本 | 大小 |
| --- | --- | --- | --- |
| macOS 12+（Apple 芯片 / Intel 通用） | [`BalanceRabbit-v1.3.0-macOS.zip`](https://github.com/AUGUSTQJR/balance-rabbit/releases/download/v1.3.0-macOS/BalanceRabbit-v1.3.0-macOS.zip) | v1.3.0 | 1.1 MB |
| Windows 10 / 11 | [`BalanceRabbit-v1.3.0-Windows.zip`](https://github.com/AUGUSTQJR/balance-rabbit/releases/download/v1.3.0-windows/BalanceRabbit-v1.3.0-Windows.zip) | v1.3.0 | 414 KB |
| Linux（Python 3.9+ / Qt6） | [`BalanceRabbit-v1.1.0-Linux.zip`](https://github.com/AUGUSTQJR/balance-rabbit/releases/download/v1.1.0-linux/BalanceRabbit-v1.1.0-Linux.zip) | v1.1.0 | 70 KB |

全部历史版本见 **[Releases](../../releases)** 页面。解压密码：无，每个 zip 里都带一份 `使用说明.txt`，照着做即可。

## 它显示什么

- **余额**：实时余额，菜单栏 / 托盘常驻显示 `¥xx.xx`
- **今日花费** 与 **近 7 天花费**（带柱状图，可悬停 / 点选查看某一天）
- **Token 用量**：输入 + 输出 + 缓存读写
- **模型分布**：最近在用哪个模型、各用了多少
- **低余额提醒**：低于阈值弹通知（默认 ¥20，6 小时不重复打扰）
- **自动刷新**：默认每 10 分钟一次，失败保留上一次数据并显示错误横幅

## 快速开始

### macOS

```bash
# 解压后直接双击运行；首次会被 Gatekeeper 拦一次（未上架 App Store）
# 放行：系统设置 → 隐私与安全性 → 滚到底 → 「仍要打开」→ 输密码
# 或用终端一次解决：
xattr -dr com.apple.quarantine /Applications/余额兔.app
```

第一次运行会弹窗让你填自己的 `sk-` 开头 API Key（**只存本机钥匙串**，按 macOS 用户隔离）。

想自己编译：`cd pet && ./build.sh`（需要 Xcode 命令行工具，纯 `swiftc`，无第三方依赖）。

### Windows

解压得到 `余额兔-v1.3.0.exe`，双击即可（免安装）。未签名，首次运行需在 SmartScreen 里点「更多信息 → 仍要运行」。

想自己编译：`cd windows && ./build.sh`（在 macOS 上交叉编译，需要本地 .NET 8 SDK，见 [tools/README](tools/README.md)）。

### Linux

```bash
unzip 余额兔-v1.1.0-Linux.zip
cd 余额兔-v1.1.0-Linux && ./install.sh --autostart   # 装到 ~/.local/share/balance-rabbit
```

基于 PySide6 / Qt 6。部分发行版需先装依赖：`sudo apt install libxcb-cursor0 libxkbcommon-x11-0`。

## 关于 API Key

- 程序只读**你自己填的** Key，**不联网上传任何东西**，数据只在你本机和 API 服务方之间流转。
- Key 存储按系统用户隔离：macOS 用钥匙串、Windows 用 DPAPI、Linux 用 `secret-tool` 或 0600 私有文件。
- 换人使用同一台电脑时启动会先问「确认账号」，菜单里也可以随时「更换 API Key」。

> 本项目只是余额查询的小挂件，不包含任何代理、加速或转发功能。

## 目录结构

```
macos/       macOS 版（Swift + AppKit，纯 swiftc 编译）
windows/   Windows 版（C# / .NET Framework 4.8 WinForms）
linux/     Linux 版（Python 3.9+ / PySide6）
design/    兔子形象设计稿
docs/      截图
tools/     交叉编译工具链说明（实际文件不入库）
```

## 各端说明

- [macOS 版说明](macos/README.md) · [设计文档](macos/DESIGN.md)
- [Windows 版说明](windows/README.md)
- [Linux 版说明](linux/README.md)

## 常见问题

**打不开 / 提示「无法验证开发者」？**
未做苹果签名公证（需每年 $99 开发者账号）和 Windows 代码签名，所以系统会拦。按上面「快速开始」里的放行步骤操作即可，程序本身是开源可审查的。

**余额显示不对？**
先确认填的是自己的 Key，其次注意日期按服务端时区（UTC+8）切分，非东八区机器上「今日」的口径可能有差异。

**支持哪些服务商？**
目前适配 [rabbitj.top](https://www.rabbitj.top) 的账户接口（`/v1/account/balance`、`/v1/account/spending`、`/v1/usage`）。走 OpenAI 兼容接口的中转站大多可以按同样的思路适配。

## 许可

[MIT](LICENSE)
