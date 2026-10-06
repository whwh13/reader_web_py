"""JS 执行引擎接口。

P1 阶段用 NullEngine（执行 JS 时报错）；P2 接入 quickjs。
AnalyzeRule / AnalyzeUrl 只依赖该协议。
"""

from __future__ import annotations

from typing import Any, Protocol


class JsEngine(Protocol):
    """执行 JS 片段。result 为注入的 `result` 绑定值。"""

    def eval(self, js: str, bindings: dict[str, Any]) -> Any: ...


class JsUnavailableError(RuntimeError):
    pass


class NullEngine:
    """占位引擎：书源含 JS 时明确报错，便于识别需要 P2 能力的规则。"""

    def eval(self, js: str, bindings: dict[str, Any]) -> Any:
        raise JsUnavailableError(f"规则包含 JS 但 JS 引擎未启用: {js[:80]}...")
