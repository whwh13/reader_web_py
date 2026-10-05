"""API 路由聚合。

/health 在根路径（对齐 legacy RestVerticle）；业务端点全部挂在 /reader3 下。
"""

from fastapi import APIRouter

from reader.api import helpers

root_router = APIRouter()
reader3 = APIRouter(prefix="/reader3")


@root_router.get("/health")
async def health():
    return helpers.ok("ok!")
