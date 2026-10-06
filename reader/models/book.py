"""书籍实体（字段名与 legacy Book/SearchBook/BookChapter 对齐，JSON 直出兼容插件）。"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict


class LooseModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Book(LooseModel):
    bookUrl: str = ""
    tocUrl: str = ""
    origin: str = ""
    originName: str = ""
    originOrder: int = 0
    name: str = ""
    author: str = ""
    kind: str | None = None
    coverUrl: str | None = None
    intro: str | None = None
    wordCount: str | None = None
    latestChapterTitle: str | None = None
    type: int = 0
    group: int = 0
    latestChapterTime: int = 0
    lastCheckTime: int = 0
    lastCheckCount: int = 0
    totalChapterNum: int = 0
    durChapterTitle: str | None = None
    durChapterIndex: int = 0
    durChapterPos: int = 0
    durChapterTime: int = 0
    canUpdate: bool = True
    order: int = 0
    useReplaceRule: bool = False
    variable: str | None = None
    charset: str | None = None
    isInShelf: bool = True

    def get_folder_name(self) -> str:
        safe = re.sub(r"[\\/:*?\"<>|.]", "", f"{self.name}_{self.author}")
        return safe or "未命名"

    def variable_map(self) -> dict[str, str]:
        if not self.variable:
            return {}
        try:
            obj = json.loads(self.variable)
            return obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            return {}

    def put_variable(self, key: str, value: str) -> None:
        obj = self.variable_map()
        obj[key] = value
        self.variable = json.dumps(obj, ensure_ascii=False)

    def get_variable(self, key: str) -> str | None:
        return self.variable_map().get(key)


class SearchBook(Book):
    """搜索结果投影，与 Book 同构（legacy 中继承 Book）。"""


def to_search_book(book: Book) -> SearchBook:
    data = book.model_dump()
    return SearchBook.model_validate(data)


class BookChapter(LooseModel):
    url: str = ""
    title: str = ""
    index: int = 0
    baseUrl: str = ""
    bookUrl: str = ""
    isVolume: bool = False
    isVip: bool = False
    tag: str | None = None
    resourceUrl: str | None = None
    start: int | None = None
    end: int | None = None
    variable: str | None = None

    def get_absolute_url(self) -> str:
        """保留 URL 选项后缀的绝对地址（对照 BookChapter.getAbsoluteURL）。"""
        from reader.utils.net_utils import get_absolute_url

        option_pos = self.url.find(",{")
        base = self.baseUrl or self.bookUrl
        if option_pos > 0:
            return get_absolute_url(base, self.url)
        return get_absolute_url(base, self.url)

    def put_variable(self, key: str, value: str) -> None:
        obj: dict[str, str] = {}
        if self.variable:
            try:
                parsed = json.loads(self.variable)
                if isinstance(parsed, dict):
                    obj = {str(k): str(v) for k, v in parsed.items()}
            except json.JSONDecodeError:
                obj = {}
        obj[key] = value
        self.variable = json.dumps(obj, ensure_ascii=False)

    def get_variable(self, key: str) -> str | None:
        if not self.variable:
            return None
        try:
            parsed = json.loads(self.variable)
            if isinstance(parsed, dict):
                return parsed.get(key)
        except json.JSONDecodeError:
            pass
        return None


class BookGroup(LooseModel):
    groupId: int = 0
    groupName: str = ""
    cover: str | None = None
    order: int = 0
    show: bool = True


def format_book_name(name: str) -> str:
    name = re.sub(r"\s+作\s*者.*|\s+\S+\s+著", "", name)
    return name.strip()


def format_book_author(author: str) -> str:
    author = re.sub(r"^\s*作\s*者[:：\s]+|\s+著", "", author)
    return author.strip()


def word_count_format(wc: str | None) -> str:
    if not wc:
        return ""
    if wc.isdigit():
        words = int(wc)
        if words <= 0:
            return ""
        if words > 10000:
            return f"{words / 10000:.1f}万字".replace(".0万", "万")
        return f"{words}字"
    return wc
