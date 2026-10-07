"""应用级服务组装与核心阅读服务（对照 legacy BookController 的单用户子集）。"""

from __future__ import annotations

import time

from reader.config import settings
from reader.core.js.bridge import JsBridge
from reader.core.js.engine import QuickJsEngine
from reader.core.net.cookie_store import CookieStore
from reader.core.net.http_client import HttpClient
from reader.models.book import Book, BookChapter
from reader.models.book_source import BookSource
from reader.services.search_service import MultiSearch, SourceSearcher
from reader.services.web_book import WebBook
from reader.store.chapter_cache import ChapterCache
from reader.store.db import Database


class ReaderService:
    """单例服务：数据库、网络、JS 引擎与各管线的粘合层。"""

    def __init__(self) -> None:
        self.db = Database(settings.data_dir)
        self.cookie_store = CookieStore(settings.data_dir)
        self.http = HttpClient(self.cookie_store)
        self.bridge = JsBridge(lambda: None)
        self.engine = QuickJsEngine(self.bridge)
        self.chapters_cache = ChapterCache(settings.data_dir)

    # ---- 书源 ----

    def save_sources(self, sources: list[BookSource]) -> None:
        self.db.save_sources(sources)

    def get_source(self, key: str) -> BookSource | None:
        return self.db.get_source(key)

    def list_sources(self) -> list[BookSource]:
        return self.db.list_sources()

    def delete_sources(self, keys: list[str]) -> None:
        self.db.delete_sources(keys)

    # ---- 搜索 ----

    def search_book(self, key: str, source_url: str, page: int = 1) -> list:
        source = self.get_source(source_url)
        if source is None:
            return []
        return WebBook(source, self.http, self.engine).search_book(key, page)

    async def search_multi(
        self,
        key: str,
        concurrent_count: int = 36,
        search_size: int = 100,
        last_index: int = 0,
        page: int = 1,
        on_batch=None,
        max_rounds: int | None = 8,
    ):
        sources = [s for s in self.list_sources() if s.enabled]
        searcher = SourceSearcher(self.http, self.engine)
        ms = MultiSearch(sources, searcher, concurrent_count, search_size)
        return await ms.run(key, last_index, page, on_batch, max_rounds=max_rounds)

    async def search_accurate_all(self, name: str, author: str, concurrent_count: int = 48):
        """换源候选：全源精搜，**不做跨源去重**——同名同作者的书每个源各留一条
        （MultiSearch 的 (name,author) 去重会吞掉其他源的条目，恰好是换源要的对象）。"""
        import asyncio as _asyncio
        from concurrent.futures import ThreadPoolExecutor

        sources = [s for s in self.list_sources() if s.enabled and s.searchUrl]
        loop = _asyncio.get_running_loop()
        semaphore = _asyncio.Semaphore(concurrent_count)
        pool = ThreadPoolExecutor(max_workers=concurrent_count, thread_name_prefix="accsearch")

        async def search_one(src) -> Book | None:
            async with semaphore:
                try:
                    books = await loop.run_in_executor(
                        pool, lambda: WebBook(src, self.http, self.engine).search_book(name, 1)
                    )
                except Exception:
                    return None
                for b in books:
                    if b.name == name and (not author or b.author == author):
                        return b
                return None

        try:
            results = await _asyncio.gather(*(search_one(s) for s in sources))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return [b for b in results if b is not None]

    # ---- 详情 / 目录 / 正文 ----

    def get_book_info(self, source_url: str, url: str) -> Book:
        source = self.get_source(source_url)
        if source is None:
            raise ValueError(f"书源不存在: {source_url}")
        book = Book(bookUrl=url, origin=source.bookSourceUrl, originName=source.bookSourceName)
        return WebBook(source, self.http, self.engine).get_book_info(book)

    def get_chapter_list(
        self,
        url: str,
        refresh: bool = False,
        book_source: str | None = None,
        book_source_url: str | None = None,
    ) -> list[BookChapter]:
        """书架书走缓存 + refresh；非架书（带 bookSourceUrl）实时抓取。"""
        shelf_book = self.db.get_book(url)
        source_key = book_source_url or (shelf_book.origin if shelf_book else None)
        if not source_key:
            raise ValueError(f"未找到书籍对应书源: {url}")
        source = self.get_source(source_key)
        if source is None:
            raise ValueError(f"书源不存在: {source_key}")
        wb = WebBook(source, self.http, self.engine)

        if shelf_book is None:
            book = Book(bookUrl=url, origin=source.bookSourceUrl, originName=source.bookSourceName)
            wb.get_book_info(book, can_re_name=False)
            return wb.get_chapter_list(book)

        if not refresh:
            cached = self.chapters_cache.load_toc(shelf_book)
            if cached is not None:
                return cached
        wb.get_book_info(shelf_book, can_re_name=False)
        chapters = wb.get_chapter_list(shelf_book)
        self.chapters_cache.save_toc(shelf_book, chapters)
        self.db.save_book(shelf_book)
        return chapters

    def get_book_content(
        self,
        url: str,
        index: int,
        refresh: bool = False,
        book_source_url: str | None = None,
    ) -> str:
        shelf_book = self.db.get_book(url)
        source_key = book_source_url or (shelf_book.origin if shelf_book else None)
        if not source_key:
            raise ValueError(f"未找到书籍对应书源: {url}")
        source = self.get_source(source_key)
        if source is None:
            raise ValueError(f"书源不存在: {source_key}")
        wb = WebBook(source, self.http, self.engine)

        book = shelf_book
        if book is None:
            book = Book(bookUrl=url, origin=source.bookSourceUrl, originName=source.bookSourceName)
            wb.get_book_info(book, can_re_name=False)

        if not refresh and settings.cache_chapter_content:
            cached = self.chapters_cache.load_content(book, index)
            if cached is not None:
                return cached

        toc = self.get_chapter_list(url, refresh=False, book_source_url=source_key)
        if index < 0 or index >= len(toc):
            raise ValueError(f"章节序号越界: {index}/{len(toc)}")
        chapter = toc[index]
        content = wb.get_book_content(book, chapter)
        if settings.cache_chapter_content:
            self.chapters_cache.save_content(book, index, content)
        return content

    # ---- 书架 ----

    def save_book(self, book: Book) -> None:
        existing = self.db.get_book(book.bookUrl)
        if existing:
            # 保留本地进度，合并字段
            book.durChapterIndex = existing.durChapterIndex
            book.durChapterPos = existing.durChapterPos
            book.durChapterTime = existing.durChapterTime
            book.durChapterTitle = existing.durChapterTitle
        book.isInShelf = True
        self.db.save_book(book)

    def delete_book(self, book_url: str) -> bool:
        book = self.db.get_book(book_url)
        existed = self.db.delete_book(book_url)
        # 同时清理章节目录/正文磁盘缓存（书已删，缓存无主）
        if book is not None:
            try:
                self.chapters_cache.delete_book(book)
            except OSError:
                pass  # 缓存清理失败不阻碍删书
        return existed

    def get_shelf_book(self, url: str) -> Book | None:
        return self.db.get_book(url)

    def get_bookshelf(self, refresh: bool = False) -> list[Book]:
        books = self.db.list_books()
        if not refresh:
            return books
        # refresh=1：逐本补齐封面/简介（详情页信息），并发抓取
        from concurrent.futures import ThreadPoolExecutor

        def _refresh_one(book: Book) -> Book:
            try:
                source = self.get_source(book.origin)
                if source is None:
                    return book
                WebBook(source, self.http, self.engine).get_book_info(
                    book, can_re_name=False
                )
            except Exception:
                pass  # 单本失败不影响书架展示
            return book

        with ThreadPoolExecutor(max_workers=6) as pool:
            books = list(pool.map(_refresh_one, books))
        for b in books:
            self.db.save_book(b)
        return books

    def save_progress(
        self,
        url: str,
        index: int,
        title: str | None = None,
        pos: int = 0,
        chapter_time: int | None = None,
    ) -> None:
        book = self.db.get_book(url)
        if book is None:
            return
        book.durChapterIndex = index
        book.durChapterPos = pos
        book.durChapterTitle = title or book.durChapterTitle
        book.durChapterTime = chapter_time if chapter_time is not None else int(time.time() * 1000)
        self.db.save_book(book)


# 模块级单例（FastAPI 依赖注入用）
_service: ReaderService | None = None


def get_service() -> ReaderService:
    global _service
    if _service is None:
        _service = ReaderService()
    return _service
