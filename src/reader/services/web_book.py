"""四条解析管线（对照 legacy WebBook / BookList / BookInfo / BookChapterList / BookContent）。

全部同步实现：JS 桥与 HTTP 均为同步，端点层用 asyncio.to_thread 并发。
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from reader.core.net.http_client import HttpClient, StrResponse
from reader.core.rule.analyze_rule import AnalyzeRule
from reader.core.rule.analyze_url import AnalyzeUrl
from reader.core.rule.js_engine import JsEngine
from reader.models.book import (
    Book,
    BookChapter,
    SearchBook,
    format_book_author,
    format_book_name,
    to_search_book,
    word_count_format,
)
from reader.models.book_source import BookSource


class TocEmptyException(Exception):
    pass


class WebBook:
    def __init__(
        self,
        source: BookSource,
        http: HttpClient,
        engine: JsEngine,
    ) -> None:
        self.source = source
        self.http = http
        self.engine = engine

    # ---- 公共 ----

    def _analyze_url(
        self,
        m_url: str,
        key: str | None = None,
        page: int | None = None,
        base_url: str = "",
        rule_data=None,
        chapter=None,
    ) -> AnalyzeUrl:
        return AnalyzeUrl(
            m_url=m_url,
            key=key,
            page=page,
            base_url=base_url,
            source=self.source,
            rule_data=rule_data,
            chapter=chapter,
            header_map=self.source.get_header_map(True),
            js_engine=self.engine,
        )

    def _fetch(self, analyze_url: AnalyzeUrl) -> StrResponse:
        res = self.http.fetch_str_sync(analyze_url)
        return res

    def _new_rule(self, rule_data) -> AnalyzeRule:
        return AnalyzeRule(rule_data, source=self.source, js_engine=self.engine)

    # ---- 搜索 ----

    def search_book(self, key: str, page: int | None = 1) -> list[SearchBook]:
        variable_book = SearchBook()
        search_url = self.source.searchUrl
        if not search_url:
            return []
        analyze_url = self._analyze_url(
            search_url, key=key, page=page,
            base_url=self.source.bookSourceUrl, rule_data=variable_book,
        )
        res = self._fetch(analyze_url)
        return self.analyze_book_list(res.body, analyze_url, res.url, variable_book, is_search=True)

    # ---- 发现（backlog 路由预留）----

    def explore_book(self, url: str, page: int | None = 1) -> list[SearchBook]:
        variable_book = SearchBook()
        analyze_url = self._analyze_url(
            url, page=page, base_url=self.source.bookSourceUrl, rule_data=variable_book,
        )
        res = self._fetch(analyze_url)
        return self.analyze_book_list(res.body, analyze_url, res.url, variable_book, is_search=False)

    # ---- 书籍列表（对照 BookList.analyzeBookList）----

    def analyze_book_list(
        self,
        body: str | None,
        analyze_url: AnalyzeUrl,
        base_url: str,
        variable_book: SearchBook,
        is_search: bool = True,
    ) -> list[SearchBook]:
        if body is None:
            raise ValueError("error_get_web_content")
        book_list: list[SearchBook] = []
        analyze_rule = self._new_rule(variable_book)
        analyze_rule.set_content(body, base_url)
        analyze_rule.set_redirect_url(base_url)

        # bookUrlPattern 命中 → 本身就是详情页
        if self.source.bookUrlPattern:
            try:
                if re.fullmatch(self.source.bookUrlPattern, base_url):
                    item = self._get_info_item(body, analyze_rule, analyze_url, base_url, base_url)
                    if item:
                        book_list.append(item)
                    return book_list
            except re.error:
                pass

        rule = self.source.ruleSearch if is_search else (
            self.source.ruleExplore if (self.source.ruleExplore and self.source.ruleExplore.bookList)
            else self.source.ruleSearch
        )
        if rule is None:
            return book_list
        rule_list = rule.bookList or ""
        reverse = False
        if rule_list.startswith("-"):
            reverse = True
            rule_list = rule_list[1:]
        elif rule_list.startswith("+"):
            rule_list = rule_list[1:]

        collections = analyze_rule.get_elements(rule_list)
        if not collections and not self.source.bookUrlPattern:
            # 列表为空，按详情页解析
            item = self._get_info_item(body, analyze_rule, analyze_url, base_url, base_url)
            if item:
                book_list.append(item)
        else:
            r_name = analyze_rule.split_source_rule(rule.name)
            r_book_url = analyze_rule.split_source_rule(rule.bookUrl)
            r_author = analyze_rule.split_source_rule(rule.author)
            r_cover = analyze_rule.split_source_rule(rule.coverUrl)
            r_intro = analyze_rule.split_source_rule(rule.intro)
            r_kind = analyze_rule.split_source_rule(rule.kind)
            r_last = analyze_rule.split_source_rule(rule.lastChapter)
            r_word = analyze_rule.split_source_rule(rule.wordCount)
            for item in collections:
                search_book = self._get_search_item(
                    item, analyze_rule, base_url,
                    rule_name=r_name, rule_book_url=r_book_url, rule_author=r_author,
                    rule_cover=r_cover, rule_intro=r_intro, rule_kind=r_kind,
                    rule_last=r_last, rule_word=r_word,
                )
                if search_book:
                    book_list.append(search_book)
            if reverse:
                book_list.reverse()
        return book_list

    def _get_info_item(
        self,
        body: str,
        analyze_rule: AnalyzeRule,
        analyze_url: AnalyzeUrl,
        base_url: str,
        redirect_url: str,
    ) -> SearchBook | None:
        book = Book()
        book.bookUrl = analyze_url.rule_url
        book.origin = self.source.bookSourceUrl
        book.originName = self.source.bookSourceName
        book.originOrder = self.source.customOrder
        book.type = self.source.bookSourceType
        analyze_rule.rule_data = book
        self.analyze_book_info(book, body, analyze_rule, base_url, redirect_url, False)
        if book.name:
            return to_search_book(book)
        return None

    def _get_search_item(
        self,
        item,
        analyze_rule: AnalyzeRule,
        base_url: str,
        rule_name,
        rule_book_url,
        rule_author,
        rule_cover,
        rule_intro,
        rule_kind,
        rule_last,
        rule_word,
    ) -> SearchBook | None:
        search_book = SearchBook()
        search_book.origin = self.source.bookSourceUrl
        search_book.originName = self.source.bookSourceName
        search_book.type = self.source.bookSourceType
        search_book.originOrder = self.source.customOrder
        analyze_rule.rule_data = search_book
        analyze_rule.set_content(item)
        search_book.name = format_book_name(analyze_rule.get_string_rules(rule_name))
        if not search_book.name:
            return None
        search_book.author = format_book_author(analyze_rule.get_string_rules(rule_author))
        try:
            kinds = analyze_rule.get_string_rules(rule_kind)
            search_book.kind = ",".join(kinds) if kinds else None
        except Exception:
            pass
        try:
            search_book.wordCount = word_count_format(analyze_rule.get_string_rules(rule_word))
        except Exception:
            pass
        try:
            search_book.latestChapterTitle = analyze_rule.get_string_rules(rule_last)
        except Exception:
            pass
        try:
            intro = analyze_rule.get_string_rules(rule_intro)
            if intro:
                from reader.core.js.bridge import _html_format

                search_book.intro = _html_format(intro)
        except Exception:
            pass
        try:
            cover = analyze_rule.get_string_rules(rule_cover)
            if cover:
                from reader.utils.net_utils import get_absolute_url

                search_book.coverUrl = get_absolute_url(base_url, cover)
        except Exception:
            pass
        search_book.bookUrl = analyze_rule.get_string_rules(rule_book_url, is_url=True)
        if not search_book.bookUrl:
            search_book.bookUrl = base_url
        return search_book

    # ---- 书籍详情（对照 BookInfo.analyzeBookInfo）----

    def get_book_info(self, book: Book, can_re_name: bool = True) -> Book:
        book.type = self.source.bookSourceType
        analyze_url = self._analyze_url(
            book.bookUrl, base_url=self.source.bookSourceUrl, rule_data=book,
        )
        res = self._fetch(analyze_url)
        self.analyze_book_info(book, res.body, self._new_rule(book), book.bookUrl, res.url, can_re_name)
        return book

    def analyze_book_info(
        self,
        book: Book,
        body: str | None,
        analyze_rule: AnalyzeRule,
        base_url: str,
        redirect_url: str,
        can_re_name: bool,
    ) -> None:
        if body is None:
            raise ValueError(f"error_get_web_content: {base_url}")
        from reader.models.book_source import BookInfoRule

        info_rule = self.source.ruleBookInfo or BookInfoRule()
        analyze_rule.set_content(body, base_url)
        analyze_rule.set_redirect_url(redirect_url)

        if info_rule.init:
            analyze_rule.set_content(analyze_rule.get_element(info_rule.init))

        m_can_re_name = can_re_name and bool(info_rule.canReName)

        name = format_book_name(analyze_rule.get_string(info_rule.name))
        if name and (m_can_re_name or not book.name):
            book.name = name
        author = format_book_author(analyze_rule.get_string(info_rule.author))
        if author and (m_can_re_name or not book.author):
            book.author = author
        try:
            kinds = analyze_rule.get_string_list(info_rule.kind)
            if kinds and ",".join(kinds):
                book.kind = ",".join(kinds)
        except Exception:
            pass
        try:
            wc = word_count_format(analyze_rule.get_string(info_rule.wordCount))
            if wc:
                book.wordCount = wc
        except Exception:
            pass
        try:
            last = analyze_rule.get_string(info_rule.lastChapter)
            if last:
                book.latestChapterTitle = last
        except Exception:
            pass
        try:
            intro = analyze_rule.get_string(info_rule.intro)
            if intro:
                from reader.core.js.bridge import _html_format

                book.intro = _html_format(intro)
        except Exception:
            pass
        try:
            cover = analyze_rule.get_string(info_rule.coverUrl)
            if cover:
                from reader.utils.net_utils import get_absolute_url

                book.coverUrl = get_absolute_url(redirect_url, cover)
        except Exception:
            pass
        from reader.utils.net_utils import get_absolute_url

        toc_url = analyze_rule.get_string(info_rule.tocUrl, is_url=True)
        book.tocUrl = toc_url or base_url

    # ---- 目录（对照 BookChapterList.analyzeChapterList）----

    def get_chapter_list(self, book: Book) -> list[BookChapter]:
        book.type = self.source.bookSourceType
        toc_rule = self.source.ruleToc
        list_rule = (toc_rule.chapterList if toc_rule else "") or ""
        reverse = False
        if list_rule.startswith("-"):
            reverse = True
            list_rule = list_rule[1:]
        elif list_rule.startswith("+"):
            list_rule = list_rule[1:]

        if book.bookUrl == book.tocUrl and getattr(book, "toc_html", None):
            chapters, _ = self._analyze_chapter_list(book, book.toc_html, book.tocUrl, book.tocUrl, list_rule, True)
        else:
            analyze_url = self._analyze_url(book.tocUrl, base_url=book.bookUrl, rule_data=book)
            res = self._fetch(analyze_url)
            chapters, next_urls = self._analyze_chapter_list(
                book, res.body, book.tocUrl, res.url, list_rule, True
            )
            # 翻页：单链接串行 / 多链接并发
            seen = {book.tocUrl, res.url}
            if len(next_urls) == 1:
                next_url = next_urls[0]
                while next_url and next_url not in seen:
                    seen.add(next_url)
                    au = self._analyze_url(next_url, base_url=book.tocUrl, rule_data=book)
                    page_res = self._fetch(au)
                    more, next_next = self._analyze_chapter_list(
                        book, page_res.body, next_url, page_res.url, list_rule, True
                    )
                    chapters.extend(more)
                    next_url = next_next[0] if next_next else ""
            elif len(next_urls) > 1:
                with ThreadPoolExecutor(max_workers=min(8, len(next_urls))) as pool:
                    futures = []
                    for u in next_urls:
                        if u in seen:
                            continue
                        seen.add(u)
                        futures.append(pool.submit(self._fetch_page_chapters, book, u, list_rule))
                    for f in futures:
                        chapters.extend(f.result())

        if not chapters:
            raise TocEmptyException("目录为空")
        if not reverse:
            chapters.reverse()
        # 去重（LinkedHashSet 语义：保留首次出现顺序）后反转恢复正序
        seen_urls: set[tuple] = set()
        deduped: list[BookChapter] = []
        for c in chapters:
            key = (c.url, c.title)
            if key in seen_urls:
                continue
            seen_urls.add(key)
            deduped.append(c)
        deduped.reverse()
        for i, c in enumerate(deduped):
            c.index = i
        book.totalChapterNum = len(deduped)
        if deduped:
            book.latestChapterTitle = deduped[-1].title
        return deduped

    def _fetch_page_chapters(self, book: Book, url: str, list_rule: str) -> list[BookChapter]:
        au = self._analyze_url(url, base_url=book.tocUrl, rule_data=book)
        res = self._fetch(au)
        more, _ = self._analyze_chapter_list(book, res.body, url, res.url, list_rule, False)
        return more

    def _analyze_chapter_list(
        self,
        book: Book,
        body: str | None,
        base_url: str,
        redirect_url: str,
        list_rule: str,
        get_next_url: bool,
    ) -> tuple[list[BookChapter], list[str]]:
        if body is None:
            raise ValueError("error_get_web_content")
        toc_rule = self.source.ruleToc
        analyze_rule = self._new_rule(book)
        analyze_rule.set_content(body, base_url)
        analyze_rule.set_redirect_url(redirect_url)

        chapter_list: list[BookChapter] = []
        elements = analyze_rule.get_elements(list_rule)

        next_urls: list[str] = []
        next_toc_rule = toc_rule.nextTocUrl if toc_rule else None
        if get_next_url and next_toc_rule:
            urls = analyze_rule.get_string_list(next_toc_rule, is_url=True)
            for u in urls or []:
                if u != redirect_url:
                    next_urls.append(u)

        if elements:
            r_name = analyze_rule.split_source_rule(toc_rule.chapterName)
            r_url = analyze_rule.split_source_rule(toc_rule.chapterUrl)
            r_vip = analyze_rule.split_source_rule(toc_rule.isVip)
            r_up = analyze_rule.split_source_rule(toc_rule.updateTime)
            r_volume = analyze_rule.split_source_rule(toc_rule.isVolume)
            for index, item in enumerate(elements):
                analyze_rule.set_content(item)
                chapter = BookChapter(bookUrl=book.bookUrl, baseUrl=redirect_url)
                analyze_rule.chapter = chapter
                chapter.title = analyze_rule.get_string_rules(r_name)
                chapter.url = analyze_rule.get_string_rules(r_url)
                chapter.tag = analyze_rule.get_string_rules(r_up)
                chapter.isVolume = False
                is_volume = analyze_rule.get_string_rules(r_volume)
                if is_volume.strip().lower() in ("true", "1", "yes"):
                    chapter.isVolume = True
                if not chapter.url:
                    if chapter.isVolume:
                        chapter.url = chapter.title + str(index)
                    else:
                        chapter.url = base_url
                if chapter.title:
                    is_vip = analyze_rule.get_string_rules(r_vip)
                    if is_vip.strip().lower() in ("true", "1", "yes"):
                        chapter.title = "🔒" + chapter.title
                    chapter_list.append(chapter)
        return chapter_list, next_urls

    # ---- 正文（对照 BookContent.analyzeContent）----

    def get_book_content(self, book: Book, chapter: BookChapter, next_chapter_url: str | None = None) -> str:
        content_rule = self.source.ruleContent
        if content_rule is None or not content_rule.content:
            return chapter.url
        if chapter.isVolume and chapter.url.startswith(chapter.title):
            return chapter.tag or ""

        analyze_url = self._analyze_url(
            chapter.get_absolute_url(), base_url=book.tocUrl, rule_data=book, chapter=chapter,
        )
        res = self.http.fetch_str_sync(
            analyze_url,
        )
        return self.analyze_content(
            res.body, book, chapter, chapter.url, res.url, next_chapter_url,
        )

    def analyze_content(
        self,
        body: str | None,
        book: Book,
        chapter: BookChapter,
        base_url: str,
        redirect_url: str,
        next_chapter_url: str | None = None,
    ) -> str:
        if body is None:
            raise ValueError("error_get_web_content")
        content_rule = self.source.ruleContent
        m_next = next_chapter_url or None

        content_parts: list[str] = []
        next_url_list = [redirect_url]
        analyze_rule = self._new_rule(book)
        analyze_rule.set_content(body, base_url)
        analyze_rule.set_redirect_url(redirect_url)
        analyze_rule.chapter = chapter
        analyze_rule.next_chapter_url = m_next

        text, next_urls = self._content_once(analyze_rule, content_rule, redirect_url)
        content_parts.append(text)

        if len(next_urls) == 1:
            next_url = next_urls[0]
            while next_url and next_url not in next_url_list:
                from reader.utils.net_utils import get_absolute_url

                if m_next and get_absolute_url(redirect_url, next_url) == get_absolute_url(redirect_url, m_next):
                    break
                next_url_list.append(next_url)
                au = self._analyze_url(next_url, base_url=book.tocUrl, rule_data=book, chapter=chapter)
                page_res = self._fetch(au)
                if page_res.body is not None:
                    pr = self._new_rule(book)
                    pr.set_content(page_res.body, next_url)
                    pr.set_redirect_url(page_res.url)
                    pr.chapter = chapter
                    pr.next_chapter_url = m_next
                    text, nx = self._content_once(pr, content_rule, next_url)
                    next_url = nx[0] if nx else ""
                    content_parts.append("\n" + text)
        elif len(next_urls) > 1:
            with ThreadPoolExecutor(max_workers=min(8, len(next_urls))) as pool:
                futures = []
                for u in next_urls:
                    futures.append(pool.submit(self._fetch_next_page, book, chapter, u, content_rule, m_next))
                for f in futures:
                    content_parts.append("\n" + f.result())

        content_str = "".join(content_parts)
        if content_rule.replaceRegex:
            analyze_rule.rule_data = book
            content_str = analyze_rule.get_string(content_rule.replaceRegex, content_str)
        return content_str

    def _fetch_next_page(self, book, chapter, url, content_rule, m_next) -> str:
        au = self._analyze_url(url, base_url=book.tocUrl, rule_data=book, chapter=chapter)
        res = self._fetch(au)
        pr = self._new_rule(book)
        pr.set_content(res.body, url)
        pr.set_redirect_url(res.url)
        pr.chapter = chapter
        pr.next_chapter_url = m_next
        text, _ = self._content_once(pr, content_rule, url)
        return text

    def _content_once(self, analyze_rule: AnalyzeRule, content_rule, redirect_url: str) -> tuple[str, list[str]]:
        content = analyze_rule.get_string(content_rule.content)
        content = format_keep_img(content, redirect_url)
        next_urls: list[str] = []
        if content_rule.nextContentUrl:
            urls = analyze_rule.get_string_list(content_rule.nextContentUrl, is_url=True)
            if urls:
                next_urls.extend(urls)
        return content, next_urls


def format_keep_img(html: str | None, redirect_url: str | None = None) -> str:
    """HtmlFormatter.formatKeepImg：块级标签转行、去标签、img 绝对化。"""
    if not html:
        return ""
    import re

    from reader.utils.net_utils import get_absolute_url

    s = re.sub(r"</?(?:div|p|br|hr|h\d|article|dd|dl)[^>]*>", "\n", html)
    s = re.sub(r"<!--[^>]*-->", "", s)
    s = re.sub(r"</?(?!img)[a-zA-Z]+(?=[ >])[^<>]*>", "", s)
    s = re.sub(r"\s*\n+\s*", "\n　　", s)
    s = re.sub(r"^[\n\s]+", "　　", s)
    s = re.sub(r"[\n\s]+$", "", s)

    def _img_repl(m: re.Match) -> str:
        src = m.group(3) or m.group(2) or m.group(1)
        if not src:
            return m.group(0)
        param = ""
        pm = re.search(r"\s*,\s*(?=\{)", src)
        if pm:
            param = "," + src[pm.end():]
            src = src[: pm.start()]
        return f'<img src="{get_absolute_url(redirect_url, src) + param}">'

    img_pattern = re.compile(
        r'<img[^>]*src *= *"([^"{]*\{(?:[^{}]|\{[^}]+\})+\})"[^>]*>'
        r"|<img[^>]*data-[^=]*= *\"([^\"]*)\"[^>]*>"
        r'|<img[^>]*src *= *"([^"]*)"[^>]*>',
        re.IGNORECASE,
    )
    return img_pattern.sub(_img_repl, s)
