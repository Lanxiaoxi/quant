#!/usr/bin/env bash
# ============================================================
# trading-quant 云服务器部署脚本
# 基于 uv 管理 Python 环境，FastAPI 一体托管前后端
# ============================================================
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

echo "=== 1/4 安装 uv ==="
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
uv --version

echo "=== 2/4 安装 Python 依赖 ==="
cd "$BACKEND_DIR"
uv pip install -r requirements.txt --python 3.12

echo "=== 3/4 构建前端 ==="
cd "$FRONTEND_DIR"
npm install --production
npx vite build

echo "=== 4/4 配置环境变量 ==="
if [ ! -f "$BACKEND_DIR/.env" ]; then
    echo "⚠ 未找到 backend/.env，请手动创建："
    echo "  TUSHARE_TOKEN=your_token"
    exit 1
fi

echo ""
echo "=== 部署完成！启动服务 ==="
echo "  cd $BACKEND_DIR && nohup uv run uvicorn app.main:app --host 0.0.0.0 --port 8100 > server.log 2>&1 &"
echo ""
echo "  访问 http://<服务器IP>:8100"
echo "  默认账号: admin / admin"
echo "  查看日志: tail -f $BACKEND_DIR/server.log"
