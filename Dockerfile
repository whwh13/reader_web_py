# reader-py — 多阶段构建：前端 (Node) + 后端 (Python 3.12)
# 构建上下文 = 仓库根目录

# ---- 阶段 1：前端构建 ----
FROM node:22-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
# npmmirror 仅在 CI 网络不佳时使用；默认官方源
RUN npm ci --registry=https://registry.npmmirror.com
COPY frontend/ ./
RUN npm run build

# ---- 阶段 2：后端运行时 ----
FROM python:3.12-slim

WORKDIR /app

# 先装依赖（利用层缓存）
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir \
    --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    .

# 前端产物由后端静态托管
COPY --from=frontend-build /build/dist ./static

# 持久化数据目录：书源、书架、章节缓存、cookie、封面缓存
# 运行时挂载: -v /宿主路径/reader-data:/data
ENV READER_PY_DATA_DIR=/data \
    READER_PY_HOST=0.0.0.0 \
    READER_PY_PORT=8081
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"READER_PY_PORT\",\"8081\")}/health', timeout=3)" || exit 1

CMD ["python", "-m", "uvicorn", "reader.app:app", "--host", "0.0.0.0", "--port", "8081"]
