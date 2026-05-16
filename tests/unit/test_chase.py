"""追跡シンボル抽出規則の仕様（spec §8.1・Phase 2 が消費）。"""

from grep_analyzer.chase import extract_var_symbols


def test_Oracleの代入左辺を抽出する():
    assert extract_var_symbols("sql", "", "v_code := 'X';") == ["v_code"]


def test_Oracleのバインド変数と置換変数は抽出しない():
    assert extract_var_symbols("sql", "", ":bind := 1") == []
    assert extract_var_symbols("sql", "", "WHERE c = &subst") == []


def test_bourneの変数代入左辺を抽出する():
    assert extract_var_symbols("shell", "bourne", 'CODE="X"') == ["CODE"]
    assert extract_var_symbols("shell", "bourne", 'echo "$CODE"') == []


def test_cshellのset_setenv_atの左辺を抽出する():
    assert extract_var_symbols("shell", "cshell", 'set CODE = "X"') == ["CODE"]
    assert extract_var_symbols("shell", "cshell", "setenv PATH /usr/bin") == ["PATH"]
    assert extract_var_symbols("shell", "cshell", "@ i = 1") == ["i"]


def test_対象外言語と該当なしは空リスト():
    assert extract_var_symbols("java", "", 'String K = "X";') == []
    assert extract_var_symbols("sql", "", "SELECT 1 FROM dual") == []


def test_Oracle同一行複数代入は全左辺を順に抽出する():
    # 1物理行に複数文（正当な PL/SQL）。決定的に出現順で全件。
    assert extract_var_symbols("sql", "", "a := 1; b := 2;") == ["a", "b"]


def test_Oracleのトリガ相関名とレコードフィールドはv1既知境界として記録する():
    # spec §8.4: :new/:old トリガ相関名・rec.field 修飾代入は v1 既知境界。
    # v1 は限定子を剥がした末尾識別子を決定的に抽出する（Phase 2 で §8.3
    # 静的ストップリストにより汎用名の横展開を抑止する前提）。本テストは
    # 「誤検出ではなく仕様として固定された挙動」であることを将来へ明示する。
    assert extract_var_symbols("sql", "", ":new.col := 1") == ["col"]
    assert extract_var_symbols("sql", "", ":old.col := 1") == ["col"]
    assert extract_var_symbols("sql", "", "rec.field := 1") == ["field"]
