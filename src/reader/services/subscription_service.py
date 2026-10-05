"""书源订阅：远程 URL → 拉取解析 → 合并入库（对照 legacy remoteBookSourceSub 语义）。"""

from __future__ import annotations

import time

import httpx

from reader.models.book_source import parse_book_sources
from reader.store.db import Database

_FETCH_TIMEOUT = 60.0


class SubscriptionService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list_subs(self) -> list[dict]:
        return self.db.list_subs()

    def add_sub(self, link: str, name: str = "") -> dict:
        result = self._refresh_one(link, name)
        if not result["ok"]:
            # 保存条目但记录错误，便于用户看到失败原因后重试
            self.db.save_sub(link, name or link, 0, 0, result["error"])
        return result

    def remove_sub(self, link: str) -> None:
        self.db.delete_sub(link)

    def refresh_all(self) -> list[dict]:
        return [self._refresh_one(sub["link"], sub["name"]) for sub in self.db.list_subs()]

    def refresh_one(self, link: str) -> dict:
        sub = next((s for s in self.db.list_subs() if s["link"] == link), None)
        return self._refresh_one(link, sub["name"] if sub else "")

    def _refresh_one(self, link: str, name: str) -> dict:
        started = time.time()
        try:
            sources = self._fetch_and_parse(link)
            self.db.save_sources(sources)
            count = len(sources)
            self.db.save_sub(link, name or link, int(time.time() * 1000), count, None)
            return {"link": link, "ok": True, "count": count, "elapsed": round(time.time() - started, 1)}
        except Exception as e:
            error = str(e) or e.__class__.__name__
            self.db.save_sub(link, name or link, 0, 0, error)
            return {"link": link, "ok": False, "count": 0, "error": error, "elapsed": round(time.time() - started, 1)}

    def _fetch_and_parse(self, link: str):
        with httpx.Client(follow_redirects=True, timeout=_FETCH_TIMEOUT) as client:
            resp = client.get(link)
            resp.raise_for_status()
        sources = parse_book_sources(resp.text)
        if not sources:
            raise ValueError("订阅内容未解析到书源")
        # 同名去重（同 URL 的源保留最后出现的，与 legacy upsert 语义一致）
        return sources
