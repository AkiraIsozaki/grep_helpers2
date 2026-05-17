"""§10.3 縮約・§8.4 全件免除（spec v4 §4 WS3・Inv-6）。"""

from grep_analyzer.diagnostics import (
    Diagnostics, SECTION_8_4_CATEGORIES, _is_exempt)


def test_detail_limit0は現行と完全同一():
    d = Diagnostics()
    for i in range(5):
        d.add("walk_skipped_large", f"f{i}")
    assert d.render(detail_limit=0, exempt=SECTION_8_4_CATEGORIES) == d.render()


def test_非84カテゴリは縮約_集約行():
    d = Diagnostics()
    for i in range(5):
        d.add("walk_skipped_large", f"f{i}")
    out = d.render(detail_limit=2, exempt=SECTION_8_4_CATEGORIES)
    assert "walk_skipped_large\tf0" in out and "walk_skipped_large\tf1" in out
    assert "walk_skipped_large\tf2" not in out
    assert "walk_skipped_large\t(... 3 more, 5 total)" in out
    assert "walk_skipped_large\t5" in out                # summary は真総数


def test_84カテゴリは縮約しない_全件():
    d = Diagnostics()
    for i in range(5):
        d.add("symbol_rejected", f"s{i}")
        d.add("prov_max_depth", f"p{i}")
    out = d.render(detail_limit=2, exempt=SECTION_8_4_CATEGORIES)
    for i in range(5):
        assert f"symbol_rejected\ts{i}" in out
        assert f"prov_max_depth\tp{i}" in out
    assert "more, 5 total" not in out


def test_is_exempt_prov_プレフィックスと完全一致集合():
    assert _is_exempt("prov_anything")            # prov_ プレフィックス
    assert _is_exempt("symbol_rejected")          # 完全一致
    assert _is_exempt("getter_setter_no_expand")  # 完全一致
    assert not _is_exempt("walk_skipped_large")   # 非 §8.4
