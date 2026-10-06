"""jsoup 语义的 lxml 工具（对照 AnalyzeByJSoup 依赖的 jsoup API）。

jsoup 的 DOM 把标签间文本作为父元素的 TextNode 子节点，lxml 则挂在
child.tail 上——text/ownText/textNodes 的实现据此对齐。
"""

from __future__ import annotations

import re

from lxml import etree, html as lhtml

_WS = re.compile(r"\s+")


def norm_space(s: str | None) -> str:
    return _WS.sub(" ", s or "").strip()


def parse_html(content) -> lhtml.HtmlElement:
    """对照 jsoup.parse：总是返回完整 <html> 根。

    libxml2 不自动创建 <tbody>（HTML5/jsoup 会），导致书源里大量
    'tbody xxx' 选择器失配——解析后按 HTML5 语义补齐。
    """
    if isinstance(content, lhtml.HtmlElement):
        el = content
    else:
        text = content if isinstance(content, str) else str(content)
        el = lhtml.document_fromstring(text)
    _normalize_table(el)
    return el


def _normalize_table(tree) -> None:
    """HTML5 表格语义补齐：table 补 tbody 包裹 tr；非行子元素 foster-parent 出 table。"""
    for table in tree.iter("table"):
        if not isinstance(table.tag, str):
            continue
        rows = [c for c in table if isinstance(c.tag, str) and c.tag == "tr"]
        others = [
            c for c in table
            if isinstance(c.tag, str)
            and c.tag not in ("tr", "tbody", "thead", "tfoot", "caption", "colgroup")
        ]
        if others:
            # jsoup：table 的非行子元素 foster-parent 到 table 之前
            parent = table.getparent()
            anchor = table
            for child_el in others:
                table.remove(child_el)
                if parent is not None:
                    anchor.addnext(child_el)
                    anchor = child_el
        if rows:
            tbody = etree.Element("tbody")
            table.insert(0, tbody)
            for tr in rows:
                table.remove(tr)
                tbody.append(tr)


def element_text(el: lhtml.HtmlElement) -> str:
    """Element.text()：后代全部文本，空白归一，节点间以空格连接。"""
    parts = [p for t in el.itertext() if (p := norm_space(t))]
    return " ".join(parts)


def element_own_text(el: lhtml.HtmlElement) -> str:
    """Element.ownText()：仅直属文本节点（el.text 与孩子的 tail）。"""
    pieces = [el.text or ""] + [c.tail or "" for c in el]
    parts = [p for t in pieces if (p := norm_space(t))]
    return " ".join(parts)


def element_text_nodes(el: lhtml.HtmlElement) -> list[str]:
    """Element.textNodes()：直属文本节点，逐个 trim。"""
    pieces = [el.text or ""] + [c.tail or "" for c in el]
    return [norm_space(t) for t in pieces if norm_space(t)]


def element_data(el: lhtml.HtmlElement) -> str:
    """Element.data()：script/style 数据节点文本。"""
    parts: list[str] = []
    for child in el.iter():
        tag = child.tag if isinstance(child.tag, str) else ""
        if tag in ("script", "style") and child.text:
            parts.append(child.text)
    return "\n".join(parts)


def outer_html(el: lhtml.HtmlElement) -> str:
    return lhtml.tostring(el, encoding="unicode")


def select(el: lhtml.HtmlElement, css: str) -> list[lhtml.HtmlElement]:
    """Element.select(CSS)。cssselect 不支持的选择器返回空列表（宽松）。"""
    try:
        return el.cssselect(css)
    except Exception:
        return []


def select_strict(el: lhtml.HtmlElement, css: str) -> list[lhtml.HtmlElement]:
    """同 select，但选择器非法时抛错（对齐 jsoup 抛 SelectorParseException）。"""
    return el.cssselect(_translate_jsoup_pseudo(css))


_LT_GT = re.compile(r":(lt|gt)\((\d+)\)")


def _translate_jsoup_pseudo(css: str) -> str:
    """jsoup 的 :lt(n)/:gt(n) → cssselect 的 nth-child（同为兄弟序）。"""

    def repl(m: re.Match) -> str:
        n = int(m.group(2))
        if m.group(1) == "lt":
            return f":nth-child(-n+{n})"
        return f":nth-child(n+{n + 1})"

    return _LT_GT.sub(repl, css)


def get_elements_by_class(el: lhtml.HtmlElement, name: str) -> list[lhtml.HtmlElement]:
    return el.cssselect(f".{name}")


def get_elements_by_tag(el: lhtml.HtmlElement, name: str) -> list[lhtml.HtmlElement]:
    return el.cssselect(name)


def get_elements_by_id(el: lhtml.HtmlElement, name: str) -> list[lhtml.HtmlElement]:
    return el.cssselect(f"#{name}")


def get_elements_containing_own_text(el: lhtml.HtmlElement, text: str) -> list[lhtml.HtmlElement]:
    """ElementsContainingOwnText：ownText 包含指定文本的所有后代元素。"""
    out: list[lhtml.HtmlElement] = []
    for child in el.iter():
        if isinstance(child.tag, str) and text in element_own_text(child):
            out.append(child)
    return out
