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
