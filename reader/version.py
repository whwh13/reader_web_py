"""reader-py 版本号（语义化版本：major.minor.patch）。

- pyproject.toml 的 project.version 与此保持一致；
- 镜像 tag 由 GitHub Actions 按 git tag（v*）发布；
- 发版流程：改此处的版本号 → 提交 → 打同名 git tag → push。
"""

__version__ = "1.0.4"
