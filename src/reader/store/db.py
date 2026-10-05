"""SQLite 存储（单用户简化：实体 JSON 行存 + 关键列索引）。

章节目录与正文缓存走 store.chapter_cache 的文件布局（对齐 legacy 概念）。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from reader.config import settings
from reader.models.book import Book, BookGroup
from reader.models.book_source import BookSource

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    key TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    custom_order INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS books (
    book_url TEXT PRIMARY KEY,
    origin TEXT NOT NULL,
    name TEXT NOT NULL,
    author TEXT NOT NULL,
    data TEXT NOT NULL,
    dur_chapter_index INTEGER NOT NULL DEFAULT 0,
    order_num INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS book_groups (
    group_id INTEGER PRIMARY KEY,
    data TEXT NOT NULL,
    order_num INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    def __init__(self, data_dir: Path | None = None) -> None:
        data_dir = data_dir or settings.data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(data_dir / "reader.db", check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def _exec(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def _query(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # ---- 书源 ----

    def save_sources(self, sources: list[BookSource]) -> None:
        for s in sources:
            self._exec(
                "INSERT INTO sources(key, data, custom_order, enabled) VALUES(?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET data=excluded.data, "
                "custom_order=excluded.custom_order, enabled=excluded.enabled",
                (s.bookSourceUrl, s.model_dump_json(), s.customOrder, int(s.enabled)),
            )

    def get_source(self, key: str) -> BookSource | None:
        rows = self._query("SELECT data FROM sources WHERE key=?", (key,))
        if not rows:
            return None
        return BookSource.model_validate(json.loads(rows[0][0]))

    def list_sources(self) -> list[BookSource]:
        rows = self._query("SELECT data FROM sources ORDER BY custom_order DESC")
        return [BookSource.model_validate(json.loads(r[0])) for r in rows]

    def delete_sources(self, keys: list[str]) -> None:
        for key in keys:
            self._exec("DELETE FROM sources WHERE key=?", (key,))

    # ---- 书架 ----

    def save_book(self, book: Book) -> None:
        self._exec(
            "INSERT INTO books(book_url, origin, name, author, data, dur_chapter_index, order_num) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(book_url) DO UPDATE SET "
            "origin=excluded.origin, name=excluded.name, author=excluded.author, "
            "data=excluded.data, dur_chapter_index=excluded.dur_chapter_index",
            (
                book.bookUrl,
                book.origin,
                book.name,
                book.author,
                book.model_dump_json(),
                book.durChapterIndex,
                book.order,
            ),
        )

    def get_book(self, book_url: str) -> Book | None:
        rows = self._query("SELECT data FROM books WHERE book_url=?", (book_url,))
        if not rows:
            return None
        return Book.model_validate(json.loads(rows[0][0]))

    def list_books(self) -> list[Book]:
        rows = self._query("SELECT data FROM books ORDER BY order_num, dur_chapter_index")
        return [Book.model_validate(json.loads(r[0])) for r in rows]

    def delete_book(self, book_url: str) -> bool:
        rows = self._query("SELECT 1 FROM books WHERE book_url=?", (book_url,))
        self._exec("DELETE FROM books WHERE book_url=?", (book_url,))
        return bool(rows)

    # ---- 分组 ----

    def save_group(self, group: BookGroup) -> None:
        self._exec(
            "INSERT INTO book_groups(group_id, data, order_num) VALUES(?,?,?) "
            "ON CONFLICT(group_id) DO UPDATE SET data=excluded.data, order_num=excluded.order_num",
            (group.groupId, group.model_dump_json(), group.order),
        )

    def list_groups(self) -> list[BookGroup]:
        rows = self._query("SELECT data FROM book_groups ORDER BY order_num")
        return [BookGroup.model_validate(json.loads(r[0])) for r in rows]

    def delete_group(self, group_id: int) -> None:
        self._exec("DELETE FROM book_groups WHERE group_id=?", (group_id,))
