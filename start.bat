@echo off
echo =======================================
echo   IND Knowledge RAG 系统一键启动脚本
echo =======================================

echo 检查 Docker 环境...
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 请先安装 Docker Desktop 并确保其正在运行。
    pause
    exit /b
)

if not exist ".env" (
    echo [提示] 未找到 .env 文件，如果需要设置 API KEY 自定义配置，请复制 .env.example 并重命名为 .env
    if exist ".env.example" (
        copy .env.example .env
        echo [成功] 自动基于 .env.example 生成了 .env，请编辑填写密钥后重新启动。
        pause
        exit /b
    )
)

echo [进行中] 正在通过 Docker Compose 构建并启动环境...
docker compose up -d --build

if %errorlevel% neq 0 (
    echo [错误] 容器启动失败，请检查 Docker 日志。
    pause
    exit /b
)

echo =======================================
echo [成功] 服务已成功在后台运行！
echo.
echo 访问入口：
echo - 前端网页: http://localhost
echo - 后端 API : http://localhost:8000/api
echo - Neo4j 图库: http://localhost:7474 (默认账密：neo4j / password123)
echo.
echo 注意: 首次启动时，后端正在初始化导入本地解析的 Markdown 文件，请耐心等待几秒钟再刷新前端。
echo.
pause
