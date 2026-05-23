"""共有行分類の仕様（pipeline と fixedpoint が共通利用）。"""

from grep_analyzer.classify import classify_hit
from grep_analyzer.classifiers.regex_classifier import classify_groovy, classify_perl


def test_ts言語はtree_sitterでhigh分類():
    # if は自分の行・正しいメソッド内（既存 test_ts_classifier/test_pipeline と同形）。
    # 不正 Java をクラス本体直下に置くと tree-sitter が ERROR ノード化し比較を取れない。
    src = "class A {\n void m(int x){\n  if (x == 1) {}\n }\n}\n"
    assert classify_hit("java", "", src, 3, "  if (x == 1) {}") == ("比較", "high")


def test_sqlとshellはmedium分類で未知はbourneフォールバック():
    assert classify_hit("sql", "", "", 1, "v := 1;") == ("代入", "medium")
    assert classify_hit("shell", "cshell", "", 1, "set X = 1") == ("代入", "medium")
    assert classify_hit("unknown", "", "", 1, "X=1") == ("代入", "medium")


def test_Perl分類():
    assert classify_perl("my $x = 1;") == ("代入", "medium")
    assert classify_perl("sub foo {") == ("宣言", "medium")
    assert classify_perl("if ($a eq $b) {") == ("比較", "medium")
    assert classify_perl("foreach my $i (@xs) {") == ("分岐", "medium")
    assert classify_perl('print "hi";') == ("出力", "medium")


def test_Perlのアロー矢印とfat_commaは比較代入に誤爆しない():
    assert classify_perl("$obj->method();") == ("その他", "medium")
    assert classify_perl("( $k => 1 )") == ("その他", "medium")


def test_Groovy分類():
    assert classify_groovy("def x = 1") == ("代入", "medium")
    assert classify_groovy("def foo() {") == ("宣言", "medium")
    assert classify_groovy("class Foo {") == ("宣言", "medium")
    assert classify_groovy("if (a == b) {") == ("比較", "medium")
    assert classify_groovy("switch (x) {") == ("分岐", "medium")
    assert classify_groovy("return v") == ("return", "medium")
    assert classify_groovy("println v") == ("出力", "medium")


def test_Groovy型付き宣言は初期化子があれば代入になる():
    assert classify_groovy("List<String> xs = []") == ("代入", "medium")
