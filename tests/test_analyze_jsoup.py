"""JSOUP 式解析器金标准测试（行为对照 legacy AnalyzeByJSoup + jsoup 语义）。"""

from reader.core.rule.analyze_jsoup import AnalyzeByJsoup

HTML = """
<html><body>
<div id="main">
  <div class="bookbox" id="b1"><h4><a href="/book/1">书名一</a></h4>
    <span class="author">作者A</span><span class="intro">简介<b>一</b></span>
    <p class="line">行1</p><p class="line">行2</p></div>
  <div class="bookbox" id="b2"><h4><a href="/book/2">书名二</a></h4>
    <span class="author">作者B</span><span class="intro">简介二</span>
    <p class="line">行3</p><p class="line">行4</p></div>
  <div class="bookbox" id="b3"><h4><a href="/book/3">书名三</a></h4>
    <span class="author">作者C</span></div>
</div>
</body></html>
"""


def make():
    return AnalyzeByJsoup(HTML)


def test_element_chain_text():
    s = make()
    assert s.get_string_list("class.bookbox@tag.h4@tag.a@text") == ["书名一", "书名二", "书名三"]


def test_attr_dedupe():
    s = make()
    assert s.get_string_list("class.bookbox@tag.a@href") == ["/book/1", "/book/2", "/book/3"]


def test_index_select():
    s = make()
    assert s.get_string_list("class.bookbox.0@tag.a@text") == ["书名一"]
    assert s.get_string_list("class.bookbox.-1@tag.a@text") == ["书名三"]
    # legacy 原写法中 ':' 分隔的每个数字都是独立索引（非区间）
    assert s.get_string_list("class.bookbox.0:2@tag.a@text") == ["书名一", "书名三"]
    assert s.get_string_list("class.bookbox.1@tag.a@text") == ["书名二"]


def test_index_exclude():
    s = make()
    assert s.get_string_list("class.bookbox!1@tag.a@text") == ["书名一", "书名三"]


def test_bracket_index():
    s = make()
    assert s.get_string_list("class.bookbox[0]@tag.a@text") == ["书名一"]
    assert s.get_string_list("class.bookbox[2,0]@tag.a@text") == ["书名三", "书名一"]
    assert s.get_string_list("class.bookbox[-1]@tag.a@text") == ["书名三"]


def test_and_combine():
    s = make()
    got = s.get_string_list("class.author@text&&class.line.0:2@text")
    # && 顺序拼接两个规则的结果
    # ':' 分隔的数字是独立索引：0:2 → 第 0、2 个元素
    assert got == ["作者A", "作者B", "作者C", "行1", "行3"]


def test_or_combine_first_non_empty():
    s = make()
    got = s.get_string_list("class.none@text||class.author@text")
    assert got == ["作者A", "作者B", "作者C"]


def test_css_prefix():
    s = make()
    got = s.get_string_list("@CSS:#main .bookbox h4 a@text")
    assert got == ["书名一", "书名二", "书名三"]


def test_own_text():
    s = make()
    got = s.get_string_list("class.bookbox.0@class.intro@ownText")
    assert got == ["简介"]  # 不含 <b>一</b> 的子文本


def test_text_nodes():
    s = make()
    got = s.get_string_list("class.bookbox.0@class.intro@textNodes")
    assert got == ["简介"]


def test_html_removes_script():
    html = '<div class="c"><script>x=1</script>内容</div>'
    s = AnalyzeByJsoup(html)
    got = s.get_string_list("class.c@html")
    assert len(got) == 1
    assert "script" not in got[0]
    assert "内容" in got[0]


def test_all_keeps_script():
    html = '<div class="c"><script>x=1</script>内容</div>'
    s = AnalyzeByJsoup(html)
    got = s.get_string_list("class.c@all")
    assert "script" in got[0]


def test_text_of_intro_includes_children():
    s = make()
    got = s.get_string_list("class.bookbox.0@class.intro@text")
    assert got == ["简介 一"]


def test_elements_chain():
    s = make()
    els = s.get_elements("class.bookbox.0:2")
    assert len(els) == 2
    # 元素继续作为内容解析
    sub = AnalyzeByJsoup(els[0])
    assert sub.get_string("tag.a@text") == "书名一"
