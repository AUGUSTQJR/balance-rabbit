#!/usr/bin/env bash
# 余额兔 · Linux 版安装脚本（装到当前用户目录，不需要 sudo）
#
#   ./install.sh              安装（自动创建虚拟环境并安装 PySide6）
#   ./install.sh --autostart  安装并加入开机自启
#
# 卸载见 uninstall.sh。
set -euo pipefail

cd "$(dirname "$0")"
HERE=$(pwd)
AUTOSTART=0
for arg in "$@"; do
  case "$arg" in
    --autostart) AUTOSTART=1 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "未知参数：$arg"; exit 1 ;;
  esac
done

DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
APPDIR="$DATA_HOME/balance-rabbit"
APPDIR_APP="$APPDIR/app"
VENV="$APPDIR/venv"
BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/balance-rabbit"
ICON_DIR="$DATA_HOME/icons/hicolor/256x256/apps"
DESKTOP_DIR="$DATA_HOME/applications"

say() { printf '\033[1;34m[余额兔]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[错误]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- 依赖检查
command -v python3 >/dev/null 2>&1 || fail "没有找到 python3，请先安装：sudo apt install python3"
python3 - <<'PY' || fail "需要 Python 3.9 或更高版本"
import sys
sys.exit(0 if sys.version_info >= (3, 9) else 1)
PY

if ! python3 -c "import venv" >/dev/null 2>&1; then
  fail "缺少 python3-venv，请先执行：sudo apt install python3-venv python3-pip"
fi

say "安装目录：$APPDIR"
mkdir -p "$APPDIR_APP" "$BIN_DIR"

# ---------------------------------------------------------------- 虚拟环境
if [ ! -x "$VENV/bin/python" ]; then
  say "创建虚拟环境…"
  python3 -m venv "$VENV" || fail "创建虚拟环境失败（sudo apt install python3-venv）"
fi

say "安装依赖 PySide6-Essentials（首次约 100 MB，走 pip 源）…"
"$VENV/bin/python" -m pip install --disable-pip-version-check --upgrade pip >/dev/null 2>&1 || true
if [ -d "$HERE/wheels" ]; then
  "$VENV/bin/python" -m pip install --disable-pip-version-check --no-index --find-links "$HERE/wheels" -r "$HERE/requirements.txt"
else
  "$VENV/bin/python" -m pip install --disable-pip-version-check -r "$HERE/requirements.txt"
fi

# ---------------------------------------------------------------- 拷贝应用
say "复制程序文件…"
rm -rf "$APPDIR_APP/balance_rabbit"
mkdir -p "$APPDIR_APP"
cp -R "$HERE/balance_rabbit" "$APPDIR_APP/"
find "$APPDIR_APP" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
cp "$HERE/icon.png" "$APPDIR_APP/icon.png" 2>/dev/null || true

cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$APPDIR_APP"
exec "$VENV/bin/python" -m balance_rabbit "\$@"
EOF
chmod +x "$LAUNCHER"

# ---------------------------------------------------------------- 图标/菜单
if [ -f "$HERE/icon.png" ]; then
  mkdir -p "$ICON_DIR"
  cp "$HERE/icon.png" "$ICON_DIR/balance-rabbit.png"
fi
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/balance-rabbit.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=余额兔
Comment=桌面宠物余额监控（rabbitj.top）
Exec=$LAUNCHER
Icon=balance-rabbit
Terminal=false
Categories=Utility;Finance;
StartupNotify=false
EOF
chmod +x "$DESKTOP_DIR/balance-rabbit.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true

# ---------------------------------------------------------------- 自检
"$VENV/bin/python" -c "import balance_rabbit" >/dev/null 2>&1 || fail "程序自检失败，请把上面的错误发给开发者"
VERSION=$("$VENV/bin/python" -m balance_rabbit --version)
say "已安装余额兔 v$VERSION"

# Qt6 的 xcb 插件需要系统库；没装时先提醒（不影响 offscreen 自检）
if [ -n "${DISPLAY:-}" ]; then
  if ! QT_QPA_PLATFORM=xcb "$VENV/bin/python" -c "from PySide6.QtWidgets import QApplication; QApplication([])" >/dev/null 2>&1; then
    echo
    printf '\033[1;33m[提示]\033[0m 图形界面依赖的系统库可能缺失，请执行：\n'
    echo "  sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1"
  fi
fi

if [ "$AUTOSTART" = "1" ]; then
  AUTOSTART_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/balance-rabbit.desktop"
  mkdir -p "$(dirname "$AUTOSTART_FILE")"
  cat > "$AUTOSTART_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=余额兔
Comment=桌面宠物余额监控
Exec=$LAUNCHER
Icon=balance-rabbit
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
  say "已加入开机自启"
fi

echo
say "安装完成。运行方式："
echo "  1) 应用列表里搜索「余额兔」"
echo "  2) 终端执行：$LAUNCHER"
echo
echo "首次启动会要求填写自己的 rabbitj.top API Key（sk- 开头）。"
echo "如果菜单栏/托盘没有图标，右键点兔子也能打开菜单。"
