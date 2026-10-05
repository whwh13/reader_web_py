"""章节目录与正文磁盘缓存（对齐 legacy 数据布局概念，单用户简化）。"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from reader.config import settings
from reader.models.book import Book, BookChapter


def _md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _safe_name(s: str) -> str:
    return re.sub(r"[\\/:*?\"<>|.]", "", s).strip() or "未命名"


class ChapterCache:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.root = (data_dir or settings.data_dir) / "books"

    def book_dir(self, book: Book) -> Path:
        d = self.root / _safe_name(book.get_folder_name())
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ---- 目录 ----

    def toc_path(self, book: Book) -> Path:
        return self.book_dir(book) / f"{_md5(book.bookUrl)}.json"

    def load_toc(self, book: Book) -> list[BookChapter] | None:
        p = self.toc_path(book)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text("utf-8"))
            return [BookChapter.model_validate(item) for item in data]
        except (json.JSONDecodeError, OSError, ValueError):
            return None

    def save_toc(self, book: Book, chapters: list[BookChapter]) -> None:
        p = self.toc_path(book)
        p.write_text(
            json.dumps([c.model_dump() for c in chapters], ensure_ascii=False), "utf-8"
        )

    # ---- 正文 ----

    def content_path(self, book: Book, index: int) -> Path:
        d = self.book_dir(book) / _md5(book.bookUrl)
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{index}.txt"

    def load_content(self, book: Book, index: int) -> str | None:
        p = self.content_path(book, index)
        if not p.exists():
            return None
        try:
            return p.read_text("utf-8")
        except OSError:
            return None

    def save_content(self, book: Book, index: int, content: str) -> None:
        self.content_path(book, index).write_text(content, "utf-8")

    def delete_content(self, book: Book, index: int) -> None:
        p = self.content_path(book, index)
        if p.exists():
            p.unlink()
