"""规则切分器（对照 legacy RuleAnalyzer.kt，逐行忠实移植）。

解决书源规则中 &&/||/%% 分隔符与 JSONPath 自带运算符、
正则/字符串字面量中同名符号的冲突：切割时跳过 [...]/(...)
筛选器内部（平衡组，感知引号与转义）。
"""

from __future__ import annotations

from collections.abc import Callable

_ESC = "\\"


class RuleBalanceError(Exception):
    """平衡组不闭合。"""


class RuleAnalyzer:
    def __init__(self, data: str, code: bool = False) -> None:
        self.queue = data
        self.pos = 0
        self.start = 0
        self.start_x = 0
        self.rule: list[str] = []
        self.step = 0
        self.elements_type = ""
        self.inner_type = True
        self._chomp_balanced = self.chomp_code_balanced if code else self.chomp_rule_balanced

    def trim(self) -> None:
        """修剪规则前的 @ 或空白符。"""
        if self.pos >= len(self.queue):
            return
        if self.queue[self.pos] == "@" or self.queue[self.pos] < "!":
            self.pos += 1
            while self.pos < len(self.queue) and (
                self.queue[self.pos] == "@" or self.queue[self.pos] < "!"
            ):
                self.pos += 1
            self.start = self.pos
            self.start_x = self.pos

    def re_set_pos(self) -> None:
        self.pos = 0
        self.start_x = 0

    def consume_to(self, seq: str) -> bool:
        self.start = self.pos
        offset = self.queue.find(seq, self.pos)
        if offset != -1:
            self.pos = offset
            return True
        return False

    def consume_to_any(self, *seqs: str) -> bool:
        pos = self.pos
        while pos != len(self.queue):
            for s in seqs:
                if self.queue.startswith(s, pos):
                    self.step = len(s)
                    self.pos = pos
                    return True
            pos += 1
        return False

    def _find_to_any(self, *chars: str) -> int:
        pos = self.pos
        while pos != len(self.queue):
            if self.queue[pos] in chars:
                return pos
            pos += 1
        return -1

    def chomp_code_balanced(self, open_ch: str, close_ch: str) -> bool:
        """拉出非内嵌代码平衡组，存在转义文本，[...] 嵌套优先。"""
        pos = self.pos
        depth = 0
        other_depth = 0
        in_single = False
        in_double = False
        while True:
            if pos == len(self.queue):
                break
            c = self.queue[pos]
            pos += 1
            if c != _ESC:
                if c == "'" and not in_double:
                    in_single = not in_single
                elif c == '"' and not in_single:
                    in_double = not in_double
                if in_single or in_double:
                    continue
                if c == "[":
                    depth += 1
                elif c == "]":
                    depth -= 1
                elif depth == 0:
                    if c == open_ch:
                        other_depth += 1
                    elif c == close_ch:
                        other_depth -= 1
            else:
                pos += 1
            if depth <= 0 and other_depth <= 0:
                break
        if depth > 0 or other_depth > 0:
            return False
        self.pos = pos
        return True

    def chomp_rule_balanced(self, open_ch: str, close_ch: str) -> bool:
        """拉出规则平衡组：引号内转义无效。"""
        pos = self.pos
        depth = 0
        in_single = False
        in_double = False
        while True:
            if pos == len(self.queue):
                break
            c = self.queue[pos]
            pos += 1
            if c == "'" and not in_double:
                in_single = not in_single
            elif c == '"' and not in_single:
                in_double = not in_single
            if in_single or in_double:
                continue
            elif c == "\\":
                pos += 1
                continue
            if c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
            if depth <= 0:
                break
        if depth > 0:
            return False
        self.pos = pos
        return True

    def split_rule(self, *splits: str) -> list[str]:
        """按分隔符切割规则（对照 splitRule(vararg)，含两段匹配与平衡组跳过）。"""
        self.rule = []
        if len(splits) == 1:
            self.elements_type = splits[0]
            if not self.consume_to(self.elements_type):
                self.rule.append(self.queue[self.start_x :])
                return self.rule
            self.step = len(self.elements_type)
            return self._split_next()

        if not self.consume_to_any(*splits):
            self.rule.append(self.queue[self.start_x :])
            return self.rule
        return self._split_first(*splits)

    def _split_first(self, *splits: str) -> list[str]:
        while True:
            end = self.pos
            self.pos = self.start  # Kotlin: pos = start（字段赋值）
            while True:  # do-while
                st = self._find_to_any("[", "(")
                if st == -1:
                    rule = [self.queue[self.start_x : end]]
                    self.elements_type = self.queue[end : end + self.step]
                    self.pos = end + self.step
                    while self.consume_to(self.elements_type):
                        rule.append(self.queue[self.start : self.pos])
                        self.pos += self.step
                    rule.append(self.queue[self.pos :])
                    self.rule = rule
                    return rule
                if st > end:
                    rule = [self.queue[self.start_x : end]]
                    self.elements_type = self.queue[end : end + self.step]
                    self.pos = end + self.step
                    while self.consume_to(self.elements_type) and self.pos < st:
                        rule.append(self.queue[self.start : self.pos])
                        self.pos += self.step
                    if self.pos > st:
                        self.start_x = self.start
                        return self._split_next()
                    rule.append(self.queue[self.pos :])
                    self.rule = rule
                    return rule
                self.pos = st
                next_ch = "]" if self.queue[self.pos] == "[" else ")"
                if not self._chomp_balanced(self.queue[self.pos], next_ch):
                    raise RuleBalanceError(f"{self.queue[: self.start]}后未平衡")
                if end <= self.pos:
                    break
            self.start = self.pos
            if not self.consume_to_any(*splits):
                self.rule.append(self.queue[self.start_x :])
                return self.rule
            # 继续首段匹配（Kotlin 递归 splitRule(*split)）

    def _split_next(self) -> list[str]:
        while True:
            end = self.pos
            self.pos = self.start  # Kotlin: pos = start（字段赋值）
            while True:  # do-while
                st = self._find_to_any("[", "(")
                if st == -1:
                    self.rule.append(self.queue[self.start_x : end])
                    self.pos = end + self.step
                    while self.consume_to(self.elements_type):
                        self.rule.append(self.queue[self.start : self.pos])
                        self.pos += self.step
                    self.rule.append(self.queue[self.pos :])
                    return self.rule
                if st > end:
                    self.rule.append(self.queue[self.start_x : end])
                    self.pos = end + self.step
                    while self.consume_to(self.elements_type) and self.pos < st:
                        self.rule.append(self.queue[self.start : self.pos])
                        self.pos += self.step
                    if self.pos > st:
                        self.start_x = self.start
                        return self._split_next()
                    self.rule.append(self.queue[self.pos :])
                    return self.rule
                self.pos = st
                next_ch = "]" if self.queue[self.pos] == "[" else ")"
                if not self._chomp_balanced(self.queue[self.pos], next_ch):
                    raise RuleBalanceError(f"{self.queue[: self.start]}后未平衡")
                if end <= self.pos:
                    break
            self.start = self.pos
            if not self.consume_to(self.elements_type):
                self.rule.append(self.queue[self.start_x :])
                return self.rule

    def inner_rule(
        self,
        inner: str,
        start_step: int,
        end_step: int,
        fr: Callable[[str], str | None],
    ) -> str:
        """替换 {$.xxx} 形式的内嵌规则（代码平衡组）。"""
        st: list[str] = []
        while self.consume_to(inner):
            pos_pre = self.pos
            if self.chomp_code_balanced("{", "}"):
                frv = fr(self.queue[pos_pre + start_step : self.pos - end_step])
                if frv:
                    st.append(self.queue[self.start_x : pos_pre] + frv)
                    self.start_x = self.pos
                    continue
            self.pos += len(inner)
        if self.start_x == 0:
            return ""
        st.append(self.queue[self.start_x :])
        return "".join(st)

    def inner_rule_pair(
        self,
        start_str: str,
        end_str: str,
        fr: Callable[[str], str | None],
    ) -> str:
        """替换 {{...}} 形式的内嵌规则。"""
        st: list[str] = []
        while self.consume_to(start_str):
            self.pos += len(start_str)
            pos_pre = self.pos
            if self.consume_to(end_str):
                frv = fr(self.queue[pos_pre : self.pos])
                st.append(self.queue[self.start_x : pos_pre - len(start_str)] + (frv or ""))
                self.pos += len(end_str)
                self.start_x = self.pos
        if self.start_x == 0:
            return self.queue
        st.append(self.queue[self.start_x :])
        return "".join(st)
