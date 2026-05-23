from grep_analyzer.embed_preprocess import (
    effective_language,
    extract_angular_ts,
    extract_inline_angular,
    extract_jsp_java,
    host_grammar,
    host_source,
    inline_template_spans,
    jsp_region_span,
)


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
    assert len(out) == len(src)            # char 長保存（lineno/桁写像の前提）
    assert "TRACKED" in out and "名前" in out
    assert "日本語" not in out


def test_jsp_レガシー文字コードのbyteからdecode後に抽出が成立する():
    """spec §8: レガシー JSP の SJIS/EUC-JP ＝ 抽出は復号後 char 単位で encoding 非依存。

    パイプラインが byte→decode 済の str を渡す前提を、SJIS(cp932)/EUC-JP の
    実 byte からの round-trip で表明する（検出→復号は言語非依存の共通経路
    ＝既存 cp932_resume/encoding_utf8 golden が固定。本テストは jsp 抽出が
    復号後 str に対し encoding 非依存であることを直接表明する）。
    """
    text = "<%-- 日本語コメント --%>\n<% String shori = TRACKED; %>\n"
    for codec in ("cp932", "euc_jp"):
        raw = text.encode(codec)            # レガシー byte 列
        decoded = raw.decode(codec)         # パイプライン相当の復号
        out = extract_jsp_java(decoded)
        assert out.count("\n") == decoded.count("\n")   # 行数保存（encoding 非依存）
        assert "TRACKED" in out and "shori" in out      # scriptlet java を抽出
        assert "日本語コメント" not in out               # コメントは空白化


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


def test_host_grammar_既存言語は恒等():
    for lang in ("java", "c", "python", "javascript", "typescript", "tsx", "html"):
        assert host_grammar(lang) == lang


def test_host_grammar_埋め込みはホストへ写像():
    assert host_grammar("proc") == "c"
    assert host_grammar("jsp") == "java"
    assert host_grammar("angular") == "typescript"


def test_host_source_既存言語は恒等():
    s = "int x = 1;\nfoo();\n"
    for lang in ("java", "c", "python", "javascript", "typescript", "tsx", "html"):
        assert host_source(lang, s) == s


def test_host_source_proc_は_EXEC_SQL_を空白化():
    s = "EXEC SQL SELECT 1 INTO :x FROM dual;\n"
    out = host_source("proc", s)
    assert "SELECT" not in out and out.count("\n") == s.count("\n")


def test_host_source_jsp_は_extract_jsp_java():
    s = "<p><%= title %></p>\n"
    assert host_source("jsp", s) == extract_jsp_java(s)


def test_host_source_angular_は_extract_angular_ts():
    s = '<p>{{ user.code }}</p>\n'
    assert host_source("angular", s) == extract_angular_ts(s)


def test_angular_補間とバインディングの式を残す():
    src = '<p>{{ user.code }}</p>\n<a [href]="url">x</a>\n'
    out = extract_angular_ts(src)
    assert out.count("\n") == src.count("\n")
    assert "user.code" in out and "url" in out
    assert "<p>" not in out and "href" not in out


def test_angular_ngFor_を_let_X_eq_Y_に正規化():
    src = '<li *ngFor="let item of items; trackBy: t">x</li>\n'
    out = extract_angular_ts(src)
    assert "let item" in out and "items" in out
    assert " of " not in out and "trackBy" not in out


def test_angular_パイプ右辺を除去():
    src = "<p>{{ value | currency }}</p>\n"
    out = extract_angular_ts(src)
    assert "value" in out and "currency" not in out


def test_angular_HTMLコメント内の式は空白化():
    src = "<!-- {{ secret }} -->\n"
    out = extract_angular_ts(src)
    assert "secret" not in out


# ── angular_inline 新規テスト ──────────────────────────────────────────────────

_COMPONENT = (
    'import { Component } from "@angular/core";\n'      # 1
    "@Component({\n"                                     # 2
    '  selector: "app-x",\n'                             # 3
    "  template: `\n"                                    # 4
    "    <ul>\n"                                         # 5
    '      <li *ngFor="let row of TRACKED">\n'           # 6
    "        {{ row.code }}\n"                           # 7
    "      </li>\n"                                      # 8
    "    </ul>\n"                                         # 9
    "  `,\n"                                             # 10
    "})\n"                                               # 11
    "export class XComponent {\n"                        # 12
    "  items = TRACKED;\n"                               # 13
    "}\n")                                               # 14


def test_inline_template_spans_検出():
    spans = inline_template_spans(_COMPONENT)
    assert len(spans) == 1
    assert spans[0] == (3, 9)        # template: ` 開き行(3)〜閉じ ` 行(9)・0始まり


def test_inline_template_spans_templateUrlは非検出():
    src = '@Component({ templateUrl: "./x.html" })\n'
    assert inline_template_spans(src) == []


def test_inline_template_spans_stylesは非検出():
    src = "@Component({ styles: [`a{}`, `b{}`] })\n"
    assert inline_template_spans(src) == []


def test_extract_inline_angular_テンプレのみangular抽出_TSコード誤抽出なし():
    out = extract_inline_angular(_COMPONENT)
    assert out.count("\n") == _COMPONENT.count("\n")
    assert "let row = TRACKED" in out
    assert "row.code" in out
    assert "selector" not in out and "app-x" not in out
    assert "items" not in out


def test_effective_language_テンプレ行はangular_inline():
    assert effective_language("typescript", _COMPONENT, 4) == "angular_inline"   # template: ` 開き行（spec §7）
    assert effective_language("typescript", _COMPONENT, 6) == "angular_inline"
    assert effective_language("typescript", _COMPONENT, 7) == "angular_inline"


def test_effective_language_コード行はtypescript():
    assert effective_language("typescript", _COMPONENT, 13) == "typescript"


def test_effective_language_非tsと非テンプレは恒等():
    assert effective_language("java", "x", 1) == "java"
    assert effective_language("jsp", "x", 1) == "jsp"
    plain = "export const x = 1;\n"
    assert effective_language("typescript", plain, 1) == "typescript"
    assert inline_template_spans(plain) == []
