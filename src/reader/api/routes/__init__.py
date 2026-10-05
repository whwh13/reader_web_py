"""/reader3 业务路由。按域拆分模块，这里聚合。"""

from fastapi import APIRouter

from reader.api.routes import reader3

api_router = APIRouter()
api_router.include_router(reader3.router)
