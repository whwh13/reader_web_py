"""书源模型（字段与 legacy BookSource / 规则实体完全一致，兼容现有书源生态 JSON）。

宽松解析：未知字段保留（extra="allow"），脏类型尽量容忍——
对齐 legacy SourceAnalyzer 的容错行为。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _LooseModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class BookListRule(_LooseModel):
    bookList: str | None = None
    name: str | None = None
    author: str | None = None
    intro: str | None = None
    kind: str | None = None
    lastChapter: str | None = None
    updateTime: str | None = None
    bookUrl: str | None = None
    coverUrl: str | None = None
    wordCount: str | None = None


class SearchRule(BookListRule):
    checkKeyWord: str | None = None


# ExploreRule 与 SearchRule 同构（legacy 两者均实现 BookListRule）
ExploreRule = SearchRule


class BookInfoRule(_LooseModel):
    init: str | None = None
    name: str | None = None
    author: str | None = None
    intro: str | None = None
    kind: str | None = None
    lastChapter: str | None = None
    updateTime: str | None = None
    coverUrl: str | None = None
    tocUrl: str | None = None
    wordCount: str | None = None
    canReName: str | None = None


class TocRule(_LooseModel):
    preUpdateJs: str | None = None
    chapterList: str | None = None
    chapterName: str | None = None
    chapterUrl: str | None = None
    isVolume: str | None = None
    isVip: str | None = None
    updateTime: str | None = None
    nextTocUrl: str | None = None


class ContentRule(_LooseModel):
    content: str | None = None
    nextContentUrl: str | None = None
    webJs: str | None = None
    sourceRegex: str | None = None
    replaceRegex: str | None = None
    imageStyle: str | None = None


class BookSource(_LooseModel):
    bookSourceUrl: str = ""
    bookSourceName: str = ""
    bookSourceGroup: str | None = None
    bookSourceType: int = 0
    bookUrlPattern: str | None = None
    customOrder: int = 0
    enabled: bool = True
    enabledExplore: bool = True
    enabledCookieJar: bool = False
    concurrentRate: str | None = None
    header: str | None = None
    loginUrl: str | None = None
    loginUi: Any = None
    loginCheckJs: str | None = None
    bookSourceComment: str | None = None
    variableComment: str | None = None
    lastUpdateTime: int = 0
    respondTime: int = 180000
    weight: int = 0
    exploreUrl: str | None = None
    searchUrl: str | None = None
    ruleSearch: SearchRule | None = None
    ruleExplore: ExploreRule | None = None
    ruleBookInfo: BookInfoRule | None = None
    ruleToc: TocRule | None = None
    ruleContent: ContentRule | None = None
    variable: str | None = Field(default=None)

    def get_key(self) -> str:
        return self.bookSourceUrl

    def get_header_map(self, format_js: bool = False) -> dict[str, str] | None:
        """header 字段：JSON 字符串或对象（对照 BaseSource.getHeaderMap）。"""
        raw = self.header
        if not raw:
            return None
        try:
            obj = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict):
            return None
        return {str(k): str(v) for k, v in obj.items()}

    def get_variable(self) -> str:
        return self.variable or ""

    def put_variable(self, key: str, value: str) -> None:
        """书源级变量写回 variable JSON（对照 BaseSource.putVariable）。"""
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


def parse_book_sources(data: str | bytes | list | dict) -> list[BookSource]:
    """宽松解析书源 JSON（单个对象、数组、或包含数组字段的 包装对象均可）。"""
    if isinstance(data, (str, bytes)):
        text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 宽松容错：截取最外层 JSON（对齐 SourceAnalyzer 的容错场景）
            data = _loose_json(text)
    sources: list[BookSource] = []
    if isinstance(data, dict):
        if "bookSourceUrl" in data:
            sources.append(BookSource.model_validate(data))
        else:
            for value in data.values():
                if isinstance(value, list):
                    sources.extend(parse_book_sources(value))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                try:
                    sources.append(BookSource.model_validate(item))
                except Exception:
                    continue
    return sources


def _loose_json(text: str):
    """从文本中提取首个平衡的 JSON 值。"""
    for start_ch, end_ch in (("[", "]"), ("{", "}")):
        start = text.find(start_ch)
        if start == -1:
            continue
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == start_ch:
                depth += 1
            elif ch == end_ch:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        return None
    return None
