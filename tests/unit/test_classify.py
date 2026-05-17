"""共有行分類の仕様（pipeline と fixedpoint が共通利用）。"""

from grep_analyzer.classify import classify_hit


def test_ts言語はtree_sitterでhigh分類():
    # if は自分の行・正しいメソッド内（既存 test_ts_classifier/test_pipeline と同形）。
    # 不正 Java をクラス本体直下に置くと tree-sitter が ERROR ノード化し比較を取れない。
    src = "class A {\n void m(int x){\n  if (x == 1) {}\n }\n}\n"
    assert classify_hit("java", "", src, 3, "  if (x == 1) {}") == ("比較", "high")


def test_sqlとshellはmedium分類で未知はbourneフォールバック():
    assert classify_hit("sql", "", "", 1, "v := 1;") == ("代入", "medium")
    assert classify_hit("shell", "cshell", "", 1, "set X = 1") == ("代入", "medium")
    assert classify_hit("unknown", "", "", 1, "X=1") == ("代入", "medium")
