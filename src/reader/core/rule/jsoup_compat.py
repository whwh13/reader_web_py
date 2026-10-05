"""jsoup 语义的 lxml 工具（对照 AnalyzeByJSoup 依赖的 jsoup API）。

jsoup 的 DOM 把标签间文本作为父元素的 TextNode 子节点，lxml 则挂在
child.tail 上——text/ownText/textNodes 的实现据此对齐。
"""

from __future__ import annotations

import re

from lxml import html as lhtml

_WS = re.compile(r"\s+")


def norm_space(s: str | None) -> str:
    return _WS.sub(" ", s or "").strip()


def parse_html(content) -> lhtml.HtmlElement:
    """对照 jsoup.parse：总是返回完整 <html> 根。"""
    if isinstance(content, lhtml.HtmlElement):
        return content
    text = content if isinstance(content, str) else str(content)
    return lhtml.document_fromstring(text)


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
    return el.cssselect(css)


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
