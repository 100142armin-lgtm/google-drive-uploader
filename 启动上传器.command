#!/bin/bash
cd "$(dirname "$0")"

echo "======================================================"
echo "    云端极速上传器 v2.0 - Mac 极速启动器"
echo "======================================================"

# 检查 Python 环境
if command -v python3 &>/dev/null; then
    PY_BIN="python3"
elif command -v python &>/dev/null; then
    PY_BIN="python"
else
    echo "【提示】未检测到 Python3 环境！"
    echo "请访问 https://www.python.org/downloads/ 安装 Python 3 即可。"
    read -p "按回车键退出..."
    exit 1
fi

echo "检查并准备运行环境..."
if ! $PY_BIN -c "import customtkinter, requests" &>/dev/null; then
    echo "正在自动安装所需安全依赖组件..."
    $PY_BIN -m pip install -q "customtkinter>=6.0.0" "requests>=2.34.0" 2>/dev/null || {
        echo "【提示】自动安装遇到网络问题，尝试继续启动..."
    }
fi

echo "启动软件中，请稍候..."
$PY_BIN app.py
