"""全局配置。

环境变量前缀 READER_PY_，例如 READER_PY_PORT=9000。
默认端口 8081，避开本机 8080 上可能运行的 legacy JAR。
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="READER_PY_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8081

    # 运行时数据根目录：SQLite、章节缓存、cookie jar、封面缓存
    data_dir: Path = Path("data")

    # 是否缓存章节正文到磁盘（对齐 legacy reader.app.cacheChapterContent）
    cache_chapter_content: bool = True

    # 多源搜索并发窗口大小（legacy 默认 36）
    concurrent_search: int = 36

    # 上游书源请求超时（秒）
    request_timeout: float = 20.0

    # 单用户模式固定命名空间（保留目录层级概念，方便日后扩展）
    namespace: str = "default"


settings = Settings()
