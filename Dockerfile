# reader-py — 多阶段构建：前端 (Node) + 后端 (Python 3.12)
# 构建上下文 = 仓库根目录。CI（GitHub Actions）网络 OK，FROM 官方镜像名。
# 本地调试（wslc，docker.io 拉不到）用 Dockerfile.local（基础镜像指向国内镜像源，
# 不进 git），构建：container build -t reader-web-py:<版本>-dev -f Dockerfile.local .

# ---- 阶段 1：前端构建 ----
FROM node:22-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
# npmmirror 仅在 CI 网络不佳时使用；默认官方源
RUN npm ci --registry=https://registry.npmmirror.com
COPY frontend/ ./
RUN npm run build

# ---- 阶段 2：后端依赖编译 ----
FROM python:3.12-slim AS pydeps
# quickjs 在部分平台（arm64）无预编译轮，需要源码编译：gcc 只装在本阶段
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY reader/ ./reader/
RUN pip install --no-cache-dir --prefix=/install \
    --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    .

# ---- 阶段 3：运行时 ----
FROM python:3.12-slim
WORKDIR /app
COPY --from=pydeps /install /usr/local

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
