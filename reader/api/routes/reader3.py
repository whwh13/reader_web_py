"""/reader3 兼容层——legado.koplugin（Kindle KOReader 插件）消费的全部端点。

契约来源：reference/legado.koplugin/.../spore/reader3_spec.lua + reader3.lua + Legado3Auth.lua
- ReturnData：HTTP 恒 200，{isSuccess, errorMsg, data}；
- accessToken 走 query（单用户免登录，忽略）；
- login 恒成功（插件允许空凭证，不会调用；调用也兼容）。
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
import httpx

from reader import __version__
from reader.api.helpers import fail, ok, read_params
from reader.models.book import Book, BookChapter
from reader.models.book_source import parse_book_sources
from reader.services.reader_service import get_service

router = APIRouter(prefix="/reader3")


def _err(e: Exception):
    return fail(str(e) or e.__class__.__name__)


# ---- 登录（兼容桩）----


@router.post("/login")
async def login(request: Request):
    return ok({"accessToken": "local", "user": "default"})


@router.get("/getUserInfo")
async def get_user_info():
    return ok({"user": "default", "enableBookSource": True, "enableLocalStore": True})


# ---- 书架 ----


@router.get("/getBookshelf")
async def get_bookshelf(request: Request):
    p = await read_params(request)
    try:
        books = get_service().get_bookshelf(refresh=p.get_bool("refresh"))
        return ok([b.model_dump(exclude_none=True) for b in books])
    except Exception as e:
        return _err(e)


@router.post("/getShelfBook")
async def get_shelf_book(request: Request):
    p = await read_params(request)
    book = get_service().get_shelf_book(p.get_str("url"))
    if book is None:
        return fail("书籍不存在")
    return ok(book.model_dump(exclude_none=True))


@router.post("/saveBook")
async def save_book(request: Request):
    p = await read_params(request)
    try:
        # 最小校验：name/bookUrl/origin 必须非空（空 body/脏请求不入库）
        if not (p.get_str("name") and p.get_str("bookUrl") and p.get_str("origin")):
            return fail("缺少必要字段（name/bookUrl/origin）")
        book = Book.model_validate(dict(p))
        get_service().save_book(book)
        return ok(dict(p))
    except Exception as e:
        return _err(e)


@router.post("/deleteBook")
async def delete_book(request: Request):
    p = await read_params(request)
    return ok(get_service().delete_book(p.get_str("bookUrl") or p.get_str("url")))


@router.post("/saveBookProgress")
async def save_book_progress(request: Request):
    """插件契约：name/author/durChapterPos/durChapterIndex/durChapterTime/durChapterTitle/index/url。"""
    p = await read_params(request)
    url = p.get_str("url") or p.get_str("bookUrl")
    try:
        get_service().save_progress(
            url=url,
            index=p.get_int("durChapterIndex", p.get_int("index")),
            title=p.get_str("durChapterTitle") or None,
            pos=p.get_int("durChapterPos"),
            chapter_time=p.get_int("durChapterTime") or None,
        )
        return ok(True)
    except Exception as e:
        return _err(e)


# ---- 详情 / 目录 / 正文 ----


@router.post("/getBookInfo")
async def get_book_info(request: Request):
    p = await read_params(request)
    try:
        book = await asyncio.to_thread(
            get_service().get_book_info, p.get_str("bookSourceUrl"), p.get_str("url")
        )
        return ok(book.model_dump(exclude_none=True))
    except Exception as e:
        return _err(e)


@router.post("/getChapterList")
async def get_chapter_list(request: Request):
    p = await read_params(request)
    try:
        chapters = await asyncio.to_thread(
            get_service().get_chapter_list,
            p.get_str("url"),
            p.get_bool("refresh"),
            p.get_str("bookSource") or None,
            p.get_str("bookSourceUrl") or None,
        )
        return ok([c.model_dump(exclude_none=True) for c in chapters])
    except Exception as e:
        return _err(e)


@router.post("/getBookContent")
async def get_book_content(request: Request):
    p = await read_params(request)
    try:
        content = await asyncio.to_thread(
            get_service().get_book_content,
            p.get_str("url"),
            p.get_int("index"),
            p.get_bool("refresh"),
            p.get_str("bookSourceUrl") or None,
        )
        return ok(content)
    except Exception as e:
        return _err(e)


# ---- 搜索 ----


@router.get("/searchBook")
async def search_book(request: Request):
    p = await read_params(request)
    try:
        books = await asyncio.to_thread(
            get_service().search_book,
            p.get_str("key"),
            p.get_str("bookSourceUrl"),
            p.get_int("page", 1),
        )
        return ok([b.model_dump(exclude_none=True) for b in books])
    except Exception as e:
        return _err(e)


@router.get("/searchBookMulti")
async def search_book_multi(request: Request):
    p = await read_params(request)
    try:
        result = await get_service().search_multi(
            key=p.get_str("key"),
            concurrent_count=p.get_int("concurrentCount", 36),
            search_size=p.get_int("searchSize", 100),
            last_index=p.get_int("lastIndex", 0),
            page=p.get_int("page", 1),
        )
        return ok(
            {
                "lastIndex": result.last_index,
                "list": [b.model_dump(exclude_none=True) for b in result.list],
            }
        )
    except Exception as e:
        return _err(e)


@router.get("/searchBookMultiSSE")
async def search_book_multi_sse(request: Request):
    """SSE 流式多源搜索：无名 data = {lastIndex, list}，event: end 结束。

    aggregate=1：聚合分组模式——同帧内按 (name, author) 归组，帧书目为
    {book(代表条目), sourceCount, sources(各源条目)}，不做跨帧去重。
    dedup=0：关闭跨源去重（同书每源各留一条，配合前端自行聚合）。
    """
    p = await read_params(request)
    aggregate = p.get_bool("aggregate")
    # dedup=0 关闭跨源去重（同书每源各留一条，配合前端自行聚合）；默认开启
    dedup = p.get_str("dedup") != "0"
    key = p.get_str("key")

    async def gen():
        queue: asyncio.Queue = asyncio.Queue()
        # run() 结果（end 时取 is_end 判断是否真跑完全部源）
        run_result: dict = {}

        def on_batch(batch, index):
            # index = 已搜完的源数（真实进度）；同步回调里必须用 put_nowait（put 是协程）
            if aggregate:
                # 聚合分组：帧内条目按 (name, author) 归组，组内保留全部来源
                groups_in_batch: dict[tuple[str, str], list] = {}
                for b in batch:
                    groups_in_batch.setdefault((b.name, b.author), []).append(b)
                queue.put_nowait(("groups", index, [
                    {
                        "book": items[0].model_dump(exclude_none=True),
                        "sourceCount": len(items),
                        "sources": [x.model_dump(exclude_none=True) for x in items],
                    }
                    for items in groups_in_batch.values()
                ]))
            else:
                queue.put_nowait((batch, index, None))

        async def run():
            try:
                result = await get_service().search_multi(
                    key=key,
                    concurrent_count=p.get_int("concurrentCount", 36),
                    search_size=p.get_int("searchSize", 100),
                    last_index=p.get_int("lastIndex", 0),
                    page=p.get_int("page", 1),
                    on_batch=on_batch,
                    dedup=dedup,
                )
                run_result["is_end"] = result.is_end
                run_result["total"] = len(
                    [s for s in get_service().list_sources() if s.enabled]
                )
                await queue.put({"__end__": result.last_index})
            except Exception as e:
                await queue.put({"__error__": str(e)})

        task = asyncio.create_task(run())
        while True:
            item = await queue.get()
            if isinstance(item, dict) and "__end__" in item:
                yield f"event: end\ndata: {json.dumps({'lastIndex': item['__end__'], 'isEnd': run_result.get('is_end', False), 'totalSources': run_result.get('total', 0)}, ensure_ascii=False)}\n\n"
                break
            if isinstance(item, dict) and "__error__" in item:
                yield f"event: error\ndata: {json.dumps(fail(item['__error__']), ensure_ascii=False)}\n\n"
                break
            batch, index, groups = item
            if groups is not None:
                yield f"data: {json.dumps({'lastIndex': index, 'groups': groups}, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps({'lastIndex': index, 'data': [b.model_dump(exclude_none=True) for b in batch]}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---- 换源 ----


@router.post("/getAvailableBookSource")
async def get_available_book_source(request: Request):
    """换源候选：全源精搜（name+author 精确匹配），每个源各留一条，不做跨源去重。"""
    p = await read_params(request)
    try:
        shelf = get_service().get_shelf_book(p.get_str("url"))
        name = shelf.name if shelf else p.get_str("name")
        if not name:
            return ok({"lastIndex": 0, "list": []})
        author = shelf.author if shelf else p.get_str("author")
        books = await get_service().search_accurate_all(name, author)
        return ok({"lastIndex": 0, "list": [b.model_dump(exclude_none=True) for b in books]})
    except Exception as e:
        return _err(e)


@router.get("/searchBookSource")
async def search_book_source(request: Request):
    p = await read_params(request)
    try:
        shelf = get_service().get_shelf_book(p.get_str("url"))
        key = shelf.name if shelf else ""
        if not key:
            return ok({"lastIndex": 0, "list": []})
        result = await get_service().search_multi(
            key=key,
            concurrent_count=36,
            search_size=p.get_int("searchSize", 5),
            last_index=p.get_int("lastIndex", 0),
        )
        if shelf:
            result.list = [
                b for b in result.list if b.name == shelf.name and b.author == shelf.author
            ]
        return ok({"lastIndex": result.last_index, "list": [b.model_dump(exclude_none=True) for b in result.list]})
    except Exception as e:
        return _err(e)


@router.post("/setBookSource")
async def set_book_source(request: Request):
    """换源落地：更新 bookUrl/origin，保留阅读进度（目录按新源重取）。"""
    p = await read_params(request)
    svc = get_service()
    try:
        book = svc.get_shelf_book(p.get_str("bookUrl"))
        if book is None:
            return fail("书籍不在书架")
        new_source = svc.get_source(p.get_str("bookSourceUrl"))
        if new_source is None:
            return fail("书源不存在")
        old_url = book.bookUrl
        book.bookUrl = p.get_str("newUrl") or book.bookUrl
        book.origin = new_source.bookSourceUrl
        book.originName = new_source.bookSourceName
        book.tocUrl = ""
        # 主键是 bookUrl：先删旧行再存，否则旧记录残留、进度保存会重建出重复书
        svc.db.delete_book(old_url)
        svc.db.save_book(book)
        return ok(True)
    except Exception as e:
        return _err(e)


# ---- 书源管理 ----


@router.get("/getBookSources")
async def get_book_sources(request: Request):
    p = await read_params(request)
    svc = get_service()
    sources = svc.list_sources()
    if p.get_bool("simple"):
        return ok(
            [
                {
                    "bookSourceUrl": s.bookSourceUrl,
                    "bookSourceName": s.bookSourceName,
                    "bookSourceGroup": s.bookSourceGroup,
                    "enabled": s.enabled,
                    "customOrder": s.customOrder,
                    "subLink": svc.db.get_source_sub_link(s.bookSourceUrl),
                }
                for s in sources
            ]
        )
    out = []
    for s in sources:
        item = s.model_dump(exclude_none=True)
        _, check_ok, check_err = svc.db.get_check_result(s.bookSourceUrl)
        if check_ok is not None:
            item["lastCheckOk"] = bool(check_ok)
            if check_err:
                item["error"] = check_err
        sub_link = svc.db.get_source_sub_link(s.bookSourceUrl)
        if sub_link:
            item["subLink"] = sub_link
        out.append(item)
    return ok(out)


@router.post("/getBookSource")
async def get_book_source(request: Request):
    p = await read_params(request)
    source = get_service().get_source(p.get_str("bookSourceUrl"))
    if source is None:
        return fail("书源不存在")
    return ok(source.model_dump(exclude_none=True))


@router.post("/saveBookSource")
@router.post("/saveBookSources")
async def save_book_sources(request: Request):
    p = await read_params(request)
    try:
        raw = p.get("bookSource") or p.get("bookSources") or p.get("data")
        if raw is None:
            return fail("缺少书源数据")
        if isinstance(raw, str):
            sources = parse_book_sources(raw)
        elif isinstance(raw, list):
            sources = parse_book_sources(raw)
        elif isinstance(raw, dict):
            sources = parse_book_sources(raw)
        else:
            return fail("书源数据格式错误")
        if not sources:
            return fail("未解析到书源")
        get_service().save_sources(sources)
        return ok(len(sources))
    except Exception as e:
        return _err(e)


@router.post("/saveFromRemoteSource")
async def save_from_remote_source(request: Request):
    """从 URL 导入书源（订阅粘贴）。"""
    p = await read_params(request)
    url = p.get_str("url")
    if not url:
        return fail("缺少 url")
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        sources = parse_book_sources(resp.text)
        if not sources:
            return fail("远程内容未解析到书源")
        get_service().save_sources(sources)
        return ok(len(sources))
    except Exception as e:
        return _err(e)


@router.post("/deleteBookSource")
@router.post("/deleteBookSources")
async def delete_book_sources(request: Request):
    p = await read_params(request)
    raw = p.get("bookSourceUrl") or p.get("bookSourceUrls") or p.get("keys")
    if raw is None:
        return fail("缺少 bookSourceUrl")
    keys = raw if isinstance(raw, list) else [str(raw)]
    get_service().delete_sources(keys)
    return ok(True)


@router.post("/enableBookSource")
@router.post("/enableBookSources")
async def enable_book_sources(request: Request):
    """单源/批量启停书源：bookSourceUrl(s) + enabled(true/false)，返回 {enabled, updated}。"""
    p = await read_params(request)
    raw = p.get("bookSourceUrl") or p.get("bookSourceUrls") or p.get("keys")
    if raw is None:
        return fail("缺少 bookSourceUrl")
    keys = raw if isinstance(raw, list) else [str(raw)]
    enabled = p.get_bool("enabled", True)
    updated = get_service().db.set_sources_enabled(keys, enabled)
    return ok({"enabled": enabled, "updated": updated})


# ---- 兼容桩 ----


@router.get("/getTxtTocRules")
async def get_txt_toc_rules():
    return ok([])


@router.get("/getReplaceRules")
async def get_replace_rules():
    return ok([])


@router.get("/getUserConfig")
async def get_user_config():
    return ok({})


@router.post("/saveUserConfig")
async def save_user_config(request: Request):
    return ok(True)


@router.get("/getSystemInfo")
async def get_system_info():
    svc = get_service()
    return ok(
        {
            "name": "reader-py",
            "version": __version__,
            "bookshelf": {
                "total": len(svc.list_sources()),
            },
        }
    )


@router.post("/exploreBook")
async def explore_book(request: Request):
    """发现页（backlog）：返回空列表。"""
    return ok([])


# ---- 书源订阅 ----


@router.get("/getBookSourceSubs")
async def get_book_source_subs():
    from reader.services.subscription_service import SubscriptionService

    return ok(SubscriptionService(get_service().db).list_subs())


@router.post("/saveBookSourceSub")
async def save_book_source_sub(request: Request):
    """添加订阅并立即拉取导入。"""
    p = await read_params(request)
    link = p.get_str("link") or p.get_str("url")
    if not link:
        return fail("缺少订阅链接")
    from reader.services.subscription_service import SubscriptionService

    result = await asyncio.to_thread(
        SubscriptionService(get_service().db).add_sub, link, p.get_str("name")
    )
    if result["ok"]:
        return ok(result)
    return fail(result.get("error", "订阅导入失败"), result)


@router.post("/deleteBookSourceSub")
async def delete_book_source_sub(request: Request):
    """删除订阅；deleteSources=1 时级联删除该订阅导入的全部书源。"""
    p = await read_params(request)
    link = p.get_str("link") or p.get_str("url")
    if not link:
        return fail("缺少订阅链接")
    from reader.services.subscription_service import SubscriptionService

    removed = SubscriptionService(get_service().db).remove_sub(
        link, delete_sources=p.get_bool("deleteSources")
    )
    return ok({"removed": removed})


@router.post("/refreshBookSourceSub")
async def refresh_book_source_sub(request: Request):
    """刷新订阅（带 link 刷新单个，不带刷新全部）。"""
    p = await read_params(request)
    from reader.services.subscription_service import SubscriptionService

    svc = SubscriptionService(get_service().db)
    link = p.get_str("link") or p.get_str("url")
    if link:
        results = [await asyncio.to_thread(svc.refresh_one, link)]
    else:
        results = await asyncio.to_thread(svc.refresh_all)
    return ok(results)


@router.get("/getInvalidBookSources")
async def get_invalid_book_sources():
    """失效书源列表（最近一次校验失败者，legacy 同名端点语义）。"""
    return ok(get_service().db.list_invalid_sources())


@router.post("/removeInvalidBookSources")
async def remove_invalid_book_sources():
    """一键移除失效书源：删除最近一次校验失败的全部源，返回删除数。"""
    svc = get_service()
    keys = svc.db.list_invalid_sources()
    if not keys:
        return ok({"removed": 0})
    svc.db.delete_sources(keys)
    return ok({"removed": len(keys)})


# ---- 书源批量校验 ----


@router.get("/validateBookSourcesSSE")
async def validate_book_sources_sse(request: Request):
    """SSE 逐源校验：data 帧 {bookSourceUrl, ok, count, error, done, total}，end 帧汇总。

    传 keys/bookSourceUrls（逗号分隔或重复参数）时只校验选中源（含停用源）。
    """
    from reader.services.validate_service import validate_all_sse

    p = await read_params(request)
    keyword = p.get_str("keyword") or "我的"
    concurrency = min(max(p.get_int("concurrency", 12), 1), 24)
    raw_keys = p.get("keys") or p.get("bookSourceUrls")
    only_keys: list[str] | None = None
    if isinstance(raw_keys, list):
        only_keys = [str(k) for k in raw_keys if str(k)]
    elif raw_keys:
        only_keys = [k.strip() for k in str(raw_keys).split(",") if k.strip()]

    async def gen():
        async for frame in validate_all_sse(
            get_service(), keyword=keyword, concurrency=concurrency, only_keys=only_keys
        ):
            yield frame

    return StreamingResponse(gen(), media_type="text/event-stream")
