"""异步 HTTP 客户端（对照 legacy OkHttp 封装 + StrResponse）。

- charset 选项与响应头优先，其次 charset-normalizer 探测（GBK 站点兜底）；
- Set-Cookie 写回按书源隔离的 CookieStore；
- retry 支持。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import httpx
import charset_normalizer

from reader.core.net.cookie_store import CookieStore
from reader.core.rule.analyze_url import AnalyzeUrl, RequestSpec
from reader.models.book_source import BookSource


@dataclass
class StrResponse:
    url: str
    body: str | None
    headers: dict[str, str] = field(default_factory=dict)
    code: int = 200


class HttpClient:
    def __init__(self, cookie_store: CookieStore) -> None:
        self.cookie_store = cookie_store

    async def fetch_str(
        self,
        analyze_url: AnalyzeUrl,
        retry: int | None = None,
    ) -> StrResponse:
        """执行 AnalyzeUrl 解析出的请求（webview 书源在 MVP 中不支持）。"""
        spec = analyze_url.build_request()
        record = analyze_url.fetch_start()
        try:
            return await self._fetch(spec, analyze_url, retry)
        finally:
            analyze_url.fetch_end(record)

    def fetch_str_sync(self, analyze_url: AnalyzeUrl, retry: int | None = None) -> StrResponse:
        """同步版本：专供 JS 桥线程内阻塞调用（java.ajax 等）。"""
        spec = analyze_url.build_request()
        record = analyze_url.fetch_start()
        try:
            source = analyze_url.source
            source_key = source.get_key() if source else spec.url
            attempts = (retry if retry is not None else spec.retry) + 1
            last_error: Exception | None = None
            for attempt in range(attempts):
                try:
                    return self._do_request_sync(spec, source_key)
                except (httpx.HTTPError, OSError) as e:
                    last_error = e
                    if attempt + 1 < attempts:
                        time.sleep(0.5)
            raise ConnectionError(f"请求失败 {spec.url}: {last_error}")
        finally:
            analyze_url.fetch_end(record)

    def _do_request_sync(self, spec: RequestSpec, source_key: str) -> StrResponse:
        headers = dict(spec.headers)
        cookies = self.cookie_store.load_for_request(source_key, spec.url)
        with httpx.Client(
            follow_redirects=True,
            timeout=20.0,
            cookies=cookies,
            headers=headers,
        ) as client:
            if spec.method == "POST":
                body = spec.body
                content_type = headers.get("Content-Type") or headers.get("content-type")
                if spec.fields and (body is None or not body.strip()):
                    response = client.post(spec.url_no_query, data=spec.fields)
                elif body is not None and content_type:
                    response = client.post(
                        spec.url_no_query, content=body.encode("utf-8"),
                        headers={"Content-Type": content_type},
                    )
                elif body is not None and _is_json_text(body):
                    response = client.post(
                        spec.url_no_query, content=body.encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                elif body is not None:
                    response = client.post(spec.url_no_query, data=body.encode("utf-8"))
                else:
                    response = client.post(spec.url_no_query, data=spec.fields)
            else:
                response = client.get(_final_url(spec))
            self.cookie_store.save_from_response(source_key, response)
            text = _decode(response, spec.charset)
            resp_headers = {
                k: v for k, v in response.headers.multi_items() if k.lower() != "set-cookie"
            }
            return StrResponse(url=str(response.url), body=text, headers=resp_headers, code=response.status_code)

    async def _fetch(self, spec: RequestSpec, analyze_url: AnalyzeUrl, retry: int | None) -> StrResponse:
        source = analyze_url.source
        source_key = source.get_key() if source else spec.url
        attempts = (retry if retry is not None else spec.retry) + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return await self._do_request(spec, source_key)
            except (httpx.HTTPError, OSError) as e:
                last_error = e
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.5)
        raise ConnectionError(f"请求失败 {spec.url}: {last_error}")

    async def _do_request(self, spec: RequestSpec, source_key: str) -> StrResponse:
        headers = dict(spec.headers)
        cookies = self.cookie_store.load_for_request(source_key, spec.url)
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=20.0,
            cookies=cookies,
            headers=headers,
        ) as client:
            if spec.method == "POST":
                body = spec.body
                content_type = headers.get("Content-Type") or headers.get("content-type")
                if spec.fields and (body is None or not body.strip()):
                    response = await client.post(spec.url_no_query, data=spec.fields)
                elif body is not None and content_type:
                    response = await client.post(
                        spec.url_no_query, content=body.encode("utf-8"),
                        headers={"Content-Type": content_type},
                    )
                elif body is not None and _is_json_text(body):
                    response = await client.post(
                        spec.url_no_query, content=body.encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                elif body is not None:
                    response = await client.post(spec.url_no_query, data=body.encode("utf-8"))
                else:
                    response = await client.post(spec.url_no_query, data=spec.fields)
            else:
                response = await client.get(_final_url(spec))

            self.cookie_store.save_from_response(source_key, response)
            text = _decode(response, spec.charset)
            resp_headers = {
                k: v for k, v in response.headers.multi_items() if k.lower() != "set-cookie"
            }
            return StrResponse(url=str(response.url), body=text, headers=resp_headers, code=response.status_code)


def _is_json_text(s: str) -> bool:
    t = s.strip()
    return bool(t) and t[0] in ("{", "[")


def _decode(response: httpx.Response, charset: str | None) -> str:
    """解码响应体：显式 charset > 响应头 > 内容探测。"""
    raw = response.content
    if charset and charset.lower() not in ("escape",):
        try:
            return raw.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            pass
    ct = response.headers.get("content-type", "")
    if "charset=" in ct:
        declared = ct.split("charset=")[-1].split(";")[0].strip().strip('"')
        try:
            return raw.decode(declared, errors="replace")
        except (LookupError, UnicodeDecodeError):
            pass
    detected = charset_normalizer.detect(raw)
    encoding = detected.get("encoding") or "utf-8"
    try:
        return raw.decode(encoding, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")


def _final_url(spec: RequestSpec) -> str:
    """拼接已编码的 query（_analyze_fields 预编码过，httpx params 会二次编码）。"""
    if not spec.fields:
        return spec.url_no_query
    query = "&".join(f"{k}={v}" for k, v in spec.fields.items())
    return f"{spec.url_no_query}?{query}"
