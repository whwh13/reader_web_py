"""变量存储（对照 legacy RuleDataInterface / Book.variableMap）。"""

from __future__ import annotations


class RuleData:
    """规则执行期变量容器（@put/@get 的存储，JSON 字符串持久化由调用方负责）。"""

    def __init__(self) -> None:
        self._variables: dict[str, str] = {}

    def put_variable(self, key: str, value: str) -> None:
        self._variables[key] = value

    def get_variable(self, key: str, default: str | None = None) -> str | None:
        return self._variables.get(key, default)
