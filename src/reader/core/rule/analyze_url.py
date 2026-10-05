"""URL 规则解析（对照 legacy AnalyzeUrl.kt）。

URL 形态：`url,{...JSON选项...}`，支持 `<js>`/@js:、{{js}} 内嵌、{{page,1,2,3}} 页码模板、
method/charset/headers/body/retry/type/webView/webJs/js 选项、query 编码、并发率限制。
网络请求本体在 core/net（P2），这里产出 RequestSpec。
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from reader.core.rule.js_engine import NullEngine, JsEngine
from reader.core.rule.rule_analyzer import RuleAnalyzer
from reader.core.rule.rule_data import RuleData
from reader.utils.net_utils import (
    get_absolute_url,
    get_base_url,
    has_url_encoded,
    js_escape,
    url_encode,
)

JS_PATTERN = re.compile(r"<js>([\w\W]*?)</js>|@js:([\w\W]*)", re.IGNORECASE)
_PARAM_PATTERN = re.compile(r"\s*,\s*(?=\{)")
_PAGE_PATTERN = re.compile(r"<(.*?)>")
_DATA_URI = re.compile(r"data:.*?;base64,(.*)")

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class ConcurrentException(Exception):
    def __init__(self, message: str, wait_time: int) -> None:
        super().__init__(message)
        self.wait_time = wait_time


def _is_json(s: str) -> bool:
    t = s.strip()
    if not t or t[0] not in ("{", "["):
        return False
    try:
        json.loads(t)
        return True
    except json.JSONDecodeError:
        return False


def _is_xml(s: str) -> bool:
    t = s.strip()
    return bool(t) and t[0] == "<" and t.endswith(">")


@dataclass
class RequestSpec:
    """解析后的请求规格（网络层执行它）。"""

    url: str
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    # form 字段（GET 时为 query；POST 且非 JSON/XML body 时为表单）
    fields: dict[str, str] = field(default_factory=dict)
    charset: str | None = None
    type: str | None = None
    retry: int = 0
    use_web_view: bool = False
    web_js: str | None = None
    url_no_query: str = ""


class ConcurrentRecord:
    def __init__(self, concurrent: bool) -> None:
        self.concurrent = concurrent
        self.time = time.time() * 1000
        self.frequency = 1


_concurrent_lock = threading.Lock()
_concurrent_records: dict[str, ConcurrentRecord] = {}


class AnalyzeUrl:
    def __init__(
        self,
        m_url: str,
        key: str | None = None,
        page: int | None = None,
        base_url: str = "",
        source=None,
        rule_data: RuleData | None = None,
        chapter: RuleData | None = None,
        header_map: dict[str, str] | None = None,
        js_engine: JsEngine | None = None,
        http_client=None,
        cookie_store=None,
    ) -> None:
        self.m_url = m_url
        self.key = key
        self.page = page
        self.base_url = base_url
        self.source = source
        self.rule_data = rule_data
        self.chapter = chapter
        self.js_engine: JsEngine = js_engine or NullEngine()

        self.rule_url = ""
        self.url = ""
        self.body: str | None = None
        self.type: str | None = None
        self.header_map: dict[str, str] = {}
        self.url_no_query = ""
        self.query_str: str | None = None
        self.field_map: dict[str, str] = {}
        self.charset: str | None = None
        self.method = "GET"
        self.proxy: str | None = None
        self.retry = 0
        self.use_web_view = False
        self.web_js: str | None = None
        self.enabled_cookie_jar = bool(getattr(source, "enabled_cookie_jar", False))
        # 供 JS 桥（java.ajax 等）使用：构造期就绪（searchUrl 的 JS 在 _init_url 里即可能调 ajax）
        self.http_client = http_client
        self.cookie_store = cookie_store

        if m_url.startswith("data:"):
            return
        # baseUrl 同样可能是 "url,{option}" 形式
        m = _PARAM_PATTERN.search(self.base_url)
        if m:
            self.base_url = self.base_url[: m.start()]
        headers = header_map or (source.get_header_map(True) if source else None)
        if headers:
            self.header_map.update(headers)
            if "proxy" in headers:
                self.proxy = headers["proxy"]
                del self.header_map["proxy"]
        self._init_url()

    # ---- 变量 ----

    def put(self, key: str, value: str) -> str:
        target = self.chapter or self.rule_data
        if target is not None:
            target.put_variable(key, value)
        return value

    def get(self, key: str) -> str:
        if key == "bookName" and self.rule_data is not None:
            return getattr(self.rule_data, "name", "") or ""
        if key == "title" and self.chapter is not None:
            return getattr(self.chapter, "title", "") or ""
        v = None
        if self.chapter is not None:
            v = self.chapter.get_variable(key)
        if v is None and self.rule_data is not None:
            v = self.rule_data.get_variable(key)
        return v or ""

    def eval_js(self, js_str: str, result: Any = None) -> Any:
        bindings: dict[str, Any] = {
            "java": self,
            "baseUrl": self.base_url,
            "cookie": None,
            "cache": None,
            "page": self.page,
            "key": self.key,
            "speakText": None,
            "speakSpeed": None,
            "book": _js_safe(self.rule_data),
            "source": _js_safe(self.source),
            "result": result,
        }
        return self.js_engine.eval(js_str, bindings, host=self)

    # ---- URL 处理 ----

    def _init_url(self) -> None:
        self.rule_url = self.m_url
        self._analyze_js()
        self._replace_key_page_js()
        self._analyze_url()

    def _analyze_js(self) -> None:
        """执行 @js/<js> 段，@result 代表原 URL。"""
        start = 0
        for m in JS_PATTERN.finditer(self.rule_url):
            if m.start() > start:
                tmp = self.rule_url[start : m.start()].strip()
                if tmp:
                    self.rule_url = tmp.replace("@result", self.rule_url)
            js_code = m.group(2) or m.group(1)
            evaled = self.eval_js(js_code, self.rule_url)
            self.rule_url = str(evaled)
            start = m.end()
        if len(self.rule_url) > start:
            tmp = self.rule_url[start:].strip()
            if tmp:
                self.rule_url = tmp.replace("@result", self.rule_url)

    def _replace_key_page_js(self) -> None:
        """替换 {{js}} 与 {{page,1,2,3}}/<...> 页码模板。"""
        if "{{" in self.rule_url and "}}" in self.rule_url:
            analyzer = RuleAnalyzer(self.rule_url)
            url = analyzer.inner_rule_pair("{{", "}}", self._eval_js_str)
            if url:
                self.rule_url = url
        if self.page is not None:
            for m in _PAGE_PATTERN.finditer(self.rule_url):
                pages = m.group(1).split(",")
                page_index = self.page - 1  # legacy page 从 1 开始
                if page_index < len(pages):
                    replacement = pages[page_index].strip()
                else:
                    replacement = pages[-1].strip()
                self.rule_url = self.rule_url.replace(m.group(0), replacement)

    def _eval_js_str(self, js: str) -> str | None:
        evaled = self.eval_js(js)
        if evaled is None:
            return None
        if isinstance(evaled, str):
            return evaled
        if isinstance(evaled, float) and evaled % 1.0 == 0.0:
            return f"{evaled:.0f}"
        return str(evaled)

    def _analyze_url(self) -> None:
        m = _PARAM_PATTERN.search(self.rule_url)
        url_no_option = self.rule_url[: m.start()] if m else self.rule_url
        self.url = get_absolute_url(self.base_url, url_no_option)
        base = get_base_url(self.url)
        if base:
            self.base_url = base
        if m and len(url_no_option) != len(self.rule_url):
            try:
                option = json.loads(self.rule_url[m.end() :])
            except json.JSONDecodeError:
                option = None
            if isinstance(option, dict):
                self._apply_option(option)
        if "User-Agent" not in self.header_map:
            self.header_map["User-Agent"] = DEFAULT_UA
        self.url_no_query = self.url
        if self.method == "GET":
            pos = self.url.find("?")
            if pos != -1:
                self._analyze_fields(self.url[pos + 1 :])
                self.url_no_query = self.url[:pos]
        else:
            if self.body and not _is_json(self.body) and not _is_xml(self.body):
                if not self.header_map.get("Content-Type"):
                    self._analyze_fields(self.body)

    def _apply_option(self, option: dict[str, Any]) -> None:
        method = option.get("method")
        if method and str(method).strip():
            if str(method).upper() == "POST":
                self.method = "POST"
        headers = option.get("headers")
        if isinstance(headers, str):
            try:
                headers = json.loads(headers)
            except json.JSONDecodeError:
                headers = None
        if isinstance(headers, dict):
            for k, v in headers.items():
                self.header_map[str(k)] = str(v)
        body = option.get("body")
        if body is not None:
            self.body = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        self.type = _clean(option.get("type"))
        self.charset = _clean(option.get("charset"))
        retry = option.get("retry")
        if retry not in (None, ""):
            try:
                self.retry = int(retry)
            except (TypeError, ValueError):
                self.retry = 0
        self.use_web_view = _truthy(option.get("webView"))
        self.web_js = _clean(option.get("webJs"))
        js = _clean(option.get("js"))
        if js:
            evaled = self.eval_js(js, self.url)
            if evaled is not None:
                self.url = str(evaled)

    def _analyze_fields(self, fields_txt: str) -> None:
        """query/form 编码（对照 analyzeFields；splitNotBlank("=") 全切取 [1]）。"""
        self.query_str = fields_txt
        for query in fields_txt.split("&"):
            if not query.strip():
                continue
            parts = [p for p in query.split("=") if p.strip()]
            if not parts:
                continue
            name = parts[0]
            value = parts[1] if len(parts) > 1 else ""
            if not self.charset:
                if has_url_encoded(value):
                    self.field_map[name] = value
                else:
                    self.field_map[name] = url_encode(value, "utf-8")
            elif self.charset == "escape":
                self.field_map[name] = js_escape(value)
            else:
                self.field_map[name] = url_encode(value, self.charset)

    # ---- 请求规格 ----

    def build_request(self) -> RequestSpec:
        return RequestSpec(
            url=self.url,
            method=self.method,
            headers=dict(self.header_map),
            body=self.body,
            fields=dict(self.field_map),
            charset=self.charset,
            type=self.type,
            retry=self.retry,
            use_web_view=self.use_web_view,
            web_js=self.web_js,
            url_no_query=self.url_no_query,
        )

    # ---- 并发率（对照 fetchStart/fetchEnd，书源级限流）----

    def _source_key(self) -> str | None:
        return getattr(self.source, "get_key", lambda: None)() if self.source else None

    def fetch_start(self) -> ConcurrentRecord | None:
        if self.source is None:
            return None
        rate = getattr(self.source, "concurrent_rate", None)
        if not rate:
            return None
        key = self._source_key()
        rate_index = rate.find("/")
        with _concurrent_lock:
            record = _concurrent_records.get(key)
            if record is None:
                record = ConcurrentRecord(rate_index > 0)
                _concurrent_records[key] = record
                return record
            try:
                now = time.time() * 1000
                if rate_index == -1:
                    if record.frequency > 0:
                        wait = int(rate)
                        raise _Wait(wait)
                    next_time = record.time + int(rate)
                    if now >= next_time:
                        record.time = now
                        record.frequency = 1
                        wait = 0
                    else:
                        wait = int(next_time - now)
                        raise _Wait(wait)
                else:
                    interval = int(rate[rate_index + 1 :])
                    next_time = record.time + interval
                    if now >= next_time:
                        record.time = now
                        record.frequency = 1
                        wait = 0
                    else:
                        limit = int(rate[:rate_index])
                        if record.frequency > limit:
                            wait = int(next_time - now)
                            raise _Wait(wait)
                        record.frequency += 1
                        wait = 0
            except _Wait as w:
                wait = w.ms
            except Exception:
                wait = 0
        if wait > 0:
            raise ConcurrentException(f"根据并发率还需等待{wait}毫秒才可以访问", wait_time=wait)
        return record

    def fetch_end(self, record: ConcurrentRecord | None) -> None:
        if record is not None and not record.concurrent:
            with _concurrent_lock:
                record.frequency -= 1


class _Wait(Exception):
    def __init__(self, ms: int) -> None:
        self.ms = ms


def _js_safe(v):
    if hasattr(v, "model_dump"):
        try:
            return v.model_dump()
        except Exception:
            return str(v)
    return v


def _clean(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _truthy(v: Any) -> bool:
    if v in (None, "", False, "false"):
        return False
    return bool(v)
