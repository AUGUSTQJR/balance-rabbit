#!/usr/bin/env bash
# 把设计稿渲染成固定 PNG 资源（Tools 里的绘制代码不参与 App 构建）
#   Assets/pet_sky.png       正常状态
#   Assets/pet_sky_low.png   低余额状态（右上角 ! 徽章）
#   build/preview/icon_1024.png  应用图标底图
set -euo pipefail
cd "$(dirname "$0")"

NATIVE_ARCH="$(uname -m)"
mkdir -p Assets build/ModuleCache build/preview

echo "▶ 导出兔子图片资源…"
swiftc -O -swift-version 5 \
  -module-cache-path build/ModuleCache \
  -target "$NATIVE_ARCH-apple-macos12.0" \
  -framework Cocoa \
  -o build/export-assets \
  Tools/Artwork.swift Tools/main.swift

./build/export-assets Assets build/preview

echo "✅ 资源已更新：$(pwd)/Assets"
