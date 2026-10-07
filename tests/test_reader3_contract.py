"""/reader3 契约测试——模拟 legado.koplugin 的完整调用序列（reader3_spec.lua）。"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reader.config import settings

MOCK_PORT = 18991
BASE = f"http://127.0.0.1:{MOCK_PORT}"

SOURCE_RULES = {
    "bookSourceUrl": BASE,
    "bookSourceName": "契约夹具",
    "bookSourceGroup": "test",
    "enabled": True,
    "searchUrl": BASE + "/search?key={{key}}&delayMs=0",
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
    "ruleToc": {
        "chapterList": "class.chapter",
        "chapterName": "tag.a@text",
        "chapterUrl": "tag.a@href",
    },
    "ruleContent": {"content": "class.content@html"},
}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    # 隔离数据目录
    import reader.services.reader_service as rs

    settings.data_dir = tmp_path_factory.mktemp("reader3_data")
    rs._service = None

    script = Path(__file__).parent.parent / "scripts" / "mock_book_source.py"
    import subprocess
    import sys
    import time
    import urllib.request

    proc = subprocess.Popen(
        [sys.executable, str(script), "--port", str(MOCK_PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            urllib.request.urlopen(f"{BASE}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("mock 服务器启动失败")

    from reader.app import app

    yield TestClient(app)
    proc.kill()


def rd(resp):
    """ReturnData 校验（插件 handleResponse 语义）。"""
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, dict) and "isSuccess" in body
    return body


def test_plugin_journey(client):
    # 1. 空书架
    body = rd(client.get("/reader3/getBookshelf?v=1&refresh=0"))
    assert body["isSuccess"] and body["data"] == []

    # 2. 导入书源（saveBookSources，插件/web 共用）
    body = rd(
        client.post(
            "/reader3/saveBookSources",
            json={"bookSources": [SOURCE_RULES]},
        )
    )
    assert body["isSuccess"] and body["data"] == 1

    # 3. getBookSources（simple=1，插件书源列表）
    body = rd(client.get("/reader3/getBookSources?v=1&simple=1"))
    assert body["isSuccess"] and len(body["data"]) == 1
    assert body["data"][0]["bookSourceUrl"] == BASE

    # 4. 单源搜索（插件 searchBook）
    body = rd(client.get(f"/reader3/searchBook?v=1&key=差分测试书&bookSourceUrl={BASE}&concurrentCount=16&lastIndex=-1&page=1"))
    assert body["isSuccess"] and len(body["data"]) == 1
    search_book = body["data"][0]
    assert search_book["name"] == "差分测试书"
    assert search_book["origin"] == BASE

    # 5. 入架（插件 saveBook 最小字段集）
    payload = {
        "name": search_book["name"],
        "author": search_book["author"],
        "bookUrl": search_book["bookUrl"],
        "origin": search_book["origin"],
        "originName": search_book["originName"],
        "originOrder": 0,
        "v": 1,
    }
    body = rd(client.post("/reader3/saveBook", json=payload))
    assert body["isSuccess"]

    # 6. 书架有一本
    body = rd(client.get("/reader3/getBookshelf?v=1&refresh=0"))
    assert body["isSuccess"] and len(body["data"]) == 1
    shelf_book = body["data"][0]

    # 7. 目录（插件 getChapterList：url=bookUrl）
    body = rd(client.post("/reader3/getChapterList", json={"url": shelf_book["bookUrl"], "v": 1}))
    assert body["isSuccess"], body["errorMsg"]
    chapters = body["data"]
    assert len(chapters) == 2
    assert chapters[0]["title"] == "第一章 起点"
    assert chapters[0]["index"] == 0

    # 8. 正文（插件 getBookContent：url + index）
    body = rd(
        client.post(
            "/reader3/getBookContent",
            json={"url": shelf_book["bookUrl"], "index": 0, "v": 1},
        )
    )
    assert body["isSuccess"], body["errorMsg"]
    assert "第一段，中文与 UTF-8。" in body["data"]

    # 9. 进度同步（插件 saveBookProgress）
    body = rd(
        client.post(
            "/reader3/saveBookProgress",
            json={
                "name": "差分测试书",
                "author": "测试作者",
                "durChapterPos": 10,
                "durChapterIndex": 1,
                "durChapterTime": 1699999999000,
                "durChapterTitle": "第二章 继续",
                "index": 1,
                "url": shelf_book["bookUrl"],
                "v": 1,
            },
        )
    )
    assert body["isSuccess"]

    # 10. 书架进度持久化
    body = rd(client.post("/reader3/getShelfBook", json={"url": shelf_book["bookUrl"], "v": 1}))
    assert body["isSuccess"]
    assert body["data"]["durChapterIndex"] == 1
    assert body["data"]["durChapterTitle"] == "第二章 继续"

    # 11. 换源候选（getAvailableBookSource：{lastIndex, list} 结构）
    body = rd(
        client.post(
            "/reader3/getAvailableBookSource",
            json={"url": shelf_book["bookUrl"], "refresh": 0, "v": 1},
        )
    )
    assert body["isSuccess"]
    assert "lastIndex" in body["data"] and isinstance(body["data"]["list"], list)

    # 12. 删除书籍（同时清理章节缓存目录）
    from reader.store.chapter_cache import ChapterCache
    from reader.config import settings as _settings

    cache = ChapterCache(_settings.data_dir)
    shelf = rd(client.get("/reader3/getBookshelf?v=1&refresh=0"))["data"] or []
    # 删书前正文缓存已存在（第 8 步拉过正文）
    book_obj = cache.load_toc.__self__ if False else None  # 占位，下面直接构造
    from reader.models.book import Book as BookModel

    book_model = BookModel.model_validate(shelf[0]) if shelf else None
    if book_model is not None:
        assert cache.toc_path(book_model).exists() or cache.content_path(book_model, 0).exists()
    body = rd(client.post("/reader3/deleteBook", json={**payload, "v": 1}))
    assert body["isSuccess"]
    body = rd(client.get("/reader3/getBookshelf?v=1&refresh=0"))
    assert body["data"] == []
    # 缓存目录一并清掉
    if book_model is not None:
        assert not (cache.root / book_model.get_folder_name()).exists() or not any(
            (cache.root / book_model.get_folder_name()).rglob("*")
        )


def test_login_stub(client):
    body = rd(client.post("/reader3/login", json={"username": "x", "password": "", "code": "", "isLogin": True, "v": 1}))
    assert body["isSuccess"] and isinstance(body["data"]["accessToken"], str)


def test_compat_stubs(client):
    assert rd(client.get("/reader3/getTxtTocRules?v=1"))["data"] == []
    assert rd(client.get("/reader3/getReplaceRules?v=1"))["data"] == []
    assert rd(client.get("/reader3/getUserConfig?v=1"))["isSuccess"]
