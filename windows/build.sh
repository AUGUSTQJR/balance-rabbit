#!/usr/bin/env bash
# 余额兔 · Windows 版构建脚本（在 macOS 上交叉编译）
# 依赖：tools/dotnet（.NET 8 SDK，见 tools/README），无需 Windows / Wine。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOTNET="$ROOT/tools/dotnet/dotnet"
export DOTNET_CLI_HOME="$ROOT/tools/home"
export NUGET_PACKAGES="$ROOT/tools/nuget"
export DOTNET_NOLOGO=1
export DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1

if [ ! -x "$DOTNET" ]; then
  echo "缺少 $DOTNET，请先解压 .NET SDK 到 tools/dotnet" >&2
  exit 1
fi

cd "$ROOT/windows/BalanceRabbit"

# 兔子形象图片与 macOS 版共用同一份（pet/Assets 由 macOS 的 export_assets.sh 生成）
if [ -f "$ROOT/pet/Assets/pet_sky.png" ]; then
  mkdir -p Assets
  cp "$ROOT/pet/Assets/pet_sky.png" "$ROOT/pet/Assets/pet_sky_low.png" Assets/
fi

"$DOTNET" build -c Release -v:m

if [ "${WITH_INSTALLER:-0}" = "1" ]; then
  cd "$ROOT/windows/Setup"
  "$DOTNET" build -c Release -v:m
fi

cd "$ROOT/windows"
mkdir -p dist
VERSION="$(python3 - <<'PY'
import re
print(re.search(r'<Version>([^<]+)</Version>', open('BalanceRabbit/BalanceRabbit.csproj').read()).group(1))
PY
)"

APP="BalanceRabbit/bin/Release/net48/BalanceRabbit.exe"
SETUP="Setup/bin/Release/net48/Setup.exe"
DIST="$ROOT/windows/dist"

# 只产出免安装 zip（里面是 exe + 使用说明），dist 不再单独放 exe
README_SRC="$ROOT/windows/使用说明-免安装.txt"
[ -f "$README_SRC" ] || README_SRC="$ROOT/windows/Setup/使用说明.txt"
rm -f "$DIST"/*.exe "$DIST"/使用说明.txt "$DIST"/余额兔-v*-Windows-免安装.zip
python3 - "$APP" "$README_SRC" "$DIST/余额兔-v$VERSION-Windows-免安装.zip" "余额兔-v$VERSION.exe" <<'EOF'
import sys, zipfile
app, readme, out, exe_name = sys.argv[1:5]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(app, exe_name)
    z.write(readme, "使用说明.txt")
print("entries:", [i.filename for i in zipfile.ZipFile(out).infolist()])
EOF

echo
echo "产物（只有带版本号的 zip）："
ls -lh "$DIST/余额兔-v$VERSION-Windows-免安装.zip"
echo
shasum -a 256 "$DIST/余额兔-v$VERSION-Windows-免安装.zip"
