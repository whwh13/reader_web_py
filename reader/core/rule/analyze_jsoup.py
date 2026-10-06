"""JSOUP 式规则解析（对照 legacy AnalyzeByJSoup.kt）。

规则形态：`@` 链逐层选元素，末段为取值器（text/textNodes/ownText/html/all/attr）；
`&&`/`||`/`%%` 组合多规则；索引筛选语法见 _ElementsSingle。
"""

from __future__ import annotations

from lxml import html as lhtml

from reader.core.rule import jsoup_compat as jc
from reader.core.rule.rule_analyzer import RuleAnalyzer


class _SourceRule:
    def __init__(self, rule_str: str) -> None:
        self.is_css = False
        if rule_str.upper().startswith("@CSS:"):
            self.is_css = True
            self.elements_rule = rule_str[5:].strip()
        else:
            self.elements_rule = rule_str


class AnalyzeByJsoup:
    def __init__(self, doc) -> None:
        if isinstance(doc, lhtml.HtmlElement):
            self.element = doc
        else:
            self.element = jc.parse_html(str(doc))

    # ---- 字符串 ----

    def get_string(self, rule_str: str) -> str | None:
        """内容列表 \n 连接。"""
        if not rule_str:
            return None
        texts = self.get_string_list(rule_str)
        return "\n".join(texts) if texts else None

    def get_string0(self, rule_str: str) -> str:
        """取第一个字符串（URL 模式用）。"""
        texts = self.get_string_list(rule_str)
        return texts[0] if texts else ""

    def get_string_list(self, rule_str: str) -> list[str]:
        texts: list[str] = []
        if not rule_str:
            return texts
        source_rule = _SourceRule(rule_str)
        if not source_rule.elements_rule:
            texts.append(jc.element_data(self.element))
            return texts

        analyzer = RuleAnalyzer(source_rule.elements_rule)
        rules = analyzer.split_rule("&&", "||", "%%")
        results: list[list[str]] = []
        for rule_x in rules:
            if source_rule.is_css:
                at = rule_x.rfind("@")
                if at == -1:
                    continue
                selected = jc.select_strict(self.element, rule_x[:at])
                temp = self._result_last(list(selected), rule_x[at + 1 :])
            else:
                temp = self._result_list(rule_x)
            if temp:
                results.append(temp)
                if analyzer.elements_type == "||":
                    break
        if results:
            if analyzer.elements_type == "%%":
                for i in range(len(results[0])):
                    for temp in results:
                        if i < len(temp):
                            texts.append(temp[i])
            else:
                for temp in results:
                    texts.extend(temp)
        return texts

    # ---- 元素列表 ----

    def get_elements(self, rule: str) -> list[lhtml.HtmlElement]:
        return self._get_elements(self.element, rule)

    def _get_elements(self, temp: lhtml.HtmlElement | None, rule: str) -> list[lhtml.HtmlElement]:
        if temp is None or not rule:
            return []

        source_rule = _SourceRule(rule)
        analyzer = RuleAnalyzer(source_rule.elements_rule)
        rules = analyzer.split_rule("&&", "||", "%%")

        elements_list: list[list[lhtml.HtmlElement]] = []
        if source_rule.is_css:
            for rule_str in rules:
                temp_s = list(jc.select_strict(temp, rule_str))
                elements_list.append(temp_s)
                if temp_s and analyzer.elements_type == "||":
                    break
        else:
            for rule_str in rules:
                rs = RuleAnalyzer(rule_str)
                rs.trim()
                segments = rs.split_rule("@")
                if len(segments) > 1:
                    el: list[lhtml.HtmlElement] = [temp]
                    for rl in segments:
                        es: list[lhtml.HtmlElement] = []
                        for et in el:
                            es.extend(self._get_elements(et, rl))
                        el = es
                    elements_list.append(el)
                else:
                    elements_list.append(
                        _ElementsSingle().get_elements_single(temp, rule_str)
                    )
        elements: list[lhtml.HtmlElement] = []
        if elements_list:
            if analyzer.elements_type == "%%":
                for i in range(len(elements_list[0])):
                    for es in elements_list:
                        if i < len(es):
                            elements.append(es[i])
            else:
                for es in elements_list:
                    elements.extend(es)
        return elements

    # ---- 内部 ----

    def _result_list(self, rule_str: str) -> list[str] | None:
        if not rule_str:
            return None
        elements: list[lhtml.HtmlElement] = [self.element]
        rule = RuleAnalyzer(rule_str)
        rule.trim()
        rules = rule.split_rule("@")
        for seg in rules[:-1]:
            es: list[lhtml.HtmlElement] = []
            for elt in elements:
                es.extend(_ElementsSingle().get_elements_single(elt, seg))
            elements = es
        if not elements:
            return None
        return self._result_last(elements, rules[-1])

    def _result_last(self, elements: list[lhtml.HtmlElement], last_rule: str) -> list[str]:
        texts: list[str] = []
        if last_rule == "text":
            for el in elements:
                text = jc.element_text(el)
                if text:
                    texts.append(text)
        elif last_rule == "textNodes":
            for el in elements:
                tn = jc.element_text_nodes(el)
                if tn:
                    texts.append("\n".join(tn))
        elif last_rule == "ownText":
            for el in elements:
                text = jc.element_own_text(el)
                if text:
                    texts.append(text)
        elif last_rule == "html":
            cleaned: list[str] = []
            for el in elements:
                to_remove = [
                    n for n in el.iter() if isinstance(n.tag, str) and n.tag in ("script", "style")
                ]
                for n in to_remove:
                    parent = n.getparent()
                    if parent is None:
                        continue
                    # jsoup 的 DOM 里标签间文本是兄弟 TextNode；lxml 挂在 tail 上，
                    # 删节点前先把 tail 文本并回去，否则正交内容会一起丢失
                    tail = n.tail
                    if tail:
                        prev = n.getprevious()
                        if prev is not None:
                            prev.tail = (prev.tail or "") + tail
                        else:
                            parent.text = (parent.text or "") + tail
                    parent.remove(n)
                html = jc.outer_html(el)
                if html:
                    cleaned.append(html)
            texts.extend(cleaned)
        elif last_rule == "all":
            texts.append("".join(jc.outer_html(el) for el in elements))
        else:
            for el in elements:
                url = el.get(last_rule) or ""
                if not url.strip() or url in texts:
                    continue
                texts.append(url)
        return texts


class _ElementsSingle:
    """单条规则选元素，支持两种索引语法（对照 ElementsSingle）。

    1. 阅读原写法：`tag.div.-1:10:2` / `tag.div!0:3`（'.' 选择 '!' 排除，':' 为区间）
    2. jsonPath 风格：`tag.div[-1, 3:-2:-10, 2]`（`[!` 开头为排除；区间 start:end[:step]）

    索引按规则串中的书写顺序生效（解析自右向左，取值时还原）。
    """

    def __init__(self) -> None:
        self.split_char = "."
        self.before_rule = ""
        self.index_default: list[int] = []
        self.indexes: list[int | tuple[int | None, int | None, int]] = []

    def get_elements_single(self, temp: lhtml.HtmlElement, rule: str) -> list[lhtml.HtmlElement]:
        self._find_index_set(rule)

        if not self.before_rule:
            elements = list(temp)
        else:
            rules = self.before_rule.split(".")
            head = rules[0]
            if len(rules) < 2:
                elements = list(jc.select_strict(temp, self.before_rule))
            elif head == "children":
                elements = list(temp)
            elif head == "class":
                elements = jc.get_elements_by_class(temp, rules[1])
            elif head == "tag":
                elements = jc.get_elements_by_tag(temp, rules[1])
            elif head == "id":
                elements = jc.get_elements_by_id(temp, rules[1])
            elif head == "text":
                elements = jc.get_elements_containing_own_text(temp, rules[1])
            else:
                elements = list(jc.select_strict(temp, self.before_rule))

        length = len(elements)
        last = len(self.index_default) - 1 if self.index_default else len(self.indexes) - 1
        # Kotlin 用 LinkedHashSet：保持索引在规则串中的书写顺序，dict 键模拟
        index_set: dict[int, None] = {}

        if not self.indexes:
            for ix in range(last, -1, -1):
                it = self.index_default[ix]
                if 0 <= it < length:
                    index_set[it] = None
                elif it < 0 and length >= -it:
                    index_set[it + length] = None
        else:
            for ix in range(last, -1, -1):
                item = self.indexes[ix]
                if isinstance(item, tuple):
                    start_x, end_x, step_x = item
                    start = self._clamp(start_x, length, default=0)
                    end = self._clamp(end_x, length, default=length - 1)
                    if start == end or step_x >= length:
                        index_set[start] = None
                        continue
                    step = step_x if step_x > 0 else (step_x + length if -step_x < length else 1)
                    if end > start:
                        index_set.update(dict.fromkeys(range(start, end + 1, step)))
                    else:
                        index_set.update(dict.fromkeys(range(start, end - 1, -step)))
                else:
                    it = item
                    if 0 <= it < length:
                        index_set[it] = None
                    elif it < 0 and length >= -it:
                        index_set[it + length] = None

        if self.split_char == "!":
            return [e for i, e in enumerate(elements) if i not in index_set]
        if self.split_char == ".":
            return [elements[i] for i in index_set]
        return elements

    @staticmethod
    def _clamp(value: int | None, length: int, default: int) -> int:
        if value is None:
            return default
        if value >= 0:
            return value if value < length else length - 1
        if -value <= length:
            return length + value
        return 0

    def _find_index_set(self, rule: str) -> None:
        """自右向左解析索引结构（对照 findIndexSet，i 为当前字符下标）。"""
        rus = rule.strip()
        self.index_default = []
        self.indexes = []
        self.split_char = "."
        self.before_rule = ""
        if not rus:
            return

        digits = ""
        cur_minus = False
        cur_list: list[int | None] = []

        def take_int() -> int | None:
            if not digits:
                return None
            return -int(digits) if cur_minus else int(digits)

        if rus[-1] == "]":
            # jsonPath 风格 [...]：i 从 ']' 前一个字符开始向左
            i = len(rus) - 2
            while i >= 0:
                rl = rus[i]
                if rl == " ":
                    i -= 1
                    continue
                if rl.isdigit():
                    digits = rl + digits
                    i -= 1
                    continue
                if rl == "-":
                    cur_minus = True
                    i -= 1
                    continue
                cur_int = take_int()
                if rl == ":":
                    cur_list.append(cur_int)
                else:
                    if not cur_list:
                        if cur_int is None:
                            break  # 不是索引列表，是普通选择器
                        self.indexes.append(cur_int)
                    else:
                        self.indexes.append(
                            (cur_int, cur_list[-1], cur_list[0] if len(cur_list) == 2 else 1)
                        )
                        cur_list.clear()
                    if rl == "!":
                        self.split_char = "!"
                        i -= 1
                        while i > 0 and rus[i] == " ":
                            i -= 1
                    if rl == "[":
                        self.before_rule = rus[:i]
                        return
                    if rl != ",":
                        break
                digits = ""
                cur_minus = False
                i -= 1
        else:
            # 阅读原写法：i 从最后一个字符开始向左
            i = len(rus) - 1
            while i >= 0:
                rl = rus[i]
                if rl == " ":
                    i -= 1
                    continue
                if rl.isdigit():
                    digits = rl + digits
                    i -= 1
                    continue
                if rl == "-":
                    cur_minus = True
                    i -= 1
                    continue
                if rl in ("!", ".", ":"):
                    self.index_default.append(take_int() or 0)
                    if rl != ":":
                        self.split_char = rl
                        self.before_rule = rus[:i]
                        return
                else:
                    break
                digits = ""
                cur_minus = False
                i -= 1

        # 循环自然结束（未构成索引结构）：整体按选择器处理
        self.split_char = " "
        self.before_rule = rus
