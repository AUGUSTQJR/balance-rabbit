# 余额兔 · Linux 版

macOS 版「余额兔」的 Linux 移植：桌面兔子 + 余额气泡 + 托盘常驻 + 左右边缘吸附。
Python 3 + PySide6（Qt 6）实现，矢量自绘（无图片资源），数据接口与 macOS / Windows 1.2.x 对齐。

## 目录

```
linux/
├── balance_rabbit/
│   ├── __main__.py        # 入口：GUI / --stats / --render / --enable-login
│   ├── app.py             # 控制器：窗口编排、托盘、菜单、定时刷新、吸附状态机、Key 对话框
│   ├── windows.py         # 三个无边框透明窗口（兔子 / 气泡 / 边缘指示器）
│   ├── painters.py        # QPainter 矢量绘制：兔子、气泡、4 种指示器、预览图、图标
│   ├── api.py             # 官方账户接口 + usage 摘要 + 旧翻页回退
│   ├── models.py          # Stats / DayStat / 接口解析模型
│   ├── settings.py        # JSON 设置、Key 存储（secret-tool 或 0600 文件）、开机自启
│   ├── instance.py        # 单实例（flock + QLocalServer）
│   └── util.py            # 金额 / Token / 日期格式化
├── tests/test_core.py     # 离线解析/汇总测试 + 真实接口核对
├── tests/test_crosscheck.py   # 独立交叉核验（假服务器 + 真实接口逐字段比对）
├── tests/test_ui_smoke.py     # 界面冒烟（offscreen）
├── tests/test_render_matrix.py # 渲染矩阵 + 窗口几何（offscreen）
├── install.sh             # 安装到 ~/.local（venv + PySide6 + 桌面项）
├── uninstall.sh
├── pack.sh                # 生成 dist/余额兔-vX.Y.Z-Linux.zip
├── requirements.txt       # PySide6-Essentials
├── 使用说明.txt
└── icon.png               # pack.sh 生成
```

## 开发运行

```bash
cd linux
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m balance_rabbit            # 启动
.venv/bin/python -m balance_rabbit --stats    # 命令行打印余额/统计
.venv/bin/python -m balance_rabbit --render build   # 生成 PNG 预览 + icon.png
python3 tests/test_crosscheck.py               # 数据层独立核验（无 Key 自动 skip 真接口）
python3 -m unittest discover -s tests -v       # 数据层测试（真实接口会读本机 Key）
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest \
    tests.test_ui_smoke tests.test_render_matrix -v   # 界面/渲染/几何
```

`--render` 可在没有 Linux 桌面的机器（如 macOS）上跑，用来核对绘制坐标和排版。
运行期未捕获异常会写到 `~/.config/balance-rabbit/error.log`，启动失败先看这个文件。

## 功能对齐（与 macOS / Windows v1.2.x）

- 兔子：呼吸、眨眼、耳朵摆动、加载小跳；低余额头顶 `!` 徽章
- 气泡：余额、更新时间、今日 / 近 7 天花费、7 天柱状图（悬停/点选当天）、峰值标签、
  Token、近期主力模型、近 7 天充值、多账户过滤提示、底部错误横幅；默认显示在兔子/指示器
  上方（上方放不下时自动翻到下方，尖角始终指向兔子）
  （is_active=false 只在菜单留一行灰色提示，不当停用告警；真正停用接口会返回 403）
- 托盘：提示文字显示实时余额，菜单与右键菜单一致；左键切换气泡
- 交互：拖动、Ctrl/Alt+滚轮缩放（96–320，默认 176）、点击刷新、右键菜单、15 秒自动收起
- 吸附：只做左 / 右边缘，28px 内松手；48×48 指示器只露 24px，悬停外探 14px，
  点击弹回，沿边缘拖动；4 种样式（默认箭头标签）
- 刷新：默认 10 分钟；失败保留旧数据并显示错误
- 通知：低余额系统通知（notify-send，6 小时节流）
- 单实例、开机自启（~/.config/autostart）
- 没有系统托盘的桌面（如原生 GNOME）会禁用「隐藏兔子」，避免隐藏后无法找回
- Key 严格按人：环境变量 > 本机密钥环 / 0600 文件；不再读 `~/.dsh/.credentials.yaml`
  （仅在首次填写对话框里预填，确认后才保存）

## 数据接口

- `GET /v1/account/balance`：实时余额、`user_id`、`is_active`
- `GET /v1/account/spending?from=&to=`：逐日花费 + totals + 充值，一次拿全
- `/v1/usage?limit=200&status=billed`：只取最近 1~2 页做模型分布与累计请求数
- 两个账户接口都失败 → 回退旧翻页聚合（最多 25 页）
- `/v1/balance` 仅作余额兜底（线上仍 404）
- Token = input + output + cache_read + cache_write；日期按服务器本地时间切天

## 技术要点 / 坑

1. **窗口定位**：Wayland 不允许应用自己定位窗口。入口在检测到 XWayland 时自动
   `QT_QPA_PLATFORM=xcb`；X11 下用 `FramelessWindowHint | WindowStaysOnTopHint | Tool |
   WindowDoesNotAcceptFocus`，需要压过全屏窗口时可设 `BALANCE_RABBIT_OVERRIDE=1`
   启用 `X11BypassWindowManagerHint`。
2. **透明**：`WA_TranslucentBackground` 依赖桌面合成器（GNOME/KDE 默认开启）。
   气泡整窗可点，透明边角也不点穿（与 macOS 行为一致）。
3. **Qt6 xcb 依赖**：pip 装的 Qt 仍需要系统库 `libxcb-cursor0`、`libxkbcommon-x11-0`，
   install.sh 会在自检失败时给出 apt 命令。
4. **绘制**：沿用 macOS 设计画布（兔子 160²、气泡 300×282、指示器 80²×0.6），
   所有文字按实际测量宽度逐级缩字号，避免不同发行版字体差异造成压字/截断。
5. **阴影**：不引入模糊特效，用逐圈描边模拟柔和阴影，气泡阴影只随 tail 变化重绘。
6. **单实例**：`flock` 锁 + QLocalServer；第二次启动通过本地 socket 让已运行实例弹气泡。
7. **Key 隔离**：优先 `secret-tool`（libsecret），否则写 `~/.config/balance-rabbit/api-key`
   并 `chmod 600`；不读共享 yaml，避免换人使用同一台电脑时显示别人的余额。
8. **设置降级**：`~/.config` → `~/.cache` → `/tmp`；不可写时提示只能本次运行有效。

## 打包

```bash
cd linux
./pack.sh     # → dist/余额兔-v1.1.0-Linux.zip（源码 + install.sh + 说明 + 图标）
```

zip 内不含 PySide6（约 100 MB），安装时由 pip 下载；内网/离线环境可把
`PySide6_Essentials-*.whl`、`shiboken6-*.whl` 放进 `wheels/` 后重新打包，
install.sh 会自动优先用本地 wheels。

## 已验证 / 未验证

- ✅ 数据层：55 项测试通过（解析 / 汇总 / 401/403/404/422/503 / 超时 / 脏 JSON / 时区 /
  多账户 / 翻页回退 / 真实接口逐字段比对）；真实接口测试用「前后快照包络」避免并发误报
- ✅ 界面：4 项冒烟 + 24 项渲染矩阵（兔子 5 档尺寸 × 4 状态 × 4 造型、气泡 7 种数据、
  4 指示器 × 左右、吸附/气泡/缩放几何）全部通过
- ✅ 绘制：`--render` 生成的预览图与 macOS 版逐项比对（兔子、气泡、4 种指示器）
- ⚠️ Linux 实机窗口行为（置顶、吸附、托盘、通知）需要在 Linux 桌面验证；
  本仓库开发环境是 macOS，只能验证渲染与接口。首次上实机若有偏差，
  按「技术要点」里的窗口/依赖两条排查。
