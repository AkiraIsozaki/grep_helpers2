"""tree-sitter 分類（spec §7）。構文位置が確定すれば high。"""

from grep_analyzer.classifiers.ts_classifier import classify_ts


def test_Javaのif比較行は比較highと判定する():
    src = 'class A {\n void m(){\n  if (s.equals("K")) {}\n }\n}\n'
    assert classify_ts("java", src, 3) == ("比較", "high")


def test_Javaのフィールド宣言は宣言highと判定する():
    src = 'class A {\n static final String K = "K";\n}\n'
    assert classify_ts("java", src, 2) == ("宣言", "high")


def test_Cのdefineは宣言highと判定する():
    src = '#define CODE "X"\nint main(){return 0;}\n'
    assert classify_ts("c", src, 1) == ("宣言", "high")


def test_ProCはEXEC_SQLをマスクしてもC宣言を分類できる():
    # `char *p = "X";` は C の declaration（宣言）。EXEC SQL 行が中立化されても
    # 行番号保存のため3行目が宣言として解釈できることを確認する。
    src = 'int f(){\n EXEC SQL SELECT 1;\n char *p = "X";\n}\n'
    assert classify_ts("proc", src, 3) == ("宣言", "high")
