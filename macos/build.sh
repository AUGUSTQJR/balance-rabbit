#!/usr/bin/env bash
# 编译「余额兔」.app，并生成应用图标
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="余额兔"
APP_DIR="$APP_NAME.app"
BUILD_DIR="build"
BINARY="BalancePet"

mkdir -p "$BUILD_DIR"
rm -rf "$APP_DIR"
rm -rf "$BUILD_DIR/preview"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"

cp Info.plist "$APP_DIR/Contents/Info.plist"

echo "▶ 编译…"
mkdir -p "$BUILD_DIR/ModuleCache"
NATIVE_ARCH="$(uname -m)"
BIN_PATH="$APP_DIR/Contents/MacOS/$BINARY"

swiftc -O -swift-version 5 \
  -module-cache-path "$BUILD_DIR/ModuleCache" \
  -target "$NATIVE_ARCH-apple-macos12.0" \
  -framework Cocoa \
  -o "$BUILD_DIR/$BINARY-$NATIVE_ARCH" \
  Sources/*.swift

# 尝试额外编译另一个架构，做成通用二进制（方便发给 Intel / Apple 芯片的同事）
OTHER_ARCH=""
if [ "$NATIVE_ARCH" = "arm64" ]; then OTHER_ARCH="x86_64"; else OTHER_ARCH="arm64"; fi
if swiftc -O -swift-version 5 \
  -module-cache-path "$BUILD_DIR/ModuleCache" \
  -target "$OTHER_ARCH-apple-macos12.0" \
  -framework Cocoa \
  -o "$BUILD_DIR/$BINARY-$OTHER_ARCH" \
  Sources/*.swift 2>/dev/null; then
  lipo -create -output "$BIN_PATH" \
    "$BUILD_DIR/$BINARY-$NATIVE_ARCH" "$BUILD_DIR/$BINARY-$OTHER_ARCH"
  echo "  通用二进制：$NATIVE_ARCH + $OTHER_ARCH"
else
  cp "$BUILD_DIR/$BINARY-$NATIVE_ARCH" "$BIN_PATH"
  echo "  单架构二进制：$NATIVE_ARCH"
fi
chmod +x "$BIN_PATH"

echo "▶ 导出兔子图片资源…"
./export_assets.sh
cp Assets/pet_sky.png Assets/pet_sky_low.png "$APP_DIR/Contents/Resources/"

echo "▶ 生成资源…"
"$APP_DIR/Contents/MacOS/$BINARY" --render "$BUILD_DIR/preview"

# 生成 .icns 图标
if [ -f "$BUILD_DIR/preview/icon_1024.png" ]; then
  ICONSET="$BUILD_DIR/icon.iconset"
  rm -rf "$ICONSET"
  mkdir -p "$ICONSET"
  for size in 16 32 128 256 512; do
    double=$((size * 2))
    sips -z "$size" "$size" "$BUILD_DIR/preview/icon_1024.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    sips -z "$double" "$double" "$BUILD_DIR/preview/icon_1024.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$APP_DIR/Contents/Resources/icon.icns"
fi

echo "▶ 签名（ad-hoc）…"
xattr -cr "$APP_DIR" 2>/dev/null || true
codesign --force --sign - "$APP_DIR" >/dev/null 2>&1 || echo "  （codesign 跳过）"

echo "✅ 已生成：$(pwd)/$APP_DIR"
echo "   双击运行，或执行：open \"$(pwd)/$APP_DIR\""
