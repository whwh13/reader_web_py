"""JSONPath 解析（对照 legacy AnalyzeByJSonPath.kt，jayway json-path 语义）。

- &&/||/%% 组合与 {$.rule} 内嵌替换经 RuleAnalyzer（code 平衡组）处理；
- 路径本体用 jsonpath-ng 求值，jayway 特有语法在此做适配；
- 路径不存在时返回空（jayway 抛 PathNotFound，legacy catch 后返回空）。
"""

from __future__ import annotations

import json

from jsonpath_ng import parse as jp_parse
from jsonpath_ng.exceptions import JSONPathError

from reader.core.rule.rule_analyzer import RuleAnalyzer


def _to_str(value) -> str:
    if isinstance(value, list):
        return "\n".join(_elem_str(v) for v in value)
    return _elem_str(value)


def _elem_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        # jayway/GSON 对整数值浮点的输出习惯
        return str(int(v))
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return str(v)


def parse_if_needed(content):
    """字符串则解析为 JSON 对象；失败返回 None。"""
    if isinstance(content, (dict, list)):
        return content
    if isinstance(content, str):
        text = content.strip()
        if text[:1] in ("{", "["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return None
    return None


class AnalyzeByJsonPath:
    def __init__(self, json_data) -> None:
        obj = parse_if_needed(json_data)
        # dict/list 直接用；字符串解析失败时保留原值，read 会走异常分支返回空
        self.obj = obj if obj is not None else json_data

    def _read(self, path: str):
        """jayway read 等价。返回 (found, value)。"""
        expr = _adapt_path(path)
        try:
            exprs = jp_parse(expr)
        except (JSONPathError, Exception):
            return False, None
        matches = exprs.find(self.obj)
        if not matches:
            return False, None
        values = [m.value for m in matches]
        # jayway 单值路径返回标量；[*] 等返回数组——jsonpath-ng 的 find 总是列表，
        # 规则写了 [*] 时 matches 元素就是期望的每一项；写死下标时也是单值。
        if len(values) == 1:
            return True, values[0]
        return True, values

    def get_string(self, rule: str) -> str | None:
        if not rule:
            return None
        analyzer = RuleAnalyzer(rule, code=True)
        rules = analyzer.split_rule("&&", "||")
        if len(rules) == 1:
            analyzer.re_set_pos()
            result = analyzer.inner_rule("{$.", 1, 1, self.get_string)
            if not result:
                found, ob = self._read(rule)
                if not found:
                    return None
                return _to_str(ob)
            return result
        texts: list[str] = []
        for rl in rules:
            temp = self.get_string(rl)
            if temp:
                texts.append(temp)
                if analyzer.elements_type == "||":
                    break
        return "\n".join(texts)

    def get_string_list(self, rule: str) -> list[str]:
        result: list[str] = []
        if not rule:
            return result
        analyzer = RuleAnalyzer(rule, code=True)
        rules = analyzer.split_rule("&&", "||", "%%")
        if len(rules) == 1:
            analyzer.re_set_pos()
            st = analyzer.inner_rule("{$.", 1, 1, self.get_string)
            if not st:
                found, ob = self._read(rule)
                if not found:
                    return result
                if isinstance(ob, list):
                    result.extend(_elem_str(v) for v in ob)
                else:
                    result.append(_elem_str(ob))
            else:
                result.append(st)
            return result
        results: list[list[str]] = []
        for rl in rules:
            temp = self.get_string_list(rl)
            if temp:
                results.append(temp)
                if analyzer.elements_type == "||":
                    break
        _combine(results, analyzer.elements_type, result)
        return result

    def get_object(self, rule: str):
        found, ob = self._read(rule)
        return ob if found else None

    def get_list(self, rule: str) -> list:
        result: list = []
        if not rule:
            return result
        analyzer = RuleAnalyzer(rule, code=True)
        rules = analyzer.split_rule("&&", "||", "%%")
        if len(rules) == 1:
            found, ob = self._read(rules[0])
            if found and isinstance(ob, list):
                return ob
            return result
        results: list[list] = []
        for rl in rules:
            temp = self.get_list(rl)
            if temp:
                results.append(temp)
                if analyzer.elements_type == "||":
                    break
        if results:
            if analyzer.elements_type == "%%":
                for i in range(len(results[0])):
                    for temp in results:
                        if i < len(temp):
                            result.append(temp[i])
            else:
                for temp in results:
                    result.extend(temp)
        return result


def _combine(results: list[list[str]], elements_type: str, out: list[str]) -> None:
    if not results:
        return
    if elements_type == "%%":
        for i in range(len(results[0])):
            for temp in results:
                if i < len(temp):
                    out.append(temp[i])
    else:
        for temp in results:
            out.extend(temp)


def _adapt_path(path: str) -> str:
    """jayway → jsonpath-ng 语法适配。"""
    # jayway 允许省略根 $.（如 "store.book"），jsonpath-ng 需要显式根
    if not path.startswith(("$", "{")):
        return "$." + path
    return path
