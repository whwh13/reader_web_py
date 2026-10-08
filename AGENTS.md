# AGENTS.md — reader-py 项目约定（面向 agent）

> 「阅读」小说服务的 Python 重写（本地单用户版）。行为基线为 `../reader-dev` 的 legacy 分支；
> API 兼容 `reference/legado.koplugin/`（Kindle KOReader 插件）消费的 `/reader3` 子集。

## 命令速查（pwsh / Git Bash）

```bash
# 测试（金标准 45+ 管线联调 + 契约测试）
~/.local/bin/uv.exe run python -m pytest tests/ -q

# 后端启动（8081；8080 留给 legacy JAR 对照用）
~/.local/bin/uv.exe run uvicorn reader.app:app --host 127.0.0.1 --port 8081

# 前端（Node 在 C:\Program Files\nodejs，Git Bash 需 export PATH="$PATH:/c/Program Files/nodejs"）
cd frontend && npm run dev      # 5173，/reader3 代理到 8081
cd frontend && npm run build    # 产物 frontend/dist
```

- uv 走 TUNA 镜像（pyproject 内配置）；npm 走 npmmirror。
- 若 `uv sync` 后 import reader 失败，执行 `~/.local/bin/uv.exe pip install -e .`。
- mock 书源夹具：`uv run python scripts/mock_book_source.py --port <port>`（loopback only）。

## 关键事实

- **Python 精确 3.12**（`requires-python = ">=3.12,<3.13"`）：quickjs 只有 cp312 的 Windows 轮子，勿放宽。
- **管线是同步实现**：JS 桥（quickjs 同步回调）与 httpx 同步客户端都假设运行在 worker 线程；
  FastAPI 端点用 `asyncio.to_thread` 包装。不要把管线改成 async，除非同时重造 JS 桥的阻塞语义。
- **quickjs Context 非线程安全**：`QuickJsEngine` 内有全局锁串行化；每次 eval 独立 Context。
  桥回调走单一 `__bridge(method, argsJson)`（JSON 协议），JS 侧 `java.*` 由前导码包装。
- **query 参数已预编码**：`AnalyzeUrl._analyze_fields` 产出的 field 值是 URL 编码过的，
  httpx 必须经 `_final_url()` 拼串发送，用 `params=` 会二次编码（踩过的坑）。
- **httpx 头遍历**是 `headers.multi_items()`，不是 `items(multi=True)`（踩过的坑）。
- **lxml 删节点丢 tail**：jsoup 把标签间文本当兄弟节点，lxml 挂 tail——删 script/style 前
  必须先把 tail 并回父级（见 `analyze_jsoup._result_last` html 分支）。
- **legacy 行为陷阱**（差分对齐的依据，勿"修正"）：
  - jsoup 原写法 `0:2` 是两个独立索引，不是区间；区间只在 `[...]` 括号语法里；
  - `##正则##替换##1` 的 replaceFirst = 取首个匹配 group(0) 再替换，**结果只保留该段**；
  - `{{}}` 与选择器混排时整段进入 REGEX 模式做字面重建（不是串联执行）；
  - `RuleAnalyzer` 只保护 `[...]`/`(...)` 平衡组，引号内的 `&&` 无括号保护时照样切割。
- 契约测试 `tests/test_reader3_contract.py` 的调用序列就是 KOReader 插件的用法，改 API 前先跑它。
- `reference/legado.koplugin/` 是去 .git 的只读快照（AGPL），已移出 git 跟踪、仅本地保留；不要恢复进仓库。

## Docker / 发版工作流（container.exe + GHCR）

- **本地调试**：`container.exe build -t reader-web-py:<版本>-dev -f Dockerfile.local .`（Dockerfile.local 基础镜像指向 daocloud 镜像源，不进 git）→ `container.exe run -d --name reader-web-py -p 127.0.0.1:8082:8081 -v <数据目录>:/data reader-web-py:<版本>-dev` 调试。**注意改 version.py 后再构建**（构建上下文在启动时快照，先改版本再 build 才进镜像）。
- **正式发版**：改 `reader/version.py` 的 `__version__`（与 pyproject.toml 同步）→ 镜内调试通过 → `git commit && git tag v<版本> && git push --tags` → GitHub Actions（`.github/workflows/ci.yml`）测试 + 双平台（amd64/arm64）构建，发布 `ghcr.io/whwh13/reader_web_py:<版本>` 与 `:latest`。
- **wslc**：`C:\Program Files\WSL\container.exe`（WSL 3.0 自带，用法与 docker 几乎一样）。需要虚拟机平台特性 + 重启；docker.io 直连拉不到基础镜像（走 daocloud 镜像源）。inspect 的 `--format` 只支持 `json`（不支持 Go template）。
- **持久化**：容器数据全部在 `/data`（挂载宿主目录）——reader.db、章节缓存、cookie、封面；删容器数据不丢，已实测。
- **已知坑**：wslc 的 buildx 对全局 ARG + 多个 FROM 引用报 "base name blank"（本地版写死镜像名）；版本号统一从 `version.py` 读取——勿在 `__init__.py`/路由里硬编码（曾出 1.0.1 镜像报 1.0.0 的事故）。

## 书源管理语义（1.0.7+）

- **来源追溯**：`sources` 表 `sub_link` 列记录书源来自哪个订阅（导入/刷新时写入，`COALESCE` 保留已有标记）。存量数据无标记，点一次"刷新全部订阅"即回填。
- **enabled 双存储以列为准**：`enabled` 同时存在于 JSON data 与 SQLite 列，批量启停只改列——`get_source`/`list_sources` 读取时必须用列值覆盖 JSON 值（踩过的坑：只改列不覆盖读取，开关切换后刷新即还原）。
- **仅删订阅不清标记**：`remove_sub(delete_sources=False)` 保留书源的 sub_link（可追溯，重新订阅自动对上）；`delete_sources=True` 级联删除。
- **SSE 选中校验**：`validateBookSourcesSSE` 支持 `keys`（逗号分隔）只校验选中源，含停用源（`validate_one_sync` 的 `skip_enabled_check`）；全量校验仍跳过停用源。
- **订阅名称展示**：前端来源列显示订阅名（无名称显示去协议主机名）；分组 tag 筛选条含"全部/失效/各分组"，失效 tag 数据来自最近校验结果。

## 多源搜索语义（1.0.7+）

- **Web 搜索走 `searchBookMultiSSE?aggregate=1`**：全源流式（48 并发 × 8 轮 = 384 源/次，searchSize=2000 不截断），带"继续搜更多"按钮（isEnd=false 时显示）。
- **聚合键是书名**：前端按 name 聚合（不是 name+author）——源站作者元数据常乱填/缺失，同一本书 6 个源 6 种作者写法，严格拼接键会拆散；组内展开列表显示各来源作者供辨别。后端 `aggregate=1` 帧内按 (name, author) 归组 + 前端跨帧按 name 合并。
- **dedup 开关**：`MultiSearch(dedup=False)` 同书每源各留一条（聚合/换源场景）；`dedup=True`（默认）跨源只留第一条（legacy 语义）。dedup=False 时 aggregated 是 dict[key, list]，searchSize 按 sum(len) 判。
- **踩坑**：on_batch 同步回调里 `asyncio.Queue.put` 是协程未 await → 静默丢帧（SSE 0 字节），必须 `put_nowait`；data 帧 lastIndex 曾硬编码 -1、end 帧 isEnd 曾硬编码 True（前端进度失效），已改为真实值。
- **换源 `search_accurate_all`**：全源精搜 name+author 精确匹配、不做跨源去重——与聚合搜索互补。

## 修改后同步

改动 API 或管线行为 → 重跑全部 pytest；影响用法/架构 → 更新根 `README.md` 与本文件、
工作区根 `AGENTS.md` 登记表。

## 最后更新

- 2026-10-08：书架详情窗"换源"改"打开源站"（1.0.7）：新窗口打开该书的源站页面（bookUrl 即源站书籍页 URL）；书架不再复用 ChangeSourceDialog（阅读器内换源保留）。同日详情窗加目录/换源按钮、删除改红色、搜索选来源弹窗、搜索排序打磨、搜索全源流式+聚合、书源管理大改、书架删除修复。
- 2026-10-08：搜索选来源改弹窗（1.0.7）：来源列表原为表格下方卡片，结果多时（380+ 行）在页尾视口外看似无反应——改为 el-dialog 弹窗，点"选来源"立即弹出。
- 2026-10-08：交互与排序打磨（1.0.7）：书架改点书弹详情窗（作者/来源/章节/简介 + 右上角叉号 + 底部删除书籍），卡片不再放删除按钮（防误触）；搜索结果每帧重排（精确同名 > 前缀 > 含词 > 无关，同档多来源优先，"访问受限"垃圾条目沉底）。
- 2026-10-08：搜索优化（1.0.7）：Web 搜索改走 searchBookMultiSSE aggregate=1 全源流式（原串行只搜前 12 源）；同名书聚合展示+展开选来源入架（聚合键为书名）；修复 SSE 丢帧（Queue.put 未 await）/进度与 isEnd 硬编码 bug。
- 2026-10-08：书架删除修复（1.0.7）：Web 书架卡片加删除按钮（确认弹窗）；删书同时清理章节目录/正文磁盘缓存（ChapterCache.delete_book，按 `books/<书名_作者>/` 目录删）；契约测试补缓存清理断言。
- 2026-10-08：书源管理大改（1.0.7）：来源追溯（sub_link 列）、删除订阅可选级联删书源、书源多选批量操作（启用/停用/校验/删除）、启停开关（enabled 列为准）、分组 tag 筛选+失效 tag、SSE 选中校验。
