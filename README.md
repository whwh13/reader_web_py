# reader-py — 「阅读」小说服务的 Python 重写

「阅读」(reader/legado) 网文服务的**本地单用户** Python 全量重写。后端 Python 3.12 + FastAPI，
前端 Vue 3 + Element Plus。**API 与 `/reader3` 契约保持兼容**——KOReader 的
[legado.koplugin](https://github.com/pengcw/legado.koplugin)（Kindle 等 KOReader 设备插件）可直接连接使用。

行为基线：[warpdotsys/reader-dev](https://github.com/warpdotsys/reader-dev) 的 `legacy` 分支（本地路径 `../reader-dev`）。
契约参考：`reference/legado.koplugin/`（只读快照）。

## 快速开始

```powershell
# 后端（uv 管理，首次 uv sync 自动建 .venv）
~/.local/bin/uv.exe sync
~/.local/bin/uv.exe pip install -e .   # 若 sync 后提示找不到 reader 包则执行一次
~/.local/bin/uv.exe run uvicorn reader.app:app --host 127.0.0.1 --port 8081

# 前端 dev（Node 20+，依赖已提交 package-lock）
cd frontend
npm install --registry=https://registry.npmmirror.com
npm run dev     # http://localhost:5173，/reader3 代理到 8081
```

- Web 界面：http://localhost:5173/（dev）或 `npm run build` 后由后端托管（backlog）
- 后端 API：http://localhost:8081/reader3/*，健康检查 `/health`
- **KOReader 插件**：服务器地址 `http://<本机IP>:8081/reader3`，用户名密码留空
- 运行数据：`data/`（SQLite + 章节缓存 + cookie），环境变量前缀 `READER_PY_`（如 `READER_PY_PORT`）

## 功能范围

**有**：书源管理（JSON 格式与「阅读」生态 100% 兼容）、单源/多源搜索（并发窗口+游标）、
书籍详情/目录（翻页目录）/正文（翻页正文+净化替换+缓存）、书架、阅读进度、换源、封面代理、
JS 规则引擎（QuickJS + `java.*` 桥 v1：网络/加解密/编码/zip 等高频方法）。

**砍掉**（本地单用户不需要）：多用户/登录、WebDAV、RSS、TTS、webview 书源、license、MongoDB。

**Backlog**：探索页、书源调试器、书源订阅、本地 TXT/EPUB 导入、用户替换规则、webview（Playwright）、
封面本地缓存、正文图片本地化。

## 架构

```
src/reader/
├── api/routes/reader3.py   # /reader3 兼容层（19 端点）
├── core/rule/              # 规则引擎：切分器/五模式解析/编排/URL 分析
├── core/js/                # QuickJS 沙箱 + java.* 桥（JsExtensions v1）
├── core/net/               # httpx 客户端（同步供桥、异步供 API）+ cookie + 编码探测
├── models/                 # BookSource（书源 JSON 兼容）/ Book / BookChapter
├── services/               # 四管线（搜索/详情/目录/正文）+ 多源搜索 + 服务粘合
└── store/                  # SQLite + 章节磁盘缓存
frontend/                   # Vue3 + Vite + Pinia + Element Plus（5 页面）
scripts/mock_book_source.py # 确定性书源夹具（移植自 legacy）
tests/                      # 规则引擎金标准 + 管线联调 + /reader3 契约测试
```

规则引擎是整个系统的地基，逐语义移植自 legacy（AnalyzeRule/RuleAnalyzer/AnalyzeByJSoup 等），
差异点在测试里有注释标注（如 `0:2` 是两个独立索引、`##regex##repl##1` 只保留首个匹配替换结果）。

## 测试

```powershell
~/.local/bin/uv.exe run python -m pytest tests/ -q
```

- `test_rule_*.py`：规则引擎语法元素金标准
- `test_web_book_pipeline.py`：mock 书源全链路（搜索→详情→目录→正文）
- `test_reader3_contract.py`：按 KOReader 插件调用序列的端到端契约

## 已知边界

- JS 桥 v1 未覆盖的方法：`queryTTF` 字体反爬（返回原文）、webview 类（返回 null）——
  遇到依赖它们的书源会解析失败，按需在 `core/js/bridge.py` 补。
- 正文图片保留远程绝对 URL，未本地化到 `/book-assets`（backlog）。
- jayway JSONPath 的极少数方言（`@.length()` 等）未适配。
