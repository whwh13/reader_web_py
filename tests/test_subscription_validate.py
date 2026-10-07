"""书源订阅与批量校验测试（本地夹具服务器）。"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from reader.config import settings
from reader.core.net.cookie_store import CookieStore
from reader.core.net.http_client import HttpClient
from reader.core.js.engine import QuickJsEngine
from reader.core.js.bridge import JsBridge
from reader.services.reader_service import ReaderService
from reader.services.subscription_service import SubscriptionService
from reader.services.validate_service import validate_one_sync


@pytest.fixture(scope="module")
def fixture_server(tmp_path_factory):
    """订阅夹具 + 真实 mock 书源服务器（好源可搜索，坏源指向死端口）。"""
    import subprocess
    import sys
    import urllib.request

    good_port = 18993  # 订阅 JSON 夹具
    book_port = 18992  # mock 书源服务器
    dead_port = 18983  # 没有服务器监听

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            base = f"http://127.0.0.1:{book_port}"
            payload = [
                {
                    "bookSourceUrl": f"{base}/good",
                    "bookSourceName": "好源",
                    "enabled": True,
                    "searchUrl": base + "/search?key={{key}}",
                    "ruleSearch": {
                        "bookList": "class.book",
                        "name": "class.name@text",
                        "author": "class.author@text",
                        "bookUrl": "tag.a@href",
                    },
                },
                {
                    "bookSourceUrl": f"http://127.0.0.1:{dead_port}/bad",
                    "bookSourceName": "坏源",
                    "enabled": True,
                    "searchUrl": f"http://127.0.0.1:{dead_port}/search?key={{{{key}}}}",
                    "ruleSearch": {"bookList": "class.book", "name": "class.name@text", "bookUrl": "tag.a@href"},
                },
            ]
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", good_port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    mock = subprocess.Popen(
        [sys.executable, str(Path(__file__).parent.parent / "scripts" / "mock_book_source.py"),
         "--port", str(book_port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{book_port}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    else:
        mock.kill()
        server.shutdown()
        pytest.fail("mock 书源服务器启动失败")
    yield {"sub_url": f"http://127.0.0.1:{good_port}/sub.json", "good_port": book_port, "dead_port": dead_port}
    mock.kill()
    server.shutdown()


@pytest.fixture()
def service(tmp_path):
    settings.data_dir = tmp_path
    return ReaderService()


def test_subscription_roundtrip(service, fixture_server):
    sub = SubscriptionService(service.db)
    # 添加订阅（立即拉取）
    result = sub.add_sub(fixture_server["sub_url"], "测试订阅")
    assert result["ok"], result.get("error")
    assert result["count"] == 2

    subs = sub.list_subs()
    assert len(subs) == 1
    assert subs[0]["sourceCount"] == 2 and subs[0]["lastSyncTime"] > 0

    # 书源入库
    keys = [s.bookSourceUrl for s in service.list_sources()]
    assert any(k.endswith("/good") for k in keys)
    assert any(k.endswith("/bad") for k in keys)

    # 删除订阅不删已导入书源（与 legacy 语义一致）
    sub.remove_sub(fixture_server["sub_url"])
    assert sub.list_subs() == []
    assert len(service.list_sources()) == 2


def test_validate_marks_invalid(service, fixture_server):
    sub = SubscriptionService(service.db)
    sub.add_sub(fixture_server["sub_url"], "测试订阅")

    sources = {s.bookSourceUrl: s for s in service.list_sources()}
    good = sources[f"http://127.0.0.1:{fixture_server['good_port']}/good"]
    bad = sources[f"http://127.0.0.1:{fixture_server['dead_port']}/bad"]

    http = service.http
    r_good = validate_one_sync(good, "差分", http, service.engine)
    assert r_good.ok, r_good.error
    assert r_good.count == 1

    r_bad = validate_one_sync(bad, "差分", http, service.engine)
    assert not r_bad.ok
    assert r_bad.error

    service.db.set_check_result(good.bookSourceUrl, r_good.ok, r_good.error)
    service.db.set_check_result(bad.bookSourceUrl, r_bad.ok, r_bad.error)
    invalid = service.db.list_invalid_sources()
    assert invalid == [bad.bookSourceUrl]


def test_sub_link_tracking_and_cascade(service, fixture_server):
    """订阅导入打来源标记；级联删除按标记删除；手动导入不打标记。"""
    sub = SubscriptionService(service.db)
    sub.add_sub(fixture_server["sub_url"], "测试订阅")

    keys = [s.bookSourceUrl for s in service.list_sources()]
    # 全部书源都带订阅来源标记
    by_sub = service.db.list_source_keys_by_sub(fixture_server["sub_url"])
    assert set(by_sub) == set(keys)
    for k in keys:
        assert service.db.get_source_sub_link(k) == fixture_server["sub_url"]

    # 手动导入（不带订阅）不打标记
    manual = {
        "bookSourceUrl": "http://manual.example/src",
        "bookSourceName": "手动源",
        "searchUrl": "http://manual.example/s?key={{key}}",
    }
    from reader.models.book_source import parse_book_sources

    service.save_sources(parse_book_sources([manual]))
    assert service.db.get_source_sub_link("http://manual.example/src") is None

    # 仅删除订阅：书源保留，来源标记也保留（可追溯；重新订阅可对上）
    sub.remove_sub(fixture_server["sub_url"], delete_sources=False)
    assert len(service.list_sources()) == 3
    assert sub.list_subs() == []
    for k in keys:
        assert service.db.get_source_sub_link(k) == fixture_server["sub_url"]

    # 重新订阅后级联删除：书源与订阅一起删
    sub.add_sub(fixture_server["sub_url"], "测试订阅")
    removed = sub.remove_sub(fixture_server["sub_url"], delete_sources=True)
    assert removed == 2
    remaining = [s.bookSourceUrl for s in service.list_sources()]
    assert remaining == ["http://manual.example/src"]
    assert sub.list_subs() == []


def test_batch_enable_and_selected_validate(service, fixture_server):
    """批量启停端点语义（db 层）+ SSE 只校验选中源（含停用源）。"""
    import asyncio

    from reader.services.validate_service import validate_all_sse

    sub = SubscriptionService(service.db)
    sub.add_sub(fixture_server["sub_url"], "测试订阅")
    keys = [s.bookSourceUrl for s in service.list_sources()]
    good_key = next(k for k in keys if k.endswith("/good"))
    bad_key = next(k for k in keys if k.endswith("/bad"))

    # 停用全部 → 只校验选中（停用源也校验）仍能跑
    updated = service.db.set_sources_enabled(keys, False)
    assert updated == 2
    assert all(not s.enabled for s in service.list_sources())

    async def collect():
        frames = []
        summary = None
        async for frame in validate_all_sse(
            service, keyword="差分", concurrency=2, only_keys=[good_key, bad_key]
        ):
            # 帧形如 'event: X\ndata: {...}\n\n'，取 data 行解析
            for line in frame.splitlines():
                if line.startswith("data: "):
                    payload = json.loads(line.removeprefix("data: "))
                    if "rate" in payload:
                        summary = payload
                    else:
                        frames.append(payload)
        return frames, summary

    frames, summary = asyncio.run(collect())
    assert {f["bookSourceUrl"] for f in frames if "bookSourceUrl" in f} == {good_key, bad_key}
    assert summary is not None and summary["total"] == 2
    # 停用的源也真实校验：good 应通过（校验不看 enabled，only_keys 场景含停用源）
    ok_map = {f["bookSourceUrl"]: f["ok"] for f in frames if "bookSourceUrl" in f}
    assert ok_map[good_key] is True

    # 重新启用
    updated = service.db.set_sources_enabled([good_key], True)
    assert updated == 1
    enabled_map = {s.bookSourceUrl: s.enabled for s in service.list_sources()}
    assert enabled_map[good_key] is True and enabled_map[bad_key] is False
