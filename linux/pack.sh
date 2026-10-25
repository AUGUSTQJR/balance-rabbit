#!/usr/bin/env bash
# 余额兔 · Linux 版打包脚本：生成 dist/余额兔-vX.Y.Z-Linux.zip
set -euo pipefail

cd "$(dirname "$0")"
HERE=$(pwd)
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' balance_rabbit/__init__.py)
[ -n "$VERSION" ] || { echo "读取版本号失败"; exit 1; }

PYTHON=${PYTHON:-python3}

# 1) 生成预览图和图标（需要本机装有 PySide6）
if "$PYTHON" -c "import PySide6" >/dev/null 2>&1; then
  "$PYTHON" -m balance_rabbit --render build >/dev/null
  cp build/icon.png icon.png
  echo "已生成图标 icon.png"
else
  echo "提示：本机没有 PySide6，跳过图标生成（沿用已有 icon.png）"
fi

# 2) 准备发布目录
NAME="余额兔-v${VERSION}-Linux"
STAGE="build/$NAME"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -R balance_rabbit "$STAGE/"
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} +
cp install.sh uninstall.sh requirements.txt 使用说明.txt README.md "$STAGE/"
if [ -f icon.png ]; then cp icon.png "$STAGE/"; fi
chmod +x "$STAGE/install.sh" "$STAGE/uninstall.sh"

# 3) 打包（用 Python zipfile：文件名 UTF-8 标记正确，Linux 解压不乱码）
find "$STAGE" -type f -exec chmod 644 {} +
chmod 755 "$STAGE/install.sh" "$STAGE/uninstall.sh"
mkdir -p dist
rm -f "dist/$NAME.zip"
python3 - "$STAGE" "dist/$NAME.zip" <<'PY'
import os
import sys
import zipfile

stage, output = sys.argv[1], sys.argv[2]
base = os.path.dirname(stage)
with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
    for root, _dirs, files in os.walk(stage):
        for name in sorted(files):
            full = os.path.join(root, name)
            arcname = os.path.relpath(full, base)
            info = zipfile.ZipInfo.from_file(full, arcname)
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(full, "rb") as handle:
                archive.writestr(info, handle.read())
PY
echo "已生成 dist/$NAME.zip"
ls -lh "dist/$NAME.zip"
