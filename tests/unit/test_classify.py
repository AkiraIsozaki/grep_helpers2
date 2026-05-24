"""共有行分類の仕様（pipeline と fixedpoint が共通利用）。"""

from grep_analyzer.classify import classify_hit
from grep_analyzer.classifiers.regex_classifier import classify_groovy, classify_perl, classify_sql


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


def test_PLSQL手続き型分類():
    assert classify_sql("PROCEDURE do_x IS") == ("宣言", "medium")
    assert classify_sql("  FUNCTION calc RETURN NUMBER IS") == ("宣言", "medium")
    assert classify_sql("IF v_x > 0 THEN") == ("比較", "medium")
    assert classify_sql("WHILE i < 10 LOOP") == ("分岐", "medium")
    assert classify_sql("DBMS_OUTPUT.PUT_LINE('hi');") == ("出力", "medium")


def test_PLSQL誤爆回避():
    # 行頭でない手続き型語・文字列内語は誤分類しない（C-B）。
    # DBMS_OUTPUT は出力（行内 'FUNCTION' を宣言と誤らない）。
    assert classify_sql("DBMS_OUTPUT.PUT_LINE('FUNCTION x');") == ("出力", "medium")
    # OPEN c FOR ... は FOR が行頭でないため新ループ規則は不発＝既存規則にも該当せず その他。
    assert classify_sql("OPEN c FOR SELECT 1 FROM dual;") == ("その他", "medium")


def test_jsp_classify_各category():
    src_if = "<% if (a > b) { } %>\n"
    assert classify_hit("jsp", "", src_if, 1, src_if)[0] == "比較"
    src_decl = "<%! private int n; %>\n"
    assert classify_hit("jsp", "", src_decl, 1, src_decl)[0] == "宣言"
    src_ret = "<% return v; %>\n"
    assert classify_hit("jsp", "", src_ret, 1, src_ret)[0] == "return"


def test_jsp_式とELはその他():
    src_expr = "<%= title %>\n"
    assert classify_hit("jsp", "", src_expr, 1, src_expr)[0] == "その他"
    src_el = "${ user.code }\n"
    assert classify_hit("jsp", "", src_el, 1, src_el)[0] == "その他"


def test_html_は常にその他_high():
    assert classify_hit("html", "", "<p>x</p>\n", 1, "<p>x</p>") == ("その他", "high")


def test_angular_classify():
    src = '<p>{{ user.code }}</p>\n'
    assert classify_hit("angular", "", src, 1, src)[0] == "その他"
    src2 = '<button (click)="x = 1">b</button>\n'
    assert classify_hit("angular", "", src2, 1, src2)[0] == "代入"


def test_angular_inline_classify_直接():
    from grep_analyzer.classifiers.ts_classifier import classify_ts
    src = '@Component({ template: `<p>{{ user.code }}</p>` })\n'
    assert classify_ts("angular_inline", src, 1)[0] == "その他"
    src2 = '@Component({ template: `<button (click)="x = 1">b</button>` })\n'
    assert classify_ts("angular_inline", src2, 1)[0] == "代入"


_C = ('@Component({\n'
      '  template: `<button (click)="x = 1">{{ user.code }}</button>`,\n'   # 2
      '})\n'
      'export class C {\n'                                                    # 4
      '  items = TRACKED;\n'                                                  # 5
      '}\n')


def test_classify_hit_inline_template行はangular扱い():
    assert classify_hit("typescript", "", _C, 2, "")[0] == "代入"            # (click)="x=1"


def test_classify_hit_TSコード行はtypescript不変():
    # L5 class field items = TRACKED → public_field_definition → 宣言（typescript 経路）。
    # 誤って angular_inline に routing されると領域外で空白化され その他 になる＝判別子。
    assert classify_hit("typescript", "", _C, 5, "")[0] == "宣言"


def test_Perlのコメント行はコメントlow():
    assert classify_perl("# perl comment 777") == ("コメント", "low")
    assert classify_perl("  # indented") == ("コメント", "low")


def test_Perlの同居コメントはコード優先():
    assert classify_perl("my $x = 1; # trailing") == ("代入", "medium")


def test_Groovyのコメント行はコメントlow():
    assert classify_groovy("// groovy comment 777") == ("コメント", "low")
    assert classify_groovy("/* block 777 */") == ("コメント", "low")


def test_Groovyの同居コメントはコード優先():
    assert classify_groovy("def x = 1 // trailing") == ("代入", "medium")


def test_classify_hit_コメント統合_ASTとregex():
    assert classify_hit("java", "", "class A {\n // 777\n}\n", 2, "// 777") == \
        ("コメント", "low")
    assert classify_hit("sql", "", "", 1, "-- 777 comment") == ("コメント", "low")
