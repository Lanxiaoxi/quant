#!/usr/bin/env bash
# ============================================================
# trading-quant 一键更新重启脚本
# 用法: bash restart.sh
# ============================================================
set -e

cd "$(dirname "$0")"

echo ">>> 1/4 拉取最新代码..."
git pull

echo ">>> 2/4 构建前端..."
cd frontend
npm install --silent 2>&1 | tail -1
npx vite build 2>&1 | tail -3
cd ..

echo ">>> 3/4 停止旧进程..."
OLD_PIDS=$(ps aux | grep -E 'uvicorn.*app\.main' | grep -v grep | awk '{print $2}')
if [ -n "$OLD_PIDS" ]; then
    echo "$OLD_PIDS" | xargs sudo kill -9 2>/dev/null || true
    echo "  已停止: $OLD_PIDS"
else
    echo "  无运行中进程"
fi
sleep 1

echo ">>> 4/4 启动服务..."
cd backend
nohup uv run --python 3.10 uvicorn app.main:app --host 0.0.0.0 --port 8100 > server.log 2>&1 &
sleep 3
curl -s -o /dev/null -w "  状态: HTTP %{http_code}\n" http://127.0.0.1:8100/api/health

echo ""
echo "✅ 重启完成 — http://$(curl -s ifconfig.me 2>/dev/null || echo '服务器IP'):8100"
