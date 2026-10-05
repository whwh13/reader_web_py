"""FastAPI 应用工厂。"""

from __future__ import annotations

import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from reader import __version__
from reader.api import root_router
from reader.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="reader-py", version=__version__, lifespan=lifespan)

    # 本地单用户工具：放开 CORS，方便前端 dev server 与 KOReader 插件调试
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(root_router)

    # 正文图片 / EPUB 解包资源（对齐 legacy /book-assets/* 与 /epub/*）
    book_assets = Path(settings.data_dir) / "book_assets"
    book_assets.mkdir(parents=True, exist_ok=True)
    mimetypes.add_type("image/webp", ".webp")
    app.mount("/book-assets", StaticFiles(directory=book_assets), name="book-assets")

    from reader.api.routes import api_router

    app.include_router(api_router)

    # Docker 镜像内打包的前端（frontend 构建产物复制到镜像 /app/static；本地开发用 Vite dev）。
    # pip 安装后 reader 包在 site-packages，__file__ 推不出 /app——优先找包同级，再找 cwd。
    candidates = [
        Path(__file__).resolve().parent.parent / "static",
        Path.cwd() / "static",
    ]
    static_dir = next((p for p in candidates if p.is_dir()), None)
    if static_dir:
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app


app = create_app()
