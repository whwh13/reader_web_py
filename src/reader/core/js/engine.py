"""QuickJS 沙箱引擎。

书源 JS 通过单一 `__bridge(method, argsJson)` 回调进入 Python，
JS 前导码把 java.*/cookie/cache 包装成宿主对象，规避各绑定库
callable 注入语义差异。每次 eval 用独立 Context，天然线程隔离。

`java`/`cookie`/`cache` 三个名字由前导码独占（bindings 里同名键会被忽略），
桥回调按每次 eval 的 host（AnalyzeRule/AnalyzeUrl）绑定网络与变量上下文。
source/book/chapter 在绑定后补回 getKey() 等方法（Rhino 下是活对象，QuickJS 只收 JSON 快照）。
"""

from __future__ import annotations

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
var java = new Proxy(__mkBridge("java", JSON.parse(__JAVA_METHODS__)), {
    get: function (t, prop) {
        if (prop in t) return t[prop];
        return function () { throw new Error("__MISSING__java." + String(prop)); };
    }
});
var cookie = __mkBridge("cookie", JSON.parse(__COOKIE_METHODS__));
var cache = __mkBridge("cache", JSON.parse(__CACHE_METHODS__));
// org.jsoup.Jsoup shim：桥回调到 Python 端做 HTML 解析（Rhino 的 Java import 等价物）
var org = {
    jsoup: {
        Jsoup: {
            parse: function (html) {
                var handle = __bridge("jsoup.parse", JSON.stringify([String(html)]));
                return __mkJsoupDoc(handle);
            }
        }
    }
};
function __mkJsoupDoc(handle) {
    return {
        select: function (css) {
            var arr = JSON.parse(__bridge("jsoup.select", JSON.stringify([handle, css])));
            return {
                text: function () { return arr.length ? arr[0] : ""; },
                attr: function (n) { return arr.length ? (arr[0][n] || "") : ""; },
                size: function () { return arr.length; }
            };
        },
        text: function () { return __bridge("jsoup.text", JSON.stringify([handle])); },
        outerHtml: function () { return __bridge("jsoup.outerHtml", JSON.stringify([handle])); }
    };
}
function __augment(obj) {
    if (!obj || typeof obj !== "object" || Array.isArray(obj)) return obj;
    if (obj.getKey === undefined) {
        obj.getKey = function () { return obj.bookSourceUrl || obj.bookUrl || obj.url || ""; };
    }
    if (obj.getLogKey === undefined) obj.getLogKey = obj.getKey;
    return obj;
}
"""

# 绑定后执行的 augment（前导码时 source/book/chapter 尚未定义）
_AUGMENT_BINDINGS = """
function __augmentAll(keys) {
    for (var i = 0; i < keys.length; i++) {
        try { eval("__augment(" + keys[i] + ")"); } catch (e) {}
    }
}
"""

# 由前导码提供的名字，bindings 不得覆盖
_RESERVED = ("java", "cookie", "cache", "__bridge")


def _to_py(v):
    """quickjs Object → Python 原生类型（dict/list 引擎出口统一转换）。"""
    if isinstance(v, quickjs.Object):
        try:
            return _to_py(json.loads(v.json()))
        except Exception:
            return str(v)
    if isinstance(v, list):
        return [_to_py(x) for x in v]
    if isinstance(v, dict):
        return {k: _to_py(x) for k, x in v.items()}
    return v


class QuickJsEngine(JsEngine):
    """每次 eval 独立 Context；桥对象由 JSBridge 提供方法表。"""

    def __init__(self, bridge: JsBridge) -> None:
        self.bridge = bridge
        self._lock = threading.RLock()  # 同线程可重入：searchUrl 的 JS 里调 java.ajax 会嵌套 eval

    def eval(self, js: str, bindings: dict[str, Any], host: Any = None) -> Any:
        with self._lock:  # quickjs Context 非线程安全，串行化
            ctx = quickjs.Context()
            ctx.add_callable("__bridge", self.bridge.dispatch_for(host))
            ctx.set("__JAVA_METHODS__", json.dumps(self.bridge.java_methods))
            ctx.set("__COOKIE_METHODS__", json.dumps(self.bridge.cookie_methods))
            ctx.set("__CACHE_METHODS__", json.dumps(self.bridge.cache_methods))
            ctx.eval(_PREAMBLE)
            bound: list[str] = []
            for key, value in bindings.items():
                if key in _RESERVED:
                    continue
                bound.append(key)
                if value is None:
                    # None 绑定须落为 JS null（跳过会让源里 book/key 判空变成 ReferenceError）
                    ctx.eval(f"var {key} = null")
                elif isinstance(value, (dict, list)):
                    # quickjs set 只认 JSON 标量；dict/list 走 JSON 字符串 + JS 端 parse
                    # （ctx.set(dict) 会 TypeError，降级 str 的旧路径产生 "[object Object]"）
                    ctx.set("__PAYLOAD__", json.dumps(value, ensure_ascii=False, default=str))
                    if key == "result":
                        # Java/Rhino 的 String coercion：List/Map 传给 JS 时 toString()
                        # 即 JSON 兼容串——书源里 JSON.parse(result) 依赖此语义
                        ctx.eval("var result = __PAYLOAD__")
                    else:
                        ctx.eval(f"var {key} = JSON.parse(__PAYLOAD__)")
                else:
                    try:
                        ctx.set(key, value)
                    except TypeError:
                        # 不可 JSON 化的对象（lxml 元素等）降级为字符串
                        ctx.set(key, str(value))
            # 绑定完成后给 source/book/chapter 补方法（getKey 等）
            if bound:
                ctx.eval(_AUGMENT_BINDINGS)
                ctx.eval("__augmentAll(" + json.dumps(bound) + ")")
            try:
                return _to_py(ctx.eval(js))
            except quickjs.JSException as e:
                raise RuntimeError(f"JS 执行失败: {e}") from e
