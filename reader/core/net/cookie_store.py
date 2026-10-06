"""按书源隔离的 Cookie 存储（对照 legacy CookieStore，简化为单用户 JSON 持久化）。"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.parse import urlparse

import httpx


def _domain_of(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return ""
    if host.count(".") <= 1:
        return host
    return host.split(".", 1)[1]


class CookieStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "cookies.json"
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, str]] = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=1), "utf-8")

    def get(self, source_key: str, domain: str) -> str:
        with self._lock:
            return self._data.get(source_key, {}).get(domain, "")

    def set(self, source_key: str, domain: str, cookie: str) -> None:
        with self._lock:
            self._data.setdefault(source_key, {})[domain] = cookie
            self._save()

    def load_for_request(self, source_key: str, url: str) -> dict[str, str]:
        """返回 {name: value}，供 httpx 客户端带上历史 cookie。"""
        domain = _domain_of(url)
        raw = self.get(source_key, domain)
        jar: dict[str, str] = {}
        for item in raw.split(";"):
            if "=" in item:
                k, v = item.split("=", 1)
                jar[k.strip()] = v.strip()
        return jar

    def save_from_response(self, source_key: str, response: httpx.Response) -> None:
        set_cookies = response.headers.get_list("set-cookie")
        if not set_cookies:
            return
        domain = _domain_of(str(response.url))
        merged: dict[str, str] = {}
        existing = self.get(source_key, domain)
        for item in existing.split(";"):
            if "=" in item:
                k, v = item.split("=", 1)
                merged[k.strip()] = v.strip()
        for sc in set_cookies:
            pair = sc.split(";", 1)[0]
            if "=" in pair:
                k, v = pair.split("=", 1)
                merged[k.strip()] = v.strip()
        if merged:
            self.set(source_key, domain, "; ".join(f"{k}={v}" for k, v in merged.items()))
