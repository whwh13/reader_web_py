"""多源并发搜索（对照 legacy BookController.searchBookMulti 的游标分批语义）。

- 源列表按 customOrder 排序，跳过禁用源；
- 滑动窗口并发（默认 36），按 (name, author) 去重聚合；
- 单轮达到 searchSize 或 8 轮即停，返回 lastIndex 游标供续搜。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable

from reader.core.net.http_client import HttpClient
from reader.core.rule.js_engine import JsEngine
from reader.models.book import SearchBook
from reader.models.book_source import BookSource
from reader.services.web_book import WebBook


@dataclass
class MultiSearchResult:
    last_index: int
    list: list[SearchBook]
    is_end: bool


class SourceSearcher:
    """在 worker 线程池上对每个书源执行搜索。"""

    def __init__(self, http: HttpClient, engine: JsEngine) -> None:
        self.http = http
        self.engine = engine

    def search_one(self, source: BookSource, key: str, page: int | None) -> list[SearchBook]:
        try:
            if not source.enabled:
                return []
            return WebBook(source, self.http, self.engine).search_book(key, page)
        except Exception:
            return []


class MultiSearch:
    def __init__(
        self,
        sources: list[BookSource],
        searcher: SourceSearcher,
        concurrent_count: int = 36,
        search_size: int = 100,
    ) -> None:
        # 排序：customOrder 降序（对照 legacy 源排序）
        self.sources = sorted(sources, key=lambda s: s.customOrder, reverse=True)
        self.searcher = searcher
        self.concurrent_count = max(1, concurrent_count)
        self.search_size = search_size

    async def run(
        self,
        key: str,
        last_index: int = 0,
        page: int = 1,
        on_batch: Callable[[list[SearchBook], int], None] | None = None,
    ) -> MultiSearchResult:
        """从 last_index 的源继续搜索，返回游标与聚合结果。"""
        loop = asyncio.get_running_loop()
        semaphore = asyncio.Semaphore(self.concurrent_count)
        aggregated: dict[tuple[str, str], SearchBook] = {}
        rounds_without_result = 0
        index = last_index
        total = len(self.sources)

        async def search_at(i: int) -> list[SearchBook]:
            async with semaphore:
                return await loop.run_in_executor(
                    None, self.searcher.search_one, self.sources[i], key, page
                )

        # 滑动窗口：一轮并发 concurrent_count 个源
        while index < total:
            window = range(index, min(index + self.concurrent_count, total))
            results = await asyncio.gather(*(search_at(i) for i in window))
            index += len(window)

            batch: list[SearchBook] = []
            for books in results:
                for sb in books:
                    dedup_key = (sb.name, sb.author)
                    if dedup_key in aggregated:
                        continue
                    aggregated[dedup_key] = sb
                    batch.append(sb)
                    if len(aggregated) >= self.search_size:
                        break
                if len(aggregated) >= self.search_size:
                    break

            if on_batch and batch:
                on_batch(batch, index)

            rounds_without_result = rounds_without_result + 1 if not batch else 0
            if len(aggregated) >= self.search_size or rounds_without_result >= 8:
                break

        return MultiSearchResult(
            last_index=index,
            list=list(aggregated.values())[: self.search_size],
            is_end=index >= total,
        )
