"""API 层公共工具：ReturnData 包装与统一参数读取。

legacy 契约（见 reference/legado.koplugin 与 reader-dev 源码）：
- HTTP 恒 200，业务结果在 {isSuccess, errorMsg, data} 中；
- 同一端点同时接受 GET(query) 与 POST(form 或 JSON body) 的同名参数；
- 登录令牌 accessToken 走 query 参数——本服务单用户免登录，直接忽略。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request


def ok(data: Any = None) -> dict:
    """成功 ReturnData。data 为空时给 {}，插件侧按 data 是否存在判断成功。"""
    return {"isSuccess": True, "errorMsg": "", "data": data if data is not None else {}}


def fail(error_msg: str = "", data: Any = None) -> dict:
    return {"isSuccess": False, "errorMsg": error_msg, "data": data if data is not None else {}}


class Params(dict):
    """query + form + JSON body 的合并视图（后者覆盖前者）。

    取值辅助统一做字符串→目标类型转换，兼容 legacy 前端/插件发来的各种类型。
    """

    def get_str(self, key: str, default: str = "") -> str:
        v = self.get(key, default)
        return default if v is None else str(v)

    def get_int(self, key: str, default: int = 0) -> int:
        v = self.get(key)
        if v is None or v == "":
            return default
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        v = self.get(key)
        if v is None or v == "":
            return default
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("1", "true", "yes", "on")


async def read_params(request: Request) -> Params:
    """合并 query、form、JSON body 为一个 Params。"""
    merged: dict[str, Any] = dict(request.query_params)

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict):
                merged.update(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    elif "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await request.form()
        for k, v in form.multi_items():
            merged[k] = v

    return Params(merged)
