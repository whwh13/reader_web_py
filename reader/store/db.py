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
CREATE TABLE IF NOT EXISTS book_source_subs (
    link TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    last_sync_time INTEGER NOT NULL DEFAULT 0,
    source_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);
"""

# sources 表的校验结果列与订阅来源列（增量迁移）
_SOURCE_CHECK_COLUMNS = """
ALTER TABLE sources ADD COLUMN last_check_time INTEGER NOT NULL DEFAULT 0;
ALTER TABLE sources ADD COLUMN last_check_ok INTEGER;
ALTER TABLE sources ADD COLUMN last_check_error TEXT;
ALTER TABLE sources ADD COLUMN sub_link TEXT;
"""


class Database:
    def __init__(self, data_dir: Path | None = None) -> None:
        data_dir = data_dir or settings.data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(data_dir / "reader.db", check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        for stmt in _SOURCE_CHECK_COLUMNS.strip().splitlines():
            try:
                self._conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # 列已存在
        self._conn.commit()

    def _exec(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def _query(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # ---- 书源 ----

    def save_sources(self, sources: list[BookSource], sub_link: str | None = None) -> None:
        for s in sources:
            self._exec(
                "INSERT INTO sources(key, data, custom_order, enabled, sub_link) VALUES(?,?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET data=excluded.data, "
                "custom_order=excluded.custom_order, enabled=excluded.enabled, "
                "sub_link=COALESCE(excluded.sub_link, sources.sub_link)",
                (s.bookSourceUrl, s.model_dump_json(), s.customOrder, int(s.enabled), sub_link),
            )

    def set_sources_sub_link(self, keys: list[str], sub_link: str | None) -> None:
        """批量改写书源的订阅来源标记（sub_link=None 表示清除）。"""
        if not keys:
            return
        placeholders = ",".join("?" * len(keys))
        self._exec(
            f"UPDATE sources SET sub_link=? WHERE key IN ({placeholders})",
            (sub_link, *keys),
        )

    def list_source_keys_by_sub(self, link: str) -> list[str]:
        rows = self._query("SELECT key FROM sources WHERE sub_link=?", (link,))
        return [r[0] for r in rows]

    def get_source_sub_link(self, key: str) -> str | None:
        rows = self._query("SELECT sub_link FROM sources WHERE key=?", (key,))
        return rows[0][0] if rows and rows[0][0] else None

    def set_sources_enabled(self, keys: list[str], enabled: bool) -> int:
        """批量启停书源，返回实际更新的行数。"""
        if not keys:
            return 0
        placeholders = ",".join("?" * len(keys))
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE sources SET enabled=? WHERE key IN ({placeholders})",
                (int(enabled), *keys),
            )
            self._conn.commit()
            return cur.rowcount

    def get_source(self, key: str) -> BookSource | None:
        rows = self._query("SELECT data, enabled FROM sources WHERE key=?", (key,))
        if not rows:
            return None
        source = BookSource.model_validate(json.loads(rows[0][0]))
        source.enabled = bool(rows[0][1])  # enabled 列为准（批量启停只改列）
        return source

    def list_sources(self) -> list[BookSource]:
        rows = self._query("SELECT data, enabled FROM sources ORDER BY custom_order DESC")
        out = []
        for r in rows:
            source = BookSource.model_validate(json.loads(r[0]))
            source.enabled = bool(r[1])  # enabled 列为准（批量启停只改列）
            out.append(source)
        return out

    def delete_sources(self, keys: list[str]) -> None:
        for key in keys:
            self._exec("DELETE FROM sources WHERE key=?", (key,))

    def set_check_result(self, key: str, ok: bool, error: str | None) -> None:
        import time as _time

        self._exec(
            "UPDATE sources SET last_check_time=?, last_check_ok=?, last_check_error=? WHERE key=?",
            (int(_time.time() * 1000), 1 if ok else 0, error, key),
        )

    def get_check_result(self, key: str) -> tuple[int, int | None, str | None]:
        rows = self._query(
            "SELECT last_check_time, last_check_ok, last_check_error FROM sources WHERE key=?",
            (key,),
        )
        if not rows:
            return 0, None, None
        return rows[0][0], rows[0][1], rows[0][2]

    def list_invalid_sources(self) -> list[str]:
        rows = self._query(
            "SELECT key FROM sources WHERE last_check_ok=0 AND last_check_time>0 ORDER BY key"
        )
        return [r[0] for r in rows]

    # ---- 书源订阅 ----

    def save_sub(self, link: str, name: str, last_sync_time: int, source_count: int, last_error: str | None) -> None:
        self._exec(
            "INSERT INTO book_source_subs(link, name, last_sync_time, source_count, last_error) "
            "VALUES(?,?,?,?,?) ON CONFLICT(link) DO UPDATE SET name=excluded.name, "
            "last_sync_time=excluded.last_sync_time, source_count=excluded.source_count, "
            "last_error=excluded.last_error",
            (link, name, last_sync_time, source_count, last_error),
        )

    def list_subs(self) -> list[dict]:
        rows = self._query(
            "SELECT link, name, last_sync_time, source_count, last_error FROM book_source_subs "
            "ORDER BY last_sync_time DESC"
        )
        return [
            {"link": r[0], "name": r[1], "lastSyncTime": r[2], "sourceCount": r[3], "lastError": r[4]}
            for r in rows
        ]

    def delete_sub(self, link: str) -> None:
        self._exec("DELETE FROM book_source_subs WHERE link=?", (link,))

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
