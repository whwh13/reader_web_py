"""java.* 桥 v1（对照 legacy JsExtensions.kt，按书源命中频率分期实现）。

v1 覆盖高频方法：ajax/ajaxAll/connect/get/post/head、base64/md5/digest、
AES/DES/3DES、encodeURI/utf8ToGbk、htmlFormat、timeFormat、cacheFile、
zip 读取、getCookie、cache put/get、日志桩。
v1 暂缺：queryTTF 字体反爬（返回原文）、webView 桩（返回 null）。
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
import zipfile
import io
from typing import Any, Callable
from urllib.parse import quote

from Crypto.Cipher import AES, DES, DES3
from Crypto.Hash import MD5 as _MD5
from Crypto.Util.Padding import pad, unpad

from reader.core.net.http_client import StrResponse


def _b64decode(s: str, flags: int = 0) -> bytes:
    s = s.strip().replace("\n", "").replace("\r", "")
    # 容忍 URL-safe 与缺省 padding
    s = s.replace("-", "+").replace("_", "/")
    pad_len = (-len(s)) % 4
    return base64.b64decode(s + "=" * pad_len)


def _to_b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _unhex(s: str) -> bytes:
    s = s.strip()
    if len(s) % 2:
        s = "0" + s
    return bytes.fromhex(s)


def _crypto_decrypt(mode_factory, key, data, iv, padding: bool):
    cipher = mode_factory(key, iv) if iv is not None else mode_factory(key)
    if padding:
        return unpad(cipher.decrypt(data), 16) if isinstance(cipher, (AES,)) else cipher.decrypt(data)
    return cipher.decrypt(data)


class JsBridge:
    """把 JsExtensions 方法暴露给 JS。所有方法同步阻塞（运行于 JS 工作线程）。"""

    def __init__(self, host_provider: Callable[[], Any]) -> None:
        # host_provider 返回当前执行宿主（AnalyzeRule/AnalyzeUrl），提供网络与变量能力
        self._host_provider = host_provider
        self.java_methods = [
            "ajax", "ajaxAll", "connect", "get", "post", "head",
            "base64Decode", "base64Encode", "base64DecodeToByteArray",
            "md5Encode", "md5Encode16", "digestHex", "digestBase64Str",
            "aesDecodeToString", "aesDecodeToByteArray",
            "aesBase64DecodeToString", "aesBase64DecodeToByteArray",
            "aesEncodeToString", "aesEncodeToBase64String",
            "desDecodeToString", "desBase64DecodeToString",
            "desEncodeToString", "desEncodeToBase64String",
            "tripleDESDecodeStr", "tripleDESEncodeBase64Str",
            "tripleDESDecodeArgsBase64Str", "tripleDESEncodeArgsBase64Str",
            "encodeURI", "utf8ToGbk", "htmlFormat",
            "timeFormat", "timeFormatUTC", "randomUUID", "androidId",
            "cacheFile", "get", "post", "log", "toast",
            "getCookie", "getZipStringContent", "getZipByteArrayContent",
            "importScript", "queryTTF", "queryBase64TTF", "replaceFont",
            "webView", "getFile", "readFile", "readTxtFile", "deleteFile",
            "downloadFile", "unzipFile", "getTxtInFolder",
        ]
        self.cookie_methods = ["getCookie", "setCookie", "removeCookie", "cookieToMap", "mapToCookie"]
        self.cache_methods = ["put", "get", "getInt", "putInt", "putLong", "getLong", "delete", "putFile", "getFile"]
        self._cache: dict[str, str] = {}
        self._cache_file: dict[str, str] = {}

    # ---- 派发 ----

    def dispatch(self, full_name: str, args_json: str) -> str | None:
        kind, _, method = full_name.partition(".")
        args = json.loads(args_json) if args_json else []
        table = {
            "java": self._java_table(),
            "cookie": self._cookie_table(),
            "cache": self._cache_table(),
        }[kind]
        fn = table.get(method)
        if fn is None:
            return None
        result = fn(*args)
        if result is None:
            return None
        return json.dumps(result, ensure_ascii=False, default=str)

    # ---- java.* ----

    def _host(self):
        return self._host_provider()

    def _http(self) -> Any:
        host = self._host()
        return host.http_client if hasattr(host, "http_client") else host

    def _ajax_spec(self, url_str: str, headers: dict | None = None):
        """用 AnalyzeUrl 解析 ajax URL（同步 httpx 在 JS 线程内阻塞执行）。"""
        from reader.core.rule.analyze_url import AnalyzeUrl

        host = self._host()
        base = getattr(host, "base_url", "") or ""
        source = getattr(host, "source", None)
        analyze = AnalyzeUrl(
            m_url=url_str,
            base_url=base if base.startswith("http") else "",
            source=source,
            rule_data=getattr(host, "book", None) or getattr(host, "rule_data", None),
            js_engine=getattr(host, "js_engine", None),
        )
        if headers:
            analyze.header_map.update({str(k): str(v) for k, v in headers.items()})
        return analyze

    def _fetch_sync(self, url_str: str, headers: dict | None = None) -> StrResponse | None:
        host = self._host()
        analyze = self._ajax_spec(url_str, headers)
        return host.http_client.fetch_str_sync(analyze)

    def _ajax(self, url_str: str, headers: dict | None = None) -> str | None:
        resp = self._fetch_sync(url_str, headers)
        return resp.body if resp else None

    def _java_table(self) -> dict[str, Callable]:
        return {
            "ajax": lambda url, *rest: self._ajax(url),
            "ajaxAll": lambda urls, *rest: [self._ajax(u) for u in urls],
            "connect": self._connect,
            "get": self._get,
            "post": self._post,
            "head": self._head,
            "base64Decode": lambda s, *a: _try_decode(_b64decode(s)),
            "base64Encode": lambda s, *a: _to_b64(str(s).encode("utf-8")),
            "base64DecodeToByteArray": lambda s, *a: list(_b64decode(s)),
            "md5Encode": lambda s: hashlib.md5(str(s).encode("utf-8")).hexdigest(),
            "md5Encode16": lambda s: hashlib.md5(str(s).encode("utf-8")).hexdigest()[8:24],
            "digestHex": lambda data, algo: hashlib.new(str(algo).replace("-", "").lower(), _as_bytes(data)).hexdigest(),
            "digestBase64Str": lambda data, algo: _to_b64(hashlib.new(str(algo).replace("-", "").lower(), _as_bytes(data)).digest()),
            "aesDecodeToString": lambda data, key, *a: _aes_dec_str(data, key, a),
            "aesDecodeToByteArray": lambda data, key, *a: list(_aes_dec(data, key, a)),
            "aesBase64DecodeToString": lambda data, key, *a: _aes_dec_str(data, key, a, b64=True),
            "aesBase64DecodeToByteArray": lambda data, key, *a: list(_aes_dec(data, key, a, b64=True)),
            "aesEncodeToString": lambda data, key, *a: _aes_enc_str(data, key, a),
            "aesEncodeToBase64String": lambda data, key, *a: _to_b64(_aes_enc(data, key, a)),
            "desDecodeToString": lambda data, key, *a: _des_dec_str(data, key, a, "DES", b64=False),
            "desBase64DecodeToString": lambda data, key, *a: _des_dec_str(data, key, a, "DES", b64=True),
            "desEncodeToString": lambda data, key, *a: _des_enc_str(data, key, a, "DES"),
            "desEncodeToBase64String": lambda data, key, *a: _to_b64(_des_enc(data, key, a, "DES")),
            "tripleDESDecodeStr": lambda data, key, *a: _des_dec_str(data, key, a, "3DES", b64=False),
            "tripleDESEncodeBase64Str": lambda data, key, *a: _to_b64(_des_enc(data, key, a, "3DES")),
            "tripleDESDecodeArgsBase64Str": lambda data, key, *a: _des_dec_str(data, key, a, "3DES", b64=True),
            "tripleDESEncodeArgsBase64Str": lambda data, key, *a: _to_b64(_des_enc(data, key, a, "3DES")),
            "encodeURI": lambda s, *a: quote(str(s), safe="-_.!~*'();/?:@&=+$,#"),
            "utf8ToGbk": lambda s, *a: str(s).encode("gbk", errors="replace").decode("gbk"),
            "htmlFormat": _html_format,
            "timeFormat": lambda *a: time.strftime("%Y-%m-%d %H:%M:%S"),
            "timeFormatUTC": lambda t, f, sh, *a: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "randomUUID": lambda: str(uuid.uuid4()),
            "androidId": lambda: "",
            "cacheFile": self._cache_file_get,
            "get": self._ajax,
            "post": self._post,
            "log": lambda *a: None,
            "toast": lambda *a: None,
            "getCookie": self._cookie_get,
            "getZipStringContent": self._zip_string,
            "getZipByteArrayContent": self._zip_bytes,
            "importScript": self._import_script,
            "queryTTF": lambda s, *a: str(s),
            "queryBase64TTF": lambda s, *a: str(s),
            "replaceFont": lambda s, *a: str(s),
            "webView": lambda *a: None,
            "getFile": lambda *a: None,
            "readFile": lambda *a: None,
            "readTxtFile": lambda *a: None,
            "deleteFile": lambda *a: None,
            "downloadFile": lambda *a: None,
            "unzipFile": lambda *a: None,
            "getTxtInFolder": lambda *a: None,
        }

    def _connect(self, url_str: str, headers: dict | None = None) -> dict | None:
        resp = self._fetch_sync(url_str, headers)
        if resp is None:
            return None
        return {"url": resp.url, "body": resp.body, "headers": resp.headers, "code": resp.code}

    def _get(self, url_str: str, headers: dict | None = None, *a) -> dict | None:
        return self._connect(url_str, headers)

    def _post(self, url_str: str, body: str, headers: dict | None = None) -> dict | None:
        if isinstance(headers, str):
            try:
                headers = json.loads(headers)
            except json.JSONDecodeError:
                headers = None
        merged = dict(headers or {})
        url_part, _, option = url_str.partition(",{")
        if option:
            merged.setdefault("Content-Type", "application/json")
            return self._connect(url_str, merged)
        merged.setdefault("Content-Type", "application/x-www-form-urlencoded")
        return self._connect(url_str, merged)

    def _head(self, url_str: str, headers: dict | None = None) -> dict | None:
        return self._connect(url_str, headers)

    def _cookie_get(self, tag: str, key: str | None = None) -> str:
        host = self._host()
        store = getattr(host, "cookie_store", None)
        if store is None:
            return ""
        return store.get(str(tag), key) if key else store.get(str(tag), None) or ""

    def _cache_get(self, key: str) -> str | None:
        return self._cache.get(str(key))

    def _zip_string(self, url: str, path: str, charset: str = "utf-8") -> str | None:
        data = self._zip_bytes(url, path)
        if data is None:
            return None
        return bytes(data).decode(charset, errors="replace")

    def _zip_bytes(self, url: str, path: str) -> list[int] | None:
        import httpx

        if url.startswith("hex://"):
            raw = _unhex(url[6:])
        else:
            raw = httpx.get(url, timeout=30, follow_redirects=True).content
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            return list(zf.read(path))

    def _import_script(self, url: str) -> str | None:
        if url.startswith("http"):
            return self._ajax(url)
        return None

    def _cache_file_get(self, url: str, save_time: int = 0) -> str | None:
        key = hashlib.md5(url.encode()).hexdigest()
        if url in self._cache_file:
            return self._cache_file[url]
        body = self._ajax(url)
        if body is not None:
            self._cache_file[url] = body
        return body

    # ---- cookie.* / cache.* ----

    def _cookie_table(self) -> dict[str, Callable]:
        host = self._host()
        store = getattr(host, "cookie_store", None)

        def _domain() -> str:
            base = getattr(host, "base_url", "") or ""
            from reader.utils.net_utils import get_sub_domain

            return get_sub_domain(base)

        def set_cookie(key: str, value: str, *a):
            if store:
                store.set(str(key), _domain(), str(value))
            return ""

        def get_cookie(key: str, *a):
            if store:
                return store.get(str(key), _domain())
            return ""

        def remove_cookie(key: str, *a):
            if store:
                store.set(str(key), _domain(), "")
            return ""

        def cookie_to_map(cookie: str, *a):
            out = {}
            for item in str(cookie).split(";"):
                if "=" in item:
                    k, v = item.split("=", 1)
                    out[k.strip()] = v.strip()
            return out

        def map_to_cookie(m, *a):
            if isinstance(m, dict):
                return "; ".join(f"{k}={v}" for k, v in m.items())
            return ""

        return {
            "getCookie": get_cookie,
            "setCookie": set_cookie,
            "removeCookie": remove_cookie,
            "cookieToMap": cookie_to_map,
            "mapToCookie": map_to_cookie,
        }

    def _cache_table(self) -> dict[str, Callable]:
        def put(key: str, value: str, *a):
            self._cache[str(key)] = str(value)
            return True

        def get(key: str, *a):
            return self._cache.get(str(key))

        def put_int(key: str, v: int, *a):
            self._cache["i:" + str(key)] = str(int(v))
            return True

        def get_int(key: str, *a):
            try:
                return int(self._cache.get("i:" + str(key), "0"))
            except ValueError:
                return 0

        def put_long(key: str, v: int, *a):
            self._cache["i:" + str(key)] = str(int(v))
            return True

        def get_long(key: str, *a):
            return get_int(key)

        def delete(key: str, *a):
            self._cache.pop(str(key), None)
            self._cache.pop("i:" + str(key), None)
            return True

        def put_file(key: str, value: str, *a):
            self._cache_file[str(key)] = str(value)
            return True

        def get_file(key: str, *a):
            return self._cache_file.get(str(key))

        return {
            "put": put, "get": get, "putInt": put_int, "getInt": get_int,
            "putLong": put_long, "getLong": get_long, "delete": delete,
            "putFile": put_file, "getFile": get_file,
        }


# ---- 辅助 ----


def _as_bytes(data) -> bytes:
    if isinstance(data, str):
        try:
            return _b64decode(data)
        except Exception:
            return _unhex(data)
    if isinstance(data, list):
        return bytes(int(b) & 0xFF for b in data)
    return str(data).encode("utf-8")


def _try_decode(b: bytes) -> str:
    return b.decode("utf-8", errors="replace")


def _mode_from_trans(transformation: str):
    """"AES/CBC/PKCS5Padding" → (cipher_module, mode, needs_iv, padding)。"""
    parts = transformation.upper().split("/")
    algo = parts[0]
    mode_name = parts[1] if len(parts) > 1 else "ECB"
    padding = len(parts) <= 2 or "PADDING" in parts[2]
    module = {"AES": AES, "DES": DES, "DESede": DES3, "3DES": DES3}[algo]
    mode = {"CBC": AES.MODE_CBC, "ECB": AES.MODE_ECB, "CTR": AES.MODE_CTR,
            "CFB": AES.MODE_CFB, "OFB": AES.MODE_OFB}[mode_name]
    needs_iv = mode_name != "ECB"
    return module, mode, needs_iv, padding


def _adjust_key(key: bytes, algo: str) -> bytes:
    if algo in ("DES",):
        if len(key) < 8:
            key = key.ljust(8, b"\x00")
        return key[:8]
    if algo in ("DESede", "3DES"):
        if len(key) == 16:
            key += key[:8]
        return key[:24]
    if len(key) not in (16, 24, 32):
        key = key.ljust(16, b"\x00")[:16]
    return key


def _aes_dec(data, key, args, b64: bool = False):
    trans = str(args[0]) if len(args) > 0 and args[0] else "AES/CBC/PKCS5Padding"
    iv = str(args[1]) if len(args) > 1 and args[1] else None
    module, mode, needs_iv, padding = _mode_from_trans(trans)
    raw = _b64decode(data) if b64 else _as_bytes(data)
    key_b = _adjust_key(_as_bytes(key), "AES")
    iv_b = _as_bytes(iv)[:16] if iv else None
    if needs_iv and not iv_b:
        iv_b = key_b[:16]
    cipher = module.new(key_b, mode, iv_b) if needs_iv else module.new(key_b)
    out = cipher.decrypt(raw)
    if padding:
        try:
            out = unpad(out, 16)
        except ValueError:
            pass
    return out


def _aes_enc(data, key, args):
    trans = str(args[0]) if len(args) > 0 and args[0] else "AES/CBC/PKCS5Padding"
    iv = str(args[1]) if len(args) > 1 and args[1] else None
    module, mode, needs_iv, padding = _mode_from_trans(trans)
    key_b = _adjust_key(_as_bytes(key), "AES")
    iv_b = _as_bytes(iv)[:16] if iv else key_b[:16]
    raw = str(data).encode("utf-8")
    if padding:
        raw = pad(raw, 16)
    cipher = module.new(key_b, mode, iv_b) if needs_iv else module.new(key_b)
    return cipher.encrypt(raw)


def _aes_dec_str(data, key, args, b64: bool = False) -> str:
    return _try_decode(_aes_dec(data, key, args, b64))


def _aes_enc_str(data, key, args) -> str:
    return _try_decode(_aes_enc(data, key, args))


def _des_dec(data, key, args, algo: str, b64: bool = False):
    trans = str(args[0]) if len(args) > 0 and args[0] else (
        "DES/CBC/PKCS5Padding" if algo == "DES" else "DESede/CBC/PKCS5Padding"
    )
    iv = str(args[1]) if len(args) > 1 and args[1] else None
    module, mode, needs_iv, padding = _mode_from_trans(trans)
    raw = _b64decode(data) if b64 else _as_bytes(data)
    key_b = _adjust_key(_as_bytes(key), algo)
    iv_len = 8 if algo in ("DES", "DESede", "3DES") else 16
    iv_b = (_as_bytes(iv)[:iv_len] if iv else key_b[:iv_len]) if needs_iv else None
    if needs_iv and module is DES3 and len(iv_b) not in (8, 16):
        iv_b = iv_b[:8]
    cipher = module.new(key_b, mode, iv_b) if needs_iv else module.new(key_b)
    out = cipher.decrypt(raw)
    if padding:
        bs = 8 if algo in ("DES", "DESede", "3DES") else 16
        try:
            out = unpad(out, bs)
        except ValueError:
            pass
    return out


def _des_enc(data, key, args, algo: str):
    trans = str(args[0]) if len(args) > 0 and args[0] else (
        "DES/CBC/PKCS5Padding" if algo == "DES" else "DESede/CBC/PKCS5Padding"
    )
    iv = str(args[1]) if len(args) > 1 and args[1] else None
    module, mode, needs_iv, padding = _mode_from_trans(trans)
    key_b = _adjust_key(_as_bytes(key), algo)
    iv_len = 8
    iv_b = (_as_bytes(iv)[:iv_len] if iv else key_b[:iv_len]) if needs_iv else None
    raw = str(data).encode("utf-8")
    bs = 8
    if padding:
        raw = pad(raw, bs)
    cipher = module.new(key_b, mode, iv_b) if needs_iv else module.new(key_b)
    return cipher.encrypt(raw)


def _des_dec_str(data, key, args, algo: str, b64: bool) -> str:
    return _try_decode(_des_dec(data, key, args, algo, b64))


def _des_enc_str(data, key, args, algo: str) -> str:
    return _try_decode(_des_enc(data, key, args, algo))


def _html_format(s: str) -> str:
    """HtmlFormatter.formatKeepImg 简化版：块级标签转行、去其他标签、保留 img。"""
    import re

    s = re.sub(r"</?(?:div|p|br|hr|h\d|article|dd|dl)[^>]*>", "\n", s)
    s = re.sub(r"<!--[^>]*-->", "", s)
    s = re.sub(r"</?(?!img)[a-zA-Z]+(?=[ >])[^<>]*>", "", s)
    s = re.sub(r"\s*\n+\s*", "\n　　", s)
    s = re.sub(r"^[\n\s]+", "　　", s)
    s = re.sub(r"[\n\s]+$", "", s)
    return s
