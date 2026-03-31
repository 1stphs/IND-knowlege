FROM python:3.10-slim

WORKDIR /app

# 安装必要的系统依赖 (针对某些可能需要编译的python包)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 将 requirements.txt 拷贝进去并安装
COPY rag_backend/requirements.txt /app/rag_backend/
RUN pip install --no-cache-dir -r /app/rag_backend/requirements.txt

# 拷贝后端代码和必要的库文件
COPY rag_backend /app/rag_backend
COPY lib /app/lib

# 暴露端口
EXPOSE 8000

# 启动脚本：先初始化数据再启动服务
# 这里设定 PYTHONPATH 让 uvicorn 可以正确找包
ENV PYTHONPATH=/app
CMD ["sh", "-c", "python rag_backend/init_db.py && python rag_backend/main.py --host 0.0.0.0 --port 8000"]
