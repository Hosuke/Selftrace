#!/bin/bash
# 启动书法字帖生成器
cd "$(dirname "$0")"

echo "=== 隶书字帖生成器 MVP ==="

# 检查Python虚拟环境
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "安装依赖..."
pip install -q -r backend/requirements.txt

echo ""
echo "启动后端服务 (http://localhost:8000)..."
echo "前端页面请直接在浏览器中打开: frontend/index.html"
echo ""

cd backend
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
