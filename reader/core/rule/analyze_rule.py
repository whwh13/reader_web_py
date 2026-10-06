"""规则解析编排器（对照 legacy AnalyzeRule.kt）。

把规则串切成有序片段（JS / CSS(jsoup) / XPath / JSONPath / Regex 混合），
前一段输出作为后一段输入；支持 ##正则替换、@put/@get、{{js}}、$N 分组引用。
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from reader.core.rule import analyze_regex, analyze_xpath, jsoup_compat as jc
from reader.core.rule.analyze_jsonpath import AnalyzeByJsonPath
from reader.core.rule.analyze_jsoup import AnalyzeByJsoup
from reader.core.rule.analyze_xpath import AnalyzeByXPath
from reader.core.rule.js_engine import NullEngine, JsEngine
from reader.core.rule.rule_data import RuleData
from reader.core.rule.rule_analyzer import RuleAnalyzer
from reader.utils.net_utils import get_absolute_url

# 对照 AppPattern
JS_PATTERN = re.compile(r"<js>([\w\W]*?)</js>|@js:([\w\W]*)", re.IGNORECASE)
_PUT_PATTERN = re.compile(r"@put:(\{[^}]+?\})", re.IGNORECASE)
_EVAL_PATTERN = re.compile(r"@get:\{[^}]+?\}|\{\{[\w\W]*?\}\}", re.IGNORECASE)
_REGEX_PATTERN = re.compile(r"\$\d{1,2}")


class Mode(Enum):
    XPATH = "xpath"
    JSON = "json"
    DEFAULT = "default"
    JS = "js"
    REGEX = "regex"


_GET_RULE_TYPE = -2
_JS_RULE_TYPE = -1
_DEFAULT_RULE_TYPE = 0


def is_json_text(s: str) -> bool:
    t = s.strip()
    if not t or t[0] not in ("{", "["):
        return False
    try:
        json.loads(t)
        return True
    except json.JSONDecodeError:
        return False


@dataclass
class SourceRule:
    """单个规则片段（对照 AnalyzeRule.SourceRule）。"""

    mode: Mode
    rule: str = ""
    replace_regex: str = ""
    replacement: str = ""
    replace_first: bool = False
    put_map: dict[str, str] = field(default_factory=dict)
    _rule_param: list[str] = field(default_factory=list)
    _rule_type: list[int] = field(default_factory=list)
    _made_up: bool = False

    def _add(self, rtype: int, param: str) -> None:
        self._rule_type.append(rtype)
        self._rule_param.append(param)

    def _split_put(self, rule_str: str) -> str:
        for m in _PUT_PATTERN.finditer(rule_str):
            try:
                obj = json.loads(m.group(1))
                if isinstance(obj, dict):
                    self.put_map.update({str(k): str(v) for k, v in obj.items()})
            except json.JSONDecodeError:
                pass
        return _PUT_PATTERN.sub("", rule_str)

    def init_detail(self, rule_str: str, is_json_content: bool) -> None:
        """对照 SourceRule init：模式识别 + put 分离 + @get/{{}}/$N 拆分。"""
        rule = rule_str
        if self.mode == Mode.JS or self.mode == Mode.REGEX:
            pass
        elif rule_str[:5].upper() == "@CSS:":
            self.mode = Mode.DEFAULT
        elif rule_str.startswith("@@"):
            self.mode = Mode.DEFAULT
            rule = rule_str[2:]
        elif rule_str[:7].upper() == "@XPATH:":
            self.mode = Mode.XPATH
            rule = rule_str[7:]
        elif rule_str[:6].upper() == "@JSON:":
            self.mode = Mode.JSON
            rule = rule_str[6:]
        elif is_json_content or rule_str.startswith("$.") or rule_str.startswith("$["):
            self.mode = Mode.JSON
        elif rule_str.startswith("/"):
            self.mode = Mode.XPATH

        rule = self._split_put(rule)

        start = 0
        eval_matcher = _EVAL_PATTERN.search(rule)
        if eval_matcher:
            tmp = rule[: eval_matcher.start()]
            if (
                self.mode not in (Mode.JS, Mode.REGEX)
                and (eval_matcher.start() == 0 or "##" not in tmp)
            ):
                self.mode = Mode.REGEX
            while True:
                if eval_matcher.start() > start:
                    self._split_regex(rule[start : eval_matcher.start()])
                tmp = eval_matcher.group()
                if tmp[:5].upper() == "@GET:":
                    self._add(_GET_RULE_TYPE, tmp[6:-1])
                elif tmp.startswith("{{"):
                    self._add(_JS_RULE_TYPE, tmp[2:-2])
                else:
                    self._split_regex(tmp)
                start = eval_matcher.end()
                eval_matcher = _EVAL_PATTERN.search(rule, start)
                if not eval_matcher:
                    break
        if len(rule) > start:
            self._split_regex(rule[start:])

        self.rule = rule

    def _split_regex(self, rule_str: str) -> None:
        """拆分 $\d{1,2}（对照 splitRegex，含 ## 尾段携带）。"""
        start = 0
        first_segment = rule_str.split("##")[0]
        matched = False
        for m in _REGEX_PATTERN.finditer(first_segment):
            if not matched:
                matched = True
                if self.mode not in (Mode.JS, Mode.REGEX):
                    self.mode = Mode.REGEX
            if m.start() > start:
                self._add(_DEFAULT_RULE_TYPE, rule_str[start : m.start()])
            self._add(int(m.group()[1:]), m.group())
            start = m.end()
        if len(rule_str) > start:
            self._add(_DEFAULT_RULE_TYPE, rule_str[start:])

    def make_up_rule(self, result: Any, host: "AnalyzeRule") -> None:
        """替换 @get/{{}}/$N 并分离 ## 替换段（对照 makeUpRule）。"""
        if self._rule_param and not self._made_up:
            info_val: list[str] = []
            for index in range(len(self._rule_param) - 1, -1, -1):
                rtype = self._rule_type[index]
                if rtype > _DEFAULT_RULE_TYPE:
                    if isinstance(result, list) and len(result) > rtype:
                        item = result[rtype]
                        if item is not None:
                            info_val.insert(0, str(item))
                    else:
                        info_val.insert(0, self._rule_param[index])
                elif rtype == _JS_RULE_TYPE:
                    js_code = self._rule_param[index]
                    if _is_rule(js_code):
                        # Kotlin: getString(List<SourceRule>) 重载——对当前 content 求子规则
                        sub = SourceRule(Mode.DEFAULT)
                        sub.init_detail(js_code, host.is_json)
                        info_val.insert(0, host.get_string_rules([sub]))
                    else:
                        js_eval = host.eval_js(js_code, result)
                        if js_eval is None:
                            continue
                        if isinstance(js_eval, str):
                            info_val.insert(0, js_eval)
                        elif isinstance(js_eval, float) and js_eval % 1.0 == 0.0:
                            info_val.insert(0, f"{js_eval:.0f}")
                        else:
                            info_val.insert(0, str(js_eval))
                elif rtype == _GET_RULE_TYPE:
                    info_val.insert(0, host.get(self._rule_param[index]))
                else:
                    info_val.insert(0, self._rule_param[index])
            self.rule = "".join(info_val)
            self._made_up = True

        parts = self.rule.split("##")
        self.rule = parts[0].strip()
        if len(parts) > 1:
            self.replace_regex = parts[1]
        if len(parts) > 2:
            self.replacement = parts[2]
        if len(parts) > 3:
            self.replace_first = True


def _js_safe(v):
    """pydantic 模型 → dict（quickjs 只认 JSON 类型，模型会被降级成字符串）。"""
    if hasattr(v, "model_dump"):
        try:
            return v.model_dump()
        except Exception:
            return str(v)
    return v


def _is_rule(rule_str: str) -> bool:
    return (
        rule_str.startswith("@")
        or rule_str.startswith("$.")
        or rule_str.startswith("$[")
        or rule_str.startswith("//")
    )


class AnalyzeRule:
    def __init__(
        self,
        rule_data: RuleData,
        source=None,
        js_engine: JsEngine | None = None,
        http_client=None,
        cookie_store=None,
    ) -> None:
        self.rule_data = rule_data
        self.source = source
        self.js_engine: JsEngine = js_engine or NullEngine()
        # 供 JS 桥（java.ajax 等）使用
        self.http_client = http_client
        self.cookie_store = cookie_store
        self.chapter: RuleData | None = None
        self.next_chapter_url: str | None = None
        self.content: Any = None
        self.base_url: str | None = None
        self.redirect_url: str | None = None
        self.is_json = False
        self.is_regex = False

        self._analyzer_jsoup: AnalyzeByJsoup | None = None
        self._analyzer_json: AnalyzeByJsonPath | None = None
        self._analyzer_xpath: AnalyzeByXPath | None = None
        self._changed_jsoup = True
        self._changed_json = True
        self._changed_xpath = True

    # ---- 内容与上下文 ----

    @property
    def book(self):
        """对照 Kotlin val book get() = ruleData as? BaseBook。"""
        return self.rule_data if self.rule_data is not None else None

    def set_content(self, content: Any, base_url: str | None = None) -> "AnalyzeRule":
        if content is None:
            raise AssertionError("内容不可空（Content cannot be null）")
        self.content = content
        self.is_json = isinstance(content, str) and is_json_text(content)
        if base_url:
            self.base_url = base_url
        self._changed_xpath = True
        self._changed_jsoup = True
        self._changed_json = True
        return self

    def set_redirect_url(self, url: str) -> str | None:
        self.redirect_url = url
        return url

    def _get_jsoup(self, o: Any) -> AnalyzeByJsoup:
        if o is not self.content:
            return AnalyzeByJsoup(o)
        if self._analyzer_jsoup is None or self._changed_jsoup:
            self._analyzer_jsoup = AnalyzeByJsoup(self.content)
            self._changed_jsoup = False
        return self._analyzer_jsoup

    def _get_json(self, o: Any) -> AnalyzeByJsonPath:
        if o is not self.content:
            return AnalyzeByJsonPath(o)
        if self._analyzer_json is None or self._changed_json:
            self._analyzer_json = AnalyzeByJsonPath(self.content)
            self._changed_json = False
        return self._analyzer_json

    def _get_xpath(self, o: Any) -> AnalyzeByXPath:
        if o is not self.content:
            return AnalyzeByXPath(o)
        if self._analyzer_xpath is None or self._changed_xpath:
            self._analyzer_xpath = AnalyzeByXPath(self.content)
            self._changed_xpath = False
        return self._analyzer_xpath

    # ---- 变量 ----

    def put(self, key: str, value: str) -> str:
        target = self.chapter or self.book or self.rule_data
        if target is not None:
            target.put_variable(key, value)
        return value

    def get(self, key: str) -> str:
        if key == "bookName" and self.book is not None:
            return getattr(self.book, "name", "") or ""
        if key == "title" and self.chapter is not None:
            return getattr(self.chapter, "title", "") or ""
        v = None
        if self.chapter is not None:
            v = self.chapter.get_variable(key)
        if v is None and self.book is not None:
            v = self.book.get_variable(key)
        if v is None:
            v = self.rule_data.get_variable(key)
        return v or ""

    def eval_js(self, js_str: str, result: Any = None) -> Any:
        bindings: dict[str, Any] = {
            "java": self,
            "cookie": None,
            "cache": None,
            "source": _js_safe(self.source),
            "book": _js_safe(self.book),
            "result": result,
            "baseUrl": self.base_url,
            "chapter": _js_safe(self.chapter),
            "title": getattr(self.chapter, "title", None) if self.chapter else None,
            "src": self.content,
            "nextChapterUrl": self.next_chapter_url,
        }
        return self.js_engine.eval(js_str, bindings, host=self)

    # ---- 规则切分 ----

    def split_source_rule(self, rule_str: str | None, all_in_one: bool = False) -> list[SourceRule]:
        if not rule_str:
            return []
        rule_list: list[SourceRule] = []
        mode = Mode.REGEX if self.is_regex else Mode.DEFAULT
        start = 0
        if all_in_one and rule_str.startswith(":"):
            mode = Mode.REGEX
            self.is_regex = True
            start = 1
        for m in JS_PATTERN.finditer(rule_str):
            if m.start() > start:
                tmp = rule_str[start : m.start()].strip()
                if tmp:
                    rule_list.append(self._new_rule(tmp, mode))
            rule_list.append(self._new_rule(m.group(2) or m.group(1), Mode.JS))
            start = m.end()
        if len(rule_str) > start:
            tmp = rule_str[start:].strip()
            if tmp:
                rule_list.append(self._new_rule(tmp, mode))
        return rule_list

    def _new_rule(self, rule_str: str, mode: Mode) -> SourceRule:
        rule = SourceRule(mode=mode)
        rule.init_detail(rule_str, self.is_json)
        return rule

    # ---- 主入口 ----

    def get_string(self, rule_str: str | None, m_content: Any = None, is_url: bool = False) -> str:
        if not rule_str:
            return ""
        rule_list = self.split_source_rule(rule_str)
        return self.get_string_rules(rule_list, m_content, is_url)

    def get_string_rules(
        self, rule_list: list[SourceRule], m_content: Any = None, is_url: bool = False
    ) -> str:
        result: Any = None
        content = m_content if m_content is not None else self.content
        if content is not None and rule_list:
            result = content
            # 对照 Kotlin NativeObject 分支：dict/JS 对象——$./$[ 开头走 JSONPath，否则直取键
            if isinstance(content, dict):
                first = rule_list[0]
                first.make_up_rule(content, self)
                if first.mode == Mode.JSON or first.rule.startswith(("$.", "$[")):
                    if first.mode != Mode.JSON:
                        first.mode = Mode.JSON
                    result = self._get_json(content).get_string(first.rule)
                else:
                    result = content.get(first.rule)
                for extra in rule_list[1:]:
                    if result is None:
                        break
                    if extra.mode == Mode.JS:
                        result = self.eval_js(extra.rule, result)
                    else:
                        result = str(extra.rule)
                if result is not None and first.replace_regex:
                    result = self._replace_regex(str(result), first)
                return str(result) if result is not None else ""
            for source_rule in rule_list:
                self._put_rule(source_rule.put_map)
                source_rule.make_up_rule(result, self)
                if result is not None and (
                    source_rule.rule.strip() or not source_rule.replace_regex
                ):
                    if source_rule.mode == Mode.JS:
                        result = self.eval_js(source_rule.rule, result)
                    elif source_rule.mode == Mode.JSON:
                        result = self._get_json(result).get_string(source_rule.rule)
                    elif source_rule.mode == Mode.XPATH:
                        result = self._get_xpath(result).get_string(source_rule.rule)
                    elif source_rule.mode == Mode.DEFAULT:
                        analyzer = self._get_jsoup(result)
                        if is_url:
                            result = analyzer.get_string0(source_rule.rule)
                        else:
                            result = analyzer.get_string(source_rule.rule)
                    else:  # REGEX：重建后的字面量
                        result = source_rule.rule
                if result is not None and source_rule.replace_regex:
                    result = self._replace_regex(str(result), source_rule)
        if result is None:
            result = ""
        try:
            string = html.unescape(str(result))
        except Exception:
            string = str(result)
        if is_url:
            if not string.strip():
                return self.base_url or ""
            return get_absolute_url(self.redirect_url or self.base_url, string)
        return string

    def get_string_list(self, rule_str: str | None, m_content: Any = None, is_url: bool = False):
        if not rule_str:
            return None
        rule_list = self.split_source_rule(rule_str, False)
        return self.get_string_list_rules(rule_list, m_content, is_url)

    def get_string_list_rules(
        self, rule_list: list[SourceRule], m_content: Any = None, is_url: bool = False
    ) -> list[str] | None:
        result: Any = None
        content = m_content if m_content is not None else self.content
        if content is not None and rule_list:
            result = content
            if isinstance(content, dict):
                first = rule_list[0]
                first.make_up_rule(content, self)
                if first.mode == Mode.JSON or first.rule.startswith(("$.", "$[")):
                    if first.mode != Mode.JSON:
                        first.mode = Mode.JSON
                    result = self._get_json(content).get_string_list(first.rule)
                else:
                    result = [str(content.get(first.rule) or "")]
                for extra in rule_list[1:]:
                    if result is None:
                        break
                    if extra.mode == Mode.JS:
                        result = self.eval_js(extra.rule, result)
                    else:
                        result = str(extra.rule)
                if result and first.replace_regex:
                    result = [self._replace_regex(str(item), first) for item in result]
                return [str(r) if r is not None else "" for r in (result or [])]
            for source_rule in rule_list:
                self._put_rule(source_rule.put_map)
                source_rule.make_up_rule(result, self)
                if result is not None and source_rule.rule:
                    if source_rule.mode == Mode.JS:
                        result = self.eval_js(source_rule.rule, result)
                    elif source_rule.mode == Mode.JSON:
                        result = self._get_json(result).get_string_list(source_rule.rule)
                    elif source_rule.mode == Mode.XPATH:
                        result = self._get_xpath(result).get_string_list(source_rule.rule)
                    elif source_rule.mode == Mode.DEFAULT:
                        result = self._get_jsoup(result).get_string_list(source_rule.rule)
                    else:
                        result = source_rule.rule
                if (
                    result is not None
                    and source_rule.replace_regex
                ):
                    if isinstance(result, list):
                        result = [
                            self._replace_regex(str(item), source_rule) for item in result
                        ]
                    else:
                        result = self._replace_regex(str(result), source_rule)
        if result is None:
            return None
        if isinstance(result, str):
            result = result.split("\n")
        if is_url and isinstance(result, list):
            url_list: list[str] = []
            for url in result:
                absolute = get_absolute_url(self.redirect_url or self.base_url, str(url))
                if absolute and absolute not in url_list:
                    url_list.append(absolute)
            return url_list
        return result if isinstance(result, list) else None

    def get_element(self, rule_str: str) -> Any:
        if not rule_str:
            return None
        result: Any = None
        content = self.content
        rule_list = self.split_source_rule(rule_str, True)
        if content is not None and rule_list:
            result = content
            for source_rule in rule_list:
                self._put_rule(source_rule.put_map)
                source_rule.make_up_rule(result, self)
                if result is not None:
                    if source_rule.mode == Mode.REGEX:
                        regs = [r for r in source_rule.rule.split("&&") if r.strip()]
                        result = analyze_regex.get_element(str(result), regs)
                    elif source_rule.mode == Mode.JS:
                        result = self.eval_js(source_rule.rule, result)
                    elif source_rule.mode == Mode.JSON:
                        result = self._get_json(result).get_object(source_rule.rule)
                    elif source_rule.mode == Mode.XPATH:
                        result = self._get_xpath(result).get_elements(source_rule.rule)
                    else:
                        result = self._get_jsoup(result).get_elements(source_rule.rule)
                    if source_rule.replace_regex:
                        result = self._replace_regex(str(result), source_rule)
        return result

    def get_elements(self, rule_str: str) -> list[Any]:
        result: Any = None
        content = self.content
        rule_list = self.split_source_rule(rule_str, True)
        if content is not None and rule_list:
            result = content
            for source_rule in rule_list:
                self._put_rule(source_rule.put_map)
                if source_rule.mode == Mode.REGEX:
                    regs = [r for r in source_rule.rule.split("&&") if r.strip()]
                    result = analyze_regex.get_elements(str(result), regs)
                elif source_rule.mode == Mode.JS:
                    result = self.eval_js(source_rule.rule, result)
                elif source_rule.mode == Mode.JSON:
                    result = self._get_json(result).get_list(source_rule.rule)
                elif source_rule.mode == Mode.XPATH:
                    result = self._get_xpath(result).get_elements(source_rule.rule)
                else:
                    result = self._get_jsoup(result).get_elements(source_rule.rule)
                if result is not None and source_rule.replace_regex:
                    result = self._replace_regex(str(result), source_rule)
        if result is None:
            return []
        return list(result) if isinstance(result, (list, tuple)) else [result]

    # ---- 内部 ----

    def _put_rule(self, put_map: dict[str, str]) -> None:
        for key, value in put_map.items():
            self.put(key, self.get_string(value))

    def _replace_regex(self, result: str, rule: SourceRule) -> str:
        """Java 正则替换语义（$1 组引用），失败回退字面替换（对照 replaceRegex）。"""
        if not rule.replace_regex:
            return result
        try:
            py_re, py_repl = _java_regex_to_py(rule.replace_regex, rule.replacement)
            if rule.replace_first:
                m = re.search(py_re, result)
                if not m:
                    return ""
                first = re.sub(py_re, py_repl, m.group(0), count=1)
                return first
            return re.sub(py_re, py_repl, result)
        except re.error:
            if rule.replace_first:
                return result.replace(rule.replace_regex, rule.replacement, 1)
            return result.replace(rule.replace_regex, rule.replacement)


def _java_regex_to_py(pattern: str, replacement: str) -> tuple[str, str]:
    """Java 替换串的 $N / ${name} 组引用转 Python \\g<N>。"""
    repl = re.sub(r"\$(\{[a-zA-Z0-9_]+\}|\d+)", lambda m: "\\" + m.group(1), replacement)
    return pattern, repl
