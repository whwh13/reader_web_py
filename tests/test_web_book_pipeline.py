"""mock 书源夹具全链路联调：搜索 → 详情 → 目录 → 正文（P2 集成测试）。

夹具服务器移植自 legacy scripts/mock-book-source.py（确定性输出）。
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from reader.core.net.cookie_store import CookieStore
from reader.core.net.http_client import HttpClient
from reader.core.js.engine import QuickJsEngine
from reader.core.js.bridge import JsBridge
from reader.models.book import Book
from reader.models.book_source import BookSource, parse_book_sources
from reader.services.web_book import WebBook
from reader.config import settings

MOCK_PORT = 18972
BASE = f"http://127.0.0.1:{MOCK_PORT}"

# 与 legacy compare-web-source-reading.ps1 相同的配套规则
SOURCE_JSON = {
    "bookSourceUrl": BASE,
    "bookSourceName": "差分夹具",
    "bookSourceGroup": "test",
    "enabled": True,
    "searchUrl": f"{BASE}/search?key={{{{key}}}}&delayMs=0",
    "ruleSearch": {
        "bookList": "class.book",
        "name": "class.name@text",
        "author": "class.author@text",
        "bookUrl": "tag.a@href",
    },
    "ruleBookInfo": {
        "name": "tag.h1@text",
        "author": "class.author@text",
        "tocUrl": "class.toc@href",
    },
    "ruleToc": {"chapterList": "class.chapter", "chapterName": "tag.a@text", "chapterUrl": "tag.a@href"},
    "ruleContent": {"content": "class.content@html"},
}


@pytest.fixture(scope="module")
def mock_server():
    script = Path(__file__).parent.parent / "scripts" / "mock_book_source.py"
    proc = subprocess.Popen(
        [sys.executable, str(script), "--port", str(MOCK_PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    import urllib.request

    for _ in range(50):
        try:
            urllib.request.urlopen(f"{BASE}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("mock 书源服务器启动失败")
    yield proc
    proc.kill()


@pytest.fixture(scope="module")
def web_book(mock_server):
    http = HttpClient(CookieStore(settings.data_dir))
    bridge = JsBridge(lambda: None)
    engine = QuickJsEngine(bridge)
    source = BookSource.model_validate(SOURCE_JSON)
    return WebBook(source, http, engine), source


def test_search(web_book):
    wb, source = web_book
    results = wb.search_book("差分测试书", 1)
    assert len(results) == 1
    sb = results[0]
    assert sb.name == "差分测试书"
    assert sb.author == "测试作者"
    assert sb.bookUrl.endswith("/book")


def test_book_info(web_book):
    wb, source = web_book
    book = Book(bookUrl=f"{BASE}/book", origin=source.bookSourceUrl, originName=source.bookSourceName)
    wb.get_book_info(book)
    assert book.name == "差分测试书"
    assert book.author == "测试作者"
    assert book.tocUrl.endswith("/toc")


def test_chapter_list(web_book):
    wb, source = web_book
    book = Book(bookUrl=f"{BASE}/book", tocUrl=f"{BASE}/toc", origin=source.bookSourceUrl)
    chapters = wb.get_chapter_list(book)
    assert len(chapters) == 2
    assert chapters[0].title == "第一章 起点"
    assert chapters[0].index == 0
    assert chapters[1].title == "第二章 继续"
    assert chapters[0].url.endswith("/chapter/1")


def test_content(web_book):
    wb, source = web_book
    book = Book(bookUrl=f"{BASE}/book", tocUrl=f"{BASE}/toc", origin=source.bookSourceUrl)
    from reader.models.book import BookChapter

    ch = BookChapter(bookUrl=book.bookUrl, baseUrl=book.tocUrl, index=0, title="第一章 起点", url=f"{BASE}/chapter/1")
    content = wb.get_book_content(book, ch)
    assert "第一段，中文与 UTF-8。" in content
    assert "第二段，符号 & 空格。" in content


def test_source_json_parse():
    """书源 JSON 宽松解析：数组、单个对象均可。"""
    arr = parse_book_sources(json.dumps([SOURCE_JSON]))
    assert len(arr) == 1 and arr[0].bookSourceName == "差分夹具"
    single = parse_book_sources(json.dumps(SOURCE_JSON))
    assert single[0].bookSourceUrl == BASE
