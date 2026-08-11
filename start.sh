#!/bin/bash
# YouTube Downloader - Mac 桌面启动脚本
# 双击或终端运行此脚本即可启动应用

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="/Users/liutongjin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"

# 检查 Python
if [ ! -f "$PYTHON_BIN" ]; then
    # 回退到系统 Python3
    PYTHON_BIN="python3"
fi

# 检查 yt-dlp
if ! "$PYTHON_BIN" -m yt_dlp --version &>/dev/null; then
    echo "yt-dlp 未安装，正在安装..."
    "$PYTHON_BIN" -m pip install yt-dlp
fi

# 检查 ffmpeg（可选，用于高清合并和 MP3 提取）
if ! command -v ffmpeg &>/dev/null; then
    echo "⚠️  ffmpeg 未安装"
    echo "   没有ffmpeg，下载高清视频(1080p+)时会自动降级到最佳可用画质"
    echo "   安装ffmpeg: brew install ffmpeg"
    echo ""
fi

echo "================================"
echo "  🎵 YouTube Downloader"
echo "  正在启动..."
echo "================================"
echo ""
echo "  使用方法："
echo "  1. 浏览器会自动打开应用界面"
echo "  2. 粘贴 YouTube 视频链接"
echo "  3. 选择画质并下载"
echo "  4. 如需代理，点击右上角⚙️设置"
echo ""
echo "  按 Ctrl+C 退出"
echo "================================"
echo ""

# 启动服务器
exec "$PYTHON_BIN" "$SCRIPT_DIR/server.py"
