"""API 路由聚合。

/health、/version 在根路径；业务端点全部挂在 /reader3 下。
"""

from fastapi import APIRouter

from reader import __version__
from reader.api import helpers

root_router = APIRouter()
reader3 = APIRouter(prefix="/reader3")


@root_router.get("/health")
async def health():
    return helpers.ok("ok!")


@root_router.get("/version")
async def version():
    return helpers.ok({"name": "reader-py", "version": __version__})
