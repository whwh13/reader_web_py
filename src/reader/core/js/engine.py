"""QuickJS 沙箱引擎。

书源 JS 通过单一 `__bridge(method, argsJson)` 回调进入 Python，
JS 前导码把 java.*/cookie/cache 包装成宿主对象，规避各绑定库
callable 注入语义差异。每次 eval 用独立 Context，天然线程隔离。
"""

from __future__ import annotations

import json
import json
import threading
from typing import Any

import quickjs

from reader.core.rule.js_engine import JsEngine
from reader.core.js.bridge import JsBridge

_PREAMBLE = """
function __mkBridge(name, methods) {
    var obj = {};
    methods.forEach(function (m) {
        obj[m] = function () {
            var args = Array.prototype.slice.call(arguments);
            var raw = JSON.stringify(args);
            var res = __bridge(name + "." + m, raw);
            return res === null || res === undefined ? null : JSON.parse(res);
        };
    });
    return obj;
}
var java = __mkBridge("java", JSON.parse(__JAVA_METHODS__));
var cookie = __mkBridge("cookie", JSON.parse(__COOKIE_METHODS__));
var cache = __mkBridge("cache", JSON.parse(__CACHE_METHODS__));
"""


class QuickJsEngine(JsEngine):
    """每次 eval 独立 Context；桥对象由 JSBridge 提供方法表。"""

    def __init__(self, bridge: JsBridge) -> None:
        self.bridge = bridge
        self._lock = threading.Lock()

    def eval(self, js: str, bindings: dict[str, Any]) -> Any:
        with self._lock:  # quickjs Context 非线程安全，串行化
            ctx = quickjs.Context()
            ctx.add_callable("__bridge", self.bridge.dispatch)
            ctx.set("__JAVA_METHODS__", json.dumps(self.bridge.java_methods))
            ctx.set("__COOKIE_METHODS__", json.dumps(self.bridge.cookie_methods))
            ctx.set("__CACHE_METHODS__", json.dumps(self.bridge.cache_methods))
            ctx.eval(_PREAMBLE)
            for key, value in bindings.items():
                if value is None:
                    continue
                try:
                    ctx.set(key, value)
                except TypeError:
                    # 不可 JSON 化的对象（lxml 元素等）降级为字符串
                    ctx.set(key, str(value))
            try:
                return ctx.eval(js)
            except quickjs.JSException as e:
                raise RuntimeError(f"JS 执行失败: {e}") from e
