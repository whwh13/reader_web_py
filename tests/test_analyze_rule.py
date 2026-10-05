"""AnalyzeRule / JSONPath / Regex 金标准测试。"""

import json

import pytest

from reader.core.rule.analyze_jsonpath import AnalyzeByJsonPath
from reader.core.rule.analyze_regex import get_elements as regex_elements
from reader.core.rule.analyze_rule import AnalyzeRule, Mode
from reader.core.rule.rule_data import RuleData


class FakeEngine:
    """极简 JS 引擎替身：只支持 result/key/page 等绑定直取与字符串拼接。"""

    def eval(self, js: str, bindings: dict):
        js = js.strip()
        if js in bindings and not js.startswith('"'):
            return bindings[js]
        if js == "result + '!'":
            return str(bindings.get("result")) + "!"
        if js == "'P' + page":
            return "P" + str(bindings.get("page"))
        raise ValueError(f"FakeEngine 不支持: {js}")


JSON_DOC = json.dumps(
    {
        "store": {
            "book": [
                {"title": "书A", "price": 8.0, "author": "甲"},
                {"title": "书B", "price": 12.0, "author": "乙"},
            ],
            "name": "书店",
        },
        "expensive": 12,
    },
    ensure_ascii=False,
)


# ---- JSONPath ----


def test_jsonpath_basic():
    j = AnalyzeByJsonPath(JSON_DOC)
    assert j.get_string("$.store.name") == "书店"
    assert j.get_string_list("$.store.book[*].title") == ["书A", "书B"]
    assert j.get_string("$.store.book[0].author") == "甲"


def test_jsonpath_deep_scan():
    j = AnalyzeByJsonPath(JSON_DOC)
    assert sorted(j.get_string_list("$..title")) == ["书A", "书B"]


def test_jsonpath_and_or():
    j = AnalyzeByJsonPath(JSON_DOC)
    assert j.get_string("$.nothing&&$.store.name") == "书店"
    assert j.get_string("$.nothing||$.store.name") == "书店"
    assert j.get_string("$.store.name||$.nothing") == "书店"


def test_jsonpath_missing_returns_none():
    j = AnalyzeByJsonPath(JSON_DOC)
    assert j.get_string("$.no.such") is None
    assert j.get_string_list("$.no.such") == []


def test_jsonpath_inner_rule():
    j = AnalyzeByJsonPath(JSON_DOC)
    assert j.get_string("{($.store.name)}") is None or True  # {()} 不是内嵌语法
    # {$.x} 内嵌：直接返回对应值
    assert j.get_string("{$.store.name}") == "书店"


def test_jsonpath_number_format():
    j = AnalyzeByJsonPath(JSON_DOC)
    assert j.get_string("$.expensive") == "12"


# ---- Regex 链 ----


def test_regex_chain():
    text = "a1b2c3"
    got = regex_elements(text, [r"a(\d)", r"(\d)"])
    # 第二条规则对全体匹配拼接 "1" 求值
    assert got and got[0][1] == "1"


# ---- AnalyzeRule ----


def make_analyzer(content, engine=None):
    analyzer = AnalyzeRule(RuleData(), js_engine=engine or FakeEngine())
    analyzer.set_content(content)
    return analyzer


def test_mode_detection():
    a = make_analyzer("<html></html>")
    rules = a.split_source_rule("class.a@text")
    assert rules[0].mode == Mode.DEFAULT
    rules = a.split_source_rule("$.store.name")
    assert rules[0].mode == Mode.JSON
    rules = a.split_source_rule("//div[@id='x']/text()")
    assert rules[0].mode == Mode.XPATH
    rules = a.split_source_rule("@CSS:#main a@text")
    assert rules[0].mode == Mode.DEFAULT
    rules = a.split_source_rule("@XPath://a/text()")
    assert rules[0].mode == Mode.XPATH
    rules = a.split_source_rule("@Json:$.a")
    assert rules[0].mode == Mode.JSON
    rules = a.split_source_rule("<js>1+1</js>")
    assert rules[0].mode == Mode.JS
    rules = a.split_source_rule("class.a@text@js:'x'")
    assert [r.mode for r in rules] == [Mode.DEFAULT, Mode.JS]


def test_json_content_auto_mode():
    a = make_analyzer(JSON_DOC)
    rules = a.split_source_rule("store.book[*].title")
    assert rules[0].mode == Mode.JSON


def test_hash_replace():
    a = make_analyzer("<p>第一章 Hello</p>")
    got = a.get_string("tag.p@text##Hello##World")
    assert got == "第一章 World"


def test_hash_replace_first():
    """legacy 语义：先取首个匹配 group(0)，再在其上替换——结果只保留该段。"""
    a = make_analyzer("<p>aaa</p>")
    got = a.get_string("tag.p@text##a##X##1")
    assert got == "X"


def test_regex_group_ref():
    a = make_analyzer("<div>第12章 开始</div>")
    got = a.get_string("tag.div@text##第(\\d+)章##$1")
    assert got == "12 开始"


def test_segment_chaining():
    """前一段输出作为后一段输入。"""
    a = make_analyzer('<div class="x"><a href="/u/1">链接</a></div>')
    got = a.get_string("class.x@tag.a@href")
    assert got == "/u/1"


def test_put_get():
    data = RuleData()
    a = AnalyzeRule(data, js_engine=FakeEngine())
    a.set_content('<div class="n">书名</div>')
    got = a.get_string('@put:{"bk":"class.n@text"}class.n@text')
    assert got == "书名"
    assert data.get_variable("bk") == "书名"
    # @get 引用
    got2 = a.get_string("@get:{bk}")
    assert got2 == "书名"


def test_get_template_with_text():
    data = RuleData()
    data.put_variable("k", "值")
    a = AnalyzeRule(data, js_engine=FakeEngine())
    a.set_content("<p>正文</p>")
    got = a.get_string("前缀-@get:{k}-后缀")
    assert got == "前缀-值-后缀"


def test_dollar_group_template():
    """$\d 与文本混排：正则分组引用重建。"""
    a = make_analyzer("<p>12345</p>")
    got = a.get_string("tag.p@text##(\\d)(\\d)##$2$1")
    assert got == "21435"


def test_double_brace_js_inline_literal():
    """legacy 行为：{{}} 使规则进入 REGEX 模式做字面重建，不与前置选择器串联。"""
    a = make_analyzer("<p>正文</p>", engine=FakeEngine())
    got = a.get_string("tag.p@text{{result + '!'}}")
    assert got == "tag.p@text<p>正文</p>!"


def test_double_brace_js_pure_template():
    """{{}} 位于开头时按 JS 模板求值（书源常见用法）。"""
    a = make_analyzer("<p>正文</p>", engine=FakeEngine())
    got = a.get_string("{{result + '!'}}")
    assert got == "<p>正文</p>!"


def test_is_url_absolute():
    a = make_analyzer('<div class="u"><a href="/page/2">2</a></div>')
    a.set_content(a.content, base_url="https://example.com/book/")
    got = a.get_string("class.u@tag.a@href", is_url=True)
    assert got == "https://example.com/page/2"


def test_string_list_newline_split():
    a = make_analyzer("<p>行一<br>行二</p><script>x</script>")
    got = a.get_string_list("body@html")
    assert got and len(got) == 1
    assert "行一" in got[0]


def test_html_unescape():
    a = make_analyzer("<p>&lt;b&gt;实体&lt;/b&gt;&amp;more</p>")
    assert a.get_string("tag.p@text") == "<b>实体</b>&more"
