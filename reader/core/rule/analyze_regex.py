"""正则链解析（对照 legacy AnalyzeByRegex.kt）。

多条正则 && 串行：前一条的全部匹配拼接为下一条输入，
最后一条的 group(0..n)（含整体匹配）作为字段数组。
"""

from __future__ import annotations

import re


def _groups(match: re.Match) -> list[str]:
    # Kotlin: for (groupIndex in 0..groupCount) add(group(groupIndex)) —— group(0) 在首位
    return [match.group(0)] + [g if g is not None else "" for g in match.groups()]


def get_element(res: str, regs: list[str], index: int = 0) -> list[str] | None:
    if index >= len(regs):
        return None
    pattern = re.compile(regs[index])
    matcher = pattern.search(res)
    if not matcher:
        return None
    if index + 1 == len(regs):
        return _groups(matcher)
    result = "".join(m.group(0) for m in pattern.finditer(res))
    return get_element(result, regs, index + 1)


def get_elements(res: str, regs: list[str], index: int = 0) -> list[list[str]]:
    if index >= len(regs):
        return []
    pattern = re.compile(regs[index])
    if not pattern.search(res):
        return []
    if index + 1 == len(regs):
        return [_groups(m) for m in pattern.finditer(res)]
    result = "".join(m.group(0) for m in pattern.finditer(res))
    return get_elements(result, regs, index + 1)
