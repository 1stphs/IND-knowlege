#!/bin/bash

echo "======================================="
echo "  IND Knowledge RAG 系统一键启动脚本"
echo "======================================="

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null
then
    echo "[错误] 请先安装 Docker 环境。"
    exit 1
fi

# 检查 .env
if [ ! -f ".env" ]; then
    echo "[提示] 未找到 .env 文件。"
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "[成功] 自动基于 .env.example 生成了 .env，请编辑填写如 OPENAI_API_KEY 密钥后重新启动脚本。"
        exit 0
    fi
fi

echo "[进行中] 正在通过 Docker Compose 构建并启动环境..."
if command -v docker-compose &> /dev/null
then
    docker-compose up -d --build
else
    docker compose up -d --build
fi

if [ $? -ne 0 ]; then
    echo "[错误] 容器启动失败，请检查 Docker 日志。"
    exit 1
fi

echo "======================================="
echo "[成功] 服务已成功在后台运行！"
echo ""
echo "访问入口："
echo "- 前端网页: http://localhost"
echo "- 后端 API : http://localhost:8000/api"
echo "- Neo4j 图库: http://localhost:7474 (默认账密：neo4j / password123)"
echo ""
echo "注意: 首次启动时，后端正在初始化导入本地解析的 Markdown 文件，可能需要几十秒时间，请耐心等待前端查询生效。"
echo "若要查看日志，请运行: docker compose logs -f"
echo ""
