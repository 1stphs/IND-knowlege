# 阶段 1：构建 React 产物
FROM node:20-alpine AS build

WORKDIR /app

# 拷贝并安装前端依赖
COPY rag_frontend/package.json rag_frontend/package-lock.json* ./
RUN npm install

# 拷贝前端代码并打包
COPY rag_frontend ./
RUN npm run build

# 阶段 2：Nginx 提供服务
FROM nginx:alpine

# 拷贝静态页面产物
COPY --from=build /app/dist /usr/share/nginx/html

# 编写 Nginx 配置文件代理 /api 请求
RUN echo 'server { \
    listen 80; \
    location / { \
        root /usr/share/nginx/html; \
        index index.html index.htm; \
        try_files $uri $uri/ /index.html; \
    } \
    location /api/ { \
        proxy_pass http://backend:8000/api/; \
        proxy_set_header Host $host; \
        proxy_set_header X-Real-IP $remote_addr; \
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; \
    } \
}' > /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
