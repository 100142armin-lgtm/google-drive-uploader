#!/bin/bash
cd "$(dirname "$0")"

echo "======================================================"
echo "    云端极速上传器 v2.0 - Mac 原生 .app 打包脚本"
echo "======================================================"

if ! command -v python3 &>/dev/null; then
    echo "错误：未检测到 Python 3，请先安装 Python 3"
    exit 1
fi

echo "1. 检查并安装打包所需依赖..."
python3 -m pip install -q "pyinstaller>=6.21.0" "customtkinter>=6.0.0" "requests>=2.34.0"

echo "2. 开始编译生成 Mac 原生独立应用..."
pyinstaller --noconfirm --clean --windowed \
  --name "云端极速上传器" \
  --icon "app_icon.icns" \
  --add-data "logo.png:." \
  --add-data "logo_small.png:." \
  --add-data "logo_card.png:." \
  --collect-all "customtkinter" \
  app.py

echo "======================================================"
echo "✓ 打包完成！生成的 Mac 原生应用位于："
echo "   $(pwd)/dist/云端极速上传器.app"
echo "您可以直接双击运行，或拖入「应用程序(Applications)」使用！"
echo "======================================================"
