"""URL 工具（对照 legacy NetworkUtils 中规则引擎用到的部分）。"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse


def get_absolute_url(base_url: str | None, relative_path: str) -> str:
    """相对 URL → 绝对 URL（对照 NetworkUtils.getAbsoluteURL）。

    legacy 会先对 baseURL 做 substringBefore(",")——搜索 URL 选项语法
    "http://x,{...}" 里逗号后是选项 JSON，不是 URL 的一部分。
    """
    if not base_url:
        return relative_path
    if not relative_path:
        return base_url
    base = base_url.split(",", 1)[0]
    try:
        return urljoin(base, relative_path)
    except Exception:
        return relative_path


def get_base_url(url: str | None) -> str | None:
    """scheme://host（对照 NetworkUtils.getBaseUrl）。"""
    if not url or not url.startswith("http"):
        return None
    index = url.find("/", 9)
    return url if index == -1 else url[:index]


def get_sub_domain(url: str | None) -> str:
    """取用于 cookie 的子域（对照 NetworkUtils.getSubDomain）。"""
    base = get_base_url(url)
    if base is None:
        return ""
    host = urlparse(base).hostname or ""
    if host.count(".") <= 1:
        return host
    return host.split(".", 1)[1]


_UNRESERVED = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~!*'()"
)


def has_url_encoded(s: str) -> bool:
    """判断字符串是否已 URL 编码（对照 NetworkUtils.hasUrlEncoded）。"""
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c in _UNRESERVED:
            i += 1
            continue
        if c == "%" and i + 2 < n + 1 and i + 2 < n + 1:
            # %XX 视为已按规范编码
            hex_part = s[i + 1 : i + 3]
            if len(hex_part) == 2:
                try:
                    int(hex_part, 16)
                    i += 3
                    continue
                except ValueError:
                    pass
        return False
    return True


def js_escape(s: str, encoding: str = "utf-8") -> str:
    """JS escape() 的等价实现（charset=escape 时使用，对照 EncoderUtils.escape）。"""
    safe = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789*@-_+./")
    out: list[str] = []
    for ch in s:
        if ch in safe:
            out.append(ch)
        elif ord(ch) < 256:
            out.append(f"%{ord(ch):02X}")
        else:
            for b in ch.encode("unicode_escape"):
                pass
            # JS escape 对 BMP 字符用 %uXXXX
            for item in ch:
                out.append(f"%u{ord(item):04X}")
    return "".join(out)


def url_encode(value: str, charset: str = "utf-8") -> str:
    """URLEncoder.encode 等价：空格转 +，按指定 charset 编码。"""
    from urllib.parse import quote

    return quote(value.encode(charset, errors="replace"), safe="-_.")
