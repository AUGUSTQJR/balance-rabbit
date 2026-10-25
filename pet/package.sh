#!/usr/bin/env bash
# 打包「余额兔」分发包：dist/ 里只放一个带版本号的 zip（内含 app + 使用说明）
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="余额兔"
APP_DIR="$APP_NAME.app"
DIST="dist"
STAGE="build/staging"
VERSION=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" Info.plist)
ZIP_NAME="$APP_NAME-v${VERSION}-macOS.zip"

./build.sh

echo "▶ 准备分发包（v${VERSION}）…"
rm -rf "$DIST" "$STAGE"
mkdir -p "$DIST" "$STAGE"
cp -R "$APP_DIR" "$STAGE/"
chmod -R u+w "$STAGE/$APP_DIR"
xattr -cr "$STAGE" 2>/dev/null || true
codesign --force --deep --sign - "$STAGE/$APP_DIR" >/dev/null 2>&1 || true
xattr -cr "$STAGE" 2>/dev/null || true

cat > "$STAGE/使用说明.txt" <<EOF
余额兔 v${VERSION} · 桌面余额小宠物（macOS）
适用于 macOS 12 及以上，Apple 芯片 / Intel 都能跑。

【安装】
1. 解压后把「余额兔.app」拖进「应用程序」文件夹。
2. 第一次打开会被系统拦下（提示「Apple 无法验证“余额兔”…」，只有「完成 / 移到废纸篓」，
   没有「打开」按钮）。在 macOS 15 / 26 上这样放行：
   · 打开「系统设置」→「隐私与安全性」→ 往下滚到最底部；
   · 会看到「已阻止使用“余额兔”，因为无法验证开发者」→ 点「仍要打开」；
   · 输入开机密码，再回到「应用程序」双击「余额兔」即可（之后正常双击，只需放行这一次）。
   macOS 13 / 14 更简单：在 App 上右键 →「打开」→ 再点「打开」。
3. 如果提示「已损坏，无法打开」，打开「终端」执行下面这行，再打开：
   xattr -dr com.apple.quarantine /Applications/余额兔.app
   （也可以在解压后、拖进应用程序之前，对「余额兔.app」执行同样的命令。）
4. 这里是「未签名/未公证」的免费分发方式，所以每个收到的人都要放行一次；
   这不是文件损坏，也不会影响功能。

【第一次使用：必须填自己的 API Key】
· 打开后 Dock 里没有图标，程序在屏幕右上角菜单栏（显示 ¥ 金额）。
· 首次启动会弹出「填写你自己的 rabbitj.top API Key」：填 sk- 开头的 Key。
  每个 macOS 用户 / 每台电脑都要填自己的 Key——填了别人的 Key 就会显示别人的余额。
  Key 只保存在本机钥匙串，不会写到任何共享文件。
· 升级/换人使用：启动时会问「确认账号」，默认不沿用旧 Key；菜单里也可「更换 API Key（换账号）…」。
· 菜单里能看到「当前 Key 尾号 …XXXX」和「账户 #id」，确认用的是自己账号。

【功能】
· 点桌面上的兔子：余额气泡（余额 / 今日 / 近 7 天柱状图 / Token / 模型）。
· 柱子可以鼠标悬停、点击：显示「10/14 花费 ¥0.32 · 24 次」，再点一次取消；点气泡其它地方刷新。
· 右键兔子或菜单栏金额：刷新、复制余额、打开商店、自动刷新间隔、低余额提醒、
  兔子大小、开机自动启动、把兔子放回屏幕右下角、隐藏等。
· 兔子形象固定为「蓝色圆环 · 弯弯眼」的静态图片（不眨眼、不呼吸摆动），三端外观完全一致。
· 拖到屏幕左 / 右边缘：收成一个蓝色小箭头（箭头标签），点一下兔子弹回来。
· ⌥ 或 ⌘ + 滚轮：自由缩放兔子大小。
· 双击菜单栏金额：把兔子叫回当前屏幕。
· 断网刷新失败会保留上一次数据，并在气泡底部提示错误。

【卸载】
菜单里「退出余额兔」，再删掉「应用程序/余额兔.app」即可
（如果开过开机自启，先在菜单里关掉「开机自动启动」）。

有问题截图发我。
EOF

echo "▶ 生成 zip…"
# 用 Python 打包：中文文件名带 UTF-8 标记（Windows/Finder 都不会乱码），并保留可执行权限
python3 - "$STAGE" "$DIST/$ZIP_NAME" <<'ZIPEOF'
import os, sys, time, zipfile

stage, out = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
    for root, dirs, files in os.walk(stage):
        dirs.sort()
        for name in dirs:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, stage).replace(os.sep, "/") + "/"
            info = zipfile.ZipInfo(rel, date_time=time.localtime(os.path.getmtime(full))[:6])
            info.create_system = 3
            info.external_attr = (0o40755 << 16) | 0x10
            archive.writestr(info, b"")
        for name in sorted(files):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, stage).replace(os.sep, "/")
            mode = 0o755 if os.access(full, os.X_OK) else 0o644
            info = zipfile.ZipInfo(rel, date_time=time.localtime(os.path.getmtime(full))[:6])
            info.create_system = 3
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(full, "rb") as handle:
                archive.writestr(info, handle.read())
ZIPEOF

echo "▶ 校验…"
lipo -info "$STAGE/$APP_DIR/Contents/MacOS/BalancePet" | sed 's/^/  /'
codesign --verify --strict "$STAGE/$APP_DIR" >/dev/null 2>&1 \
  && echo "  签名自检通过" || echo "  （ad-hoc 签名，需右键打开）"
[ -x "$STAGE/$APP_DIR/Contents/MacOS/BalancePet" ] && echo "  可执行文件正常"
unzip -l "$DIST/$ZIP_NAME" | tail -6 | sed 's/^/  /'

ls -lh "$DIST/$ZIP_NAME"
echo "✅ 分发文件：$(pwd)/$DIST/$ZIP_NAME"
