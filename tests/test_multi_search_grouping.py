"""MultiSearch 聚合分组模式测试（dedup 开关 + 同书多源合并语义）。"""

import asyncio

import pytest

from reader.models.book_source import BookSource
from reader.models.book import SearchBook
from reader.services.search_service import MultiSearch, SourceSearcher


class FakeSearcher(SourceSearcher):
    """不真发请求：按预设的 (源名, 书列表) 返回。"""

    def __init__(self, per_source: dict[str, list[tuple[str, str]]]) -> None:
        self.per_source = per_source

    def search_one(self, source: BookSource, key: str, page) -> list:
        names = self.per_source.get(source.bookSourceUrl, [])
        return [
            SearchBook(name=n, author=a, bookUrl=f"{source.bookSourceUrl}/b{i}", origin=source.bookSourceUrl)
            for i, (n, a) in enumerate(names)
        ]


def _sources(urls: list[str]) -> list[BookSource]:
    return [
        BookSource(bookSourceUrl=u, bookSourceName=u, searchUrl=f"{u}/s")
        for u in urls
    ]


def test_dedup_merges_same_book_across_sources():
    """默认 dedup=True：同 (name,author) 跨源只留第一条（legacy 语义）。"""
    sources = _sources(["s1", "s2", "s3"])
    searcher = FakeSearcher({
        "s1": [("书A", "作者X")],
        "s2": [("书A", "作者X"), ("书B", "作者Y")],
        "s3": [("书A", "作者X")],
    })
    ms = MultiSearch(sources, searcher, concurrent_count=3)
    result = asyncio.run(ms.run("书", max_rounds=1))
    names = sorted((b.name, b.origin) for b in result.list)
    # 书A 只保留一个来源（s1 的），书B 一条
    assert names == [("书A", "s1"), ("书B", "s2")]


def test_no_dedup_keeps_every_source_entry():
    """dedup=False：同书每源各留一条（聚合分组场景）。"""
    sources = _sources(["s1", "s2", "s3"])
    searcher = FakeSearcher({
        "s1": [("书A", "作者X")],
        "s2": [("书A", "作者X")],
        "s3": [("书A", "作者X"), ("书C", "作者Z")],
    })
    ms = MultiSearch(sources, searcher, concurrent_count=3, dedup=False)
    result = asyncio.run(ms.run("书", max_rounds=1))
    book_a = [b for b in result.list if b.name == "书A"]
    assert len(book_a) == 3
    assert {b.origin for b in book_a} == {"s1", "s2", "s3"}


def test_grouped_batches_cover_all_sources():
    """聚合分组：on_batch 每帧内同书归组，多源同书组 sourceCount 累加。"""
    sources = _sources(["s1", "s2", "s3", "s4"])
    searcher = FakeSearcher({
        "s1": [("书A", "作者X")],
        "s2": [("书A", "作者X")],
        "s3": [("书A", "作者X")],
        "s4": [("书B", "作者Y")],
    })
    ms = MultiSearch(sources, searcher, concurrent_count=2, dedup=False)
    batches: list[list] = []

    async def run():
        return await ms.run("书", on_batch=lambda batch, idx: batches.append(batch), max_rounds=2)

    asyncio.run(run())
    grouped = {}
    for batch in batches:
        for b in batch:
            grouped.setdefault((b.name, b.author), []).append(b)
    # 书A 来自 3 个源都保留（dedup=False）
    assert len(grouped[("书A", "作者X")]) == 3
    assert len(grouped[("书B", "作者Y")]) == 1
