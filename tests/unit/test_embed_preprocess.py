from grep_analyzer.embed_preprocess import extract_jsp_java, jsp_region_span


def test_jsp_scriptletのjavaを残し他を空白化():
    src = "<html>\n<% int x = foo(); %>\n<p>text</p>\n"
    out = extract_jsp_java(src)
    assert out.count("\n") == src.count("\n")
    assert "int x = foo();" in out
    assert "<html>" not in out and "text" not in out
    assert "<%" not in out and "%>" not in out


def test_jsp_式と宣言を残す():
    src = "<%= title %>\n<%! private int n; %>\n"
    out = extract_jsp_java(src)
    assert "title" in out
    assert "private int n;" in out


def test_jsp_ELを残しprefixを除去():
    src = "${ user.code }\n${ fn:length(list) }\n"
    out = extract_jsp_java(src)
    assert "user.code" in out
    assert "length(list)" in out
    assert "fn:" not in out


def test_jsp_多バイト混在でも行数保存():
    src = "<%-- 日本語 --%>\n<% String 名前 = TRACKED; %>\n"
    out = extract_jsp_java(src)
    assert out.count("\n") == src.count("\n")
    assert "TRACKED" in out and "名前" in out
    assert "日本語" not in out


def test_jsp_ディレクティブとコメントと標準アクションを空白化():
    src = ('<%@ page import="java.util.*" %>\n'
           "<%-- comment ${secret} --%>\n"
           "<!-- html ${hidden} -->\n"
           '<jsp:useBean id="bean" class="X"/>\n')
    out = extract_jsp_java(src)
    assert out.count("\n") == src.count("\n")
    assert "import" not in out and "secret" not in out
    assert "hidden" not in out and "bean" not in out


def test_jsp_region_span_多行scriptletの行スパン():
    src = "<html>\n<%\n  int x = 1;\n%>\n</html>\n"
    assert jsp_region_span(src, 3) == (1, 3)


def test_jsp_region_span_区間外はNone():
    src = "<html>\n<% int x = 1; %>\n<p>t</p>\n"
    assert jsp_region_span(src, 3) is None
