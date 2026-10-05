"""规则切分器金标准测试（行为对照 legacy RuleAnalyzer）。"""

from reader.core.rule.rule_analyzer import RuleAnalyzer, RuleBalanceError


def test_split_and():
    a = RuleAnalyzer("class.a@text&&class.b@text")
    rules = a.split_rule("&&", "||", "%%")
    assert rules == ["class.a@text", "class.b@text"]
    assert a.elements_type == "&&"


def test_split_or():
    a = RuleAnalyzer("tag.div@text||tag.p@text")
    rules = a.split_rule("&&", "||", "%%")
    assert rules == ["tag.div@text", "tag.p@text"]
    assert a.elements_type == "||"


def test_jsonpath_with_logical_operators():
    """jsonPath 内部含 && 时不得误切（code 平衡组，[] 内跳过分隔符）。"""
    a = RuleAnalyzer("$.store[?(@.price<10 && @.price>5)].book", code=True)
    rules = a.split_rule("&&", "||")
    assert len(rules) == 1
    assert rules[0] == "$.store[?(@.price<10 && @.price>5)].book"


def test_filter_brackets_protection():
    """[...] 筛选器内出现的 && 不切割。"""
    a = RuleAnalyzer("tag.div[0:2]&&tag.p")
    rules = a.split_rule("&&", "||", "%%")
    assert rules == ["tag.div[0:2]", "tag.p"]


def test_quotes_containing_separator():
    """legacy 仅保护 [...]/(...) 筛选器；无括号时引号内的 && 同样会被切（保持一致）。"""
    rule = r'class.a@text##"&&"##X&&tag.p'
    a = RuleAnalyzer(rule)
    rules = a.split_rule("&&", "||", "%%")
    assert rules == [r'class.a@text##"', '"##X', "tag.p"]


def test_single_split_at():
    a = RuleAnalyzer("class.bookbox@tag.h4@tag.a@text")
    rules = a.split_rule("@")
    assert rules == ["class.bookbox", "tag.h4", "tag.a", "text"]


def test_unbalanced_raises():
    import pytest

    a = RuleAnalyzer("div[(unclosed&&tag.p")
    with pytest.raises(RuleBalanceError):
        a.split_rule("&&", "||", "%%")


def test_inner_rule_pair():
    a = RuleAnalyzer("search?key={{key}}&page={{page + 1}}&x=1")
    out = a.inner_rule_pair("{{", "}}", lambda js: f"E({js})")
    assert out == "search?key=E(key)&page=E(page + 1)&x=1"


def test_inner_rule_json():
    a = RuleAnalyzer("{$.data.title}-{$.data.author}")
    out = a.inner_rule("{$.", 1, 1, lambda p: f"<{p}>")
    assert out == "<$.data.title>-<$.data.author>"


def test_trim():
    a = RuleAnalyzer("@class.a@text")
    a.trim()
    rules = a.split_rule("@")
    assert rules[0] == "class.a"
