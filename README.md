# reader-py

「阅读」小说服务的 **Python 全量重写**（本地单用户版）。后端 Python 3.12 + FastAPI，
前端 Vue 3 + Element Plus。`/reader3` API 与 KOReader 插件
[legado.koplugin](https://github.com/pengcw/legado.koplugin) 兼容——可在 Kindle 等
KOReader 设备上直接阅读。

> 书源规则引擎逐语义移植自 [warpdotsys/reader-dev](https://github.com/warpdotsys/reader-dev)
> （`legacy` 分支，reader-pro 3.2.14 恢复工程）；API 契约参考
> [pengcw/legado.koplugin](https://github.com/pengcw/legado.koplugin) 源码（`reader3_spec.lua`）。

## 功能

- **书源订阅**：订阅远程书源集合 URL，一键拉取导入、刷新
- **书源批量校验**：并发验证全部启用源，SSE 实时进度，统计成功率并标记失效源
- **多源搜索**：滑动窗口并发 + 游标分批 + SSE 流式，结果按相关性排序（精确命中优先）
- **完整阅读链路**：详情 / 目录（翻页目录）/ 正文（翻页正文、净化替换、章节缓存）
- **书源 JS 规则引擎**：QuickJS 沙箱 + `java.*` 桥（网络/加解密/编码/zip/jsoup 等高频方法）
- **书架与进度**：分组、阅读进度、换源；书源 JSON 格式与「阅读」生态 100% 兼容
- **Web 界面**：书架 / 搜索 / 书源管理（订阅+校验）/ 阅读器 / 设置

砍掉了本地单用户不需要的东西：多用户、登录、WebDAV、RSS、TTS、webview 书源、license、MongoDB。

## 快速开始

```bash
# 后端（uv 管理，Python 3.12）
uv sync
uv pip install -e .
uv run uvicorn reader.app:app --host 0.0.0.0 --port 8081

# 前端 dev（Node 20+）
cd frontend && npm install && npm run dev   # http://localhost:5173
```

- 书源 JSON / 订阅 URL 导入：Web 界面 → 书源管理
- **KOReader 插件**：服务器地址填 `http://<本机IP>:8081/reader3`，用户名密码留空
- 运行数据在 `data/`（SQLite + 章节缓存 + cookie），可用环境变量 `READER_PY_*` 覆盖配置

## 致谢与许可说明

本项目基于并参考了以下开源项目，感谢原作者：

| 项目 | 许可证 | 关系 |
|---|---|---|
| [hectorqin/reader](https://github.com/hectorqin/reader)（「阅读」3.0 服务端） | GPL-3.0 | 被恢复/引用的上游产品 |
| [warpdotsys/reader-dev](https://github.com/warpdotsys/reader-dev)（reader-pro 3.2.14 恢复工程） | GPL-3.0 | 书源规则引擎的移植基线（`legacy` 分支） |
| [pengcw/legado.koplugin](https://github.com/pengcw/legado.koplugin)（KOReader 插件） | **AGPL-3.0** | API 契约来源；其源码快照随仓库 `reference/` 分发（保留原许可证） |

因仓库包含 AGPL-3 许可证的 `legado.koplugin` 参考快照，本项目整体以
**GNU Affero General Public License v3.0（AGPL-3.0）** 发布（AGPL-3 与 GPL-3 依
GPL-3 第 13 条互相兼容）。详见 [LICENSE](LICENSE) 与 `reference/legado.koplugin/LICENSE`。

## 测试

```bash
uv run pytest tests/ -q
```

- `test_rule_*.py`：规则引擎金标准（逐语法元素对照 legacy 行为）
- `test_web_book_pipeline.py`：mock 书源全链路（搜索→详情→目录→正文）
- `test_reader3_contract.py`：按 KOReader 插件调用序列的端到端契约
- `test_subscription_validate.py`：订阅与批量校验

## 目录结构

```
src/reader/
├── api/routes/reader3.py   # /reader3 兼容层（插件契约 19 端点 + 订阅/校验扩展）
├── core/rule/              # 规则引擎：切分器、五模式解析器、编排器、URL 分析
├── core/js/                # QuickJS 沙箱 + java.* 桥 + org.jsoup shim
├── core/net/               # httpx 客户端（同步/异步）、cookie、编码探测
├── models/                 # BookSource（书源 JSON 兼容）/ Book / BookChapter
├── services/               # 四管线、多源搜索、订阅、批量校验
└── store/                  # SQLite + 章节磁盘缓存
frontend/                   # Vue3 + Vite + Pinia + Element Plus
scripts/mock_book_source.py # 确定性书源夹具（移植自 reader-dev）
reference/legado.koplugin/  # KOReader 插件源码快照（AGPL-3，只读参考）
```

架构与踩坑记录见 [AGENTS.md](AGENTS.md)。
