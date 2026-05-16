"""SQL/Shell の正規表現分類（spec §7）。confidence は medium。"""

from grep_analyzer.classifiers.regex_classifier import classify_sql, classify_shell


def test_SQLのWHERE比較は比較と判定する():
    assert classify_sql("WHERE col = 'X'") == ("比較", "medium")


def test_SQLのINSERT_VALUESは代入と判定する():
    assert classify_sql("INSERT INTO t VALUES ('X')") == ("代入", "medium")


def test_Shellの変数代入は代入と判定する():
    assert classify_shell('CODE="X"') == ("代入", "medium")


def test_Shellのtest比較は比較と判定する():
    assert classify_shell('[ "$x" = "X" ]') == ("比較", "medium")


def test_該当規則がなければその他と判定する():
    assert classify_sql("-- just a comment") == ("その他", "medium")


def test_OracleのPLSQL代入は代入と判定する():
    assert classify_sql("v_code := 'X';") == ("代入", "medium")


def test_OracleのDECODEは分岐と判定する():
    assert classify_sql("SELECT DECODE(st,1,'OK','NG') FROM dual") == ("分岐", "medium")


def test_OracleのCASE_WHENは分岐と判定する():
    assert classify_sql("SELECT CASE WHEN st=1 THEN 'A' END FROM dual") == ("分岐", "medium")


def test_既存のWHERE比較とINSERT代入はOracle規則でも不変():
    assert classify_sql("WHERE col = 'X'") == ("比較", "medium")
    assert classify_sql("INSERT INTO t VALUES ('X')") == ("代入", "medium")
