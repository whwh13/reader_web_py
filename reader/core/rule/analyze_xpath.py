"""XPath 解析（对照 legacy AnalyzeByXPath.kt，JXDocument → lxml）。

- JXNode.asString：元素节点取其全部文本；文本节点取文本值；
- getElements 返回 lxml 元素节点（文本节点降级为字符串），供下游规则继续解析；
- 片段 HTML 自动补 <table>/<tr>（对照 strToJXDocument）。
"""

from __future__ import annotations

from lxml import etree, html as lhtml

from reader.core.rule.rule_analyzer import RuleAnalyzer


def _parse_doc(content) -> lhtml.HtmlElement:
    if isinstance(content, lhtml.HtmlElement):
        return content
    text = content if isinstance(content, str) else str(content)
    if text.rstrip().endswith("</td>"):
        text = f"<tr>{text}</tr>"
    if text.rstrip().endswith(("</tr>", "</tbody>")):
        text = f"<table>{text}</table>"
    return lhtml.document_fromstring(text)


def node_as_string(node) -> str | None:
    """JXNode.asString 等价：元素取全部文本，字符串/文本节点取本身。"""
    if isinstance(node, str):
        return node
    if isinstance(node, lhtml.HtmlElement):
        return node.text_content()
    return str(node) if node is not None else None


class AnalyzeByXPath:
    def __init__(self, doc) -> None:
        if isinstance(doc, lhtml.HtmlElement):
            self.tree = doc
        else:
            self.tree = _parse_doc(doc)

    def _result(self, xpath: str) -> list:
        try:
            return self.tree.xpath(xpath)
        except etree.XPathError:
            return []

    def get_elements(self, xpath: str) -> list:
        if not xpath:
            return None
        analyzer = RuleAnalyzer(xpath)
        rules = analyzer.split_rule("&&", "||", "%%")
        if len(rules) == 1:
            return list(self._result(rules[0]))
        results: list[list] = []
        for rl in rules:
            temp = self.get_elements(rl)
            if temp:
                results.append(temp)
                if analyzer.elements_type == "||":
                    break
        out: list = []
        if results:
            if analyzer.elements_type == "%%":
                for i in range(len(results[0])):
                    for temp in results:
                        if i < len(temp):
                            out.append(temp[i])
            else:
                for temp in results:
                    out.extend(temp)
        return out

    def get_string_list(self, xpath: str) -> list[str]:
        result: list[str] = []
        analyzer = RuleAnalyzer(xpath)
        rules = analyzer.split_rule("&&", "||", "%%")
        if len(rules) == 1:
            for n in self._result(rules[0]):
                s = node_as_string(n)
                if s is not None:
                    result.append(s)
            return result
        results: list[list[str]] = []
        for rl in rules:
            temp = self.get_string_list(rl)
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

    def get_string(self, rule: str) -> str | None:
        analyzer = RuleAnalyzer(rule)
        rules = analyzer.split_rule("&&", "||")
        if len(rules) == 1:
            found = self._result(rules[0])
            texts = [s for s in (node_as_string(n) for n in found) if s is not None]
            return "\n".join(texts) if texts else None
        texts: list[str] = []
        for rl in rules:
            temp = self.get_string(rl)
            if temp:
                texts.append(temp)
                if analyzer.elements_type == "||":
                    break
        return "\n".join(texts)
