"""书源批量校验：对启用源逐一执行真实搜索，统计成功率并标记失效源。

成功标准：搜索请求无异常且返回 ≥1 条结果（名称字段非空）。
超时/异常/空结果均记失败——用户预期 70-80% 成功率即可（订阅源里本就有死源）。
"""

from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import AsyncIterator

from reader.models.book_source import BookSource
from reader.services.reader_service import ReaderService
from reader.services.web_book import WebBook

DEFAULT_KEYWORD = "我的"
VALIDATE_TIMEOUT = 25.0


@dataclass
class CheckResult:
    bookSourceUrl: str
    bookSourceName: str
    ok: bool
    count: int = 0
    elapsed: int = 0  # ms
    error: str | None = None

    def as_dict(self) -> dict:
        d = {
            "bookSourceUrl": self.bookSourceUrl,
            "bookSourceName": self.bookSourceName,
            "ok": self.ok,
            "count": self.count,
            "elapsed": self.elapsed,
        }
        if self.error:
            d["error"] = self.error
        return d


def validate_one_sync(source: BookSource, keyword: str, http, engine) -> CheckResult:
    started = time.time()
    try:
        if not source.enabled:
            return CheckResult(source.bookSourceUrl, source.bookSourceName, False, error="已停用")
        if not source.searchUrl:
            return CheckResult(source.bookSourceUrl, source.bookSourceName, False, error="无搜索规则")
        books = WebBook(source, http, engine).search_book(keyword, 1)
        count = sum(1 for b in books if b.name)
        elapsed = int((time.time() - started) * 1000)
        if count > 0:
            return CheckResult(source.bookSourceUrl, source.bookSourceName, True, count, elapsed)
        return CheckResult(source.bookSourceUrl, source.bookSourceName, False, 0, elapsed, "搜索无结果")
    except Exception as e:
        elapsed = int((time.time() - started) * 1000)
        msg = str(e) or e.__class__.__name__
        return CheckResult(source.bookSourceUrl, source.bookSourceName, False, 0, elapsed, msg[:200])


async def validate_all_sse(
    service: ReaderService,
    keyword: str = DEFAULT_KEYWORD,
    concurrency: int = 12,
    only_enabled: bool = True,
) -> AsyncIterator[str]:
    """SSE 逐源推送校验结果，event: end 汇总 {total, ok, failed, rate}。"""
    sources = [
        s for s in service.list_sources()
        if (s.enabled or not only_enabled) and s.searchUrl
    ]
    total = len(sources)
    yield f"event: start\ndata: {json.dumps({'total': total}, ensure_ascii=False)}\n\n"

    loop = asyncio.get_running_loop()
    semaphore = asyncio.Semaphore(concurrency)
    executor = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="validate")
    ok_count = 0
    done = 0

    async def check_one(source: BookSource) -> CheckResult:
        async with semaphore:
            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(
                        executor, validate_one_sync, source, keyword, service.http, service.engine
                    ),
                    timeout=VALIDATE_TIMEOUT,
                )
            except asyncio.TimeoutError:
                result = CheckResult(
                    source.bookSourceUrl, source.bookSourceName, False, error="校验超时"
                )
            except Exception as e:  # 防御：任何异常都不能中断整个校验流
                result = CheckResult(
                    source.bookSourceUrl, source.bookSourceName, False, error=str(e)[:200]
                )
            service.db.set_check_result(source.bookSourceUrl, result.ok, result.error)
            return result

    try:
        tasks = [asyncio.create_task(check_one(s)) for s in sources]
        for coro in asyncio.as_completed(tasks):
            result = await coro
            done += 1
            if result.ok:
                ok_count += 1
            frame = {**result.as_dict(), "done": done, "total": total}
            yield f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    failed = done - ok_count
    rate = round(ok_count / done * 100, 1) if done else 0.0
    summary = {"total": done, "ok": ok_count, "failed": failed, "rate": rate}
    yield f"event: end\ndata: {json.dumps(summary, ensure_ascii=False)}\n\n"
