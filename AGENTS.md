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

- **本地调试**：`container.exe build -t reader-web-py:<版本>-dev -f Dockerfile.local .`（Dockerfile.local 基础镜像指向 daocloud 镜像源，不进 git）→ `container.exe run -d -p 8082:8081 -v <数据目录>:/data reader-web-py:<版本>-dev` 调试。
- **正式发版**：改 `reader/version.py` 的 `__version__`（与 pyproject.toml 同步）→ 镜内调试通过 → `git commit && git tag v<版本> && git push --tags` → GitHub Actions（`.github/workflows/ci.yml`）测试 + 双平台（amd64/arm64）构建，发布 `ghcr.io/whwh13/reader_web_py:<版本>` 与 `:latest`。
- **wslc**：`C:\Program Files\WSL\container.exe`（WSL 3.0 自带，用法与 docker 几乎一样）。需要虚拟机平台特性 + 重启；docker.io 直连拉不到基础镜像（走 daocloud 镜像源）。
- **持久化**：容器数据全部在 `/data`（挂载宿主目录）——reader.db、章节缓存、cookie、封面；删容器数据不丢，已实测。
- **已知坑**：wslc 的 buildx 对全局 ARG + 多个 FROM 引用报 "base name blank"（本地版写死镜像名）；版本号统一从 `version.py` 读取——勿在 `__init__.py`/路由里硬编码（曾出 1.0.1 镜像报 1.0.0 的事故）。

## 修改后同步

改动 API 或管线行为 → 重跑全部 pytest；影响用法/架构 → 更新根 `README.md` 与本文件、
工作区根 `AGENTS.md` 登记表。
