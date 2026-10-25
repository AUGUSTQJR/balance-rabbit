#!/usr/bin/env bash
# 余额兔 · Linux 版卸载脚本。默认保留设置与 API Key；加 --purge 一并删除。
set -euo pipefail

PURGE=0
for arg in "$@"; do
  case "$arg" in
    --purge) PURGE=1 ;;
    *) echo "未知参数：$arg"; exit 1 ;;
  esac
done

DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
CONFIG_HOME=${XDG_CONFIG_HOME:-$HOME/.config}
APPDIR="$DATA_HOME/balance-rabbit"
LAUNCHER="$HOME/.local/bin/balance-rabbit"
DESKTOP="$DATA_HOME/applications/balance-rabbit.desktop"
ICON="$DATA_HOME/icons/hicolor/256x256/apps/balance-rabbit.png"
AUTOSTART="$CONFIG_HOME/autostart/balance-rabbit.desktop"

pkill -f "balance_rabbit" 2>/dev/null || true

rm -rf "$APPDIR"
rm -f "$LAUNCHER" "$DESKTOP" "$ICON" "$AUTOSTART"

if [ "$PURGE" = "1" ]; then
  rm -rf "$CONFIG_HOME/balance-rabbit"
  echo "已删除程序与设置（含本机保存的 API Key）。"
else
  echo "已删除程序；设置和 API Key 保留在 $CONFIG_HOME/balance-rabbit（如需清理加 --purge）。"
fi
