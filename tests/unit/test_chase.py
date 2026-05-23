"""追跡シンボル抽出規則の仕様（spec §8.1・Phase 2 が消費）。"""

from grep_analyzer.chase import (
    extract_chase_symbols,
    extract_var_symbols,
    mask_literals,
)


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


def test_文字列とコメントをマスクし行長を保つ():
    src = 'String s = "x=1"; // y=2'
    out = mask_literals("java", src)
    assert out == 'String s =      ;       '   # "x=1"=5字→空白5, // y=2=6字→空白6
    assert len(out) == len(src) == 24
    assert len(mask_literals("c", 'a=1; /* z=9 */ b=2')) == len('a=1; /* z=9 */ b=2')


def test_文字列内の代入様字句は追跡シンボルにしない():
    cs = extract_chase_symbols("java", "", 'String s = "url=/x"; int n = 1;')
    assert "url" not in cs.vars and cs.vars == ("s", "n")


def test_Java定数はstaticかつfinalのみでgenericと配列を許容する():
    assert extract_chase_symbols(
        "java", "", "private static final Map<String, Integer> CODE_MAP = init();"
    ).constants == ("CODE_MAP",)
    assert extract_chase_symbols("java", "", "static final int[] CODES = a;").constants == ("CODES",)
    cs = extract_chase_symbols("java", "", "final int X = 1;")
    assert cs.constants == () and cs.vars == ("X",)
    assert extract_chase_symbols("java", "", "public static int Y = 1;").constants == ()


def test_Javaのgetterとsetterとvarをマスクのうえ分類抽出する():
    cs = extract_chase_symbols("java", "", "int count = svc.getName(); obj.setValue(count);")
    assert cs.vars == ("count",)
    assert cs.getters == ("getName",) and cs.setters == ("setValue",)


def test_C定義とconst定数を抽出しProCホスト変数は追跡投入しない():
    assert extract_chase_symbols("c", "", "#define MAX_LEN 10").constants == ("MAX_LEN",)
    assert extract_chase_symbols("c", "", "const int FOO = 1;").constants == ("FOO",)
    assert extract_chase_symbols("c", "", "int n = 3;").vars == ("n",)
    # spec §8.1 手順1（8c21227 で本体明確化）: Pro*C ホスト変数 :host は
    # 外部・ホスト境界＝追跡投入しない。手順5 は停止性の字句形のみで投入是非でない。
    cs = extract_chase_symbols("proc", "", "EXEC SQL SELECT c INTO :host FROM t;")
    assert "host" not in cs.vars and cs.vars == () and cs.constants == ()


def test_ref_kind言語表の禁止セルは空を返す():
    # spec §9 ref_kind×言語表の `—` セルを負の契約で固定（将来改修の回帰防御）。
    pc = extract_chase_symbols("proc", "", "int n = 3; #define M 1")
    assert pc.getters == () and pc.setters == ()                 # C/Pro*C: getter/setter 無
    sq = extract_chase_symbols("sql", "", "v := 1;")
    assert sq.constants == () and sq.getters == () and sq.setters == ()  # SQL: const/getter/setter 無
    cs = extract_chase_symbols("shell", "cshell", "set CODE = 1")
    assert cs.constants == () and cs.getters == () and cs.setters == ()  # cshell: const 無
    bo = extract_chase_symbols("shell", "bourne", 'NAME="x"')
    assert bo.constants == () and bo.getters == () and bo.setters == ()  # bourne 非readonly: const 無


def test_bourneのreadonlyは定数SQLとcshellはvarのみ():
    assert extract_chase_symbols("shell", "bourne", "readonly CODE=1").constants == ("CODE",)
    assert extract_chase_symbols("shell", "bourne", 'NAME="x"').vars == ("NAME",)
    cs = extract_chase_symbols("sql", "", "v_code := 'X';")
    assert cs.vars == ("v_code",) and cs.getters == () and cs.constants == ()
    assert extract_chase_symbols("shell", "cshell", "set CODE = 1").vars == ("CODE",)


def test_var抽出は既存extract_var_symbolsと一致する():
    line = 'CODE="X"'
    assert list(extract_chase_symbols("shell", "bourne", line).vars) == extract_var_symbols(
        "shell", "bourne", line)


def test_Perlのmaskは文字列とコメントを潰しドル井戸は壊さない():
    # $#array は最終添字 sigil でありコメントではない（設計 §5.1 C-D）
    assert mask_literals("perl", "$last = $#array; # tail") == "$last = $#array;       "
    # 長さ保存(18字): "x=1"→空白5, "; # c" は ; +空白1+ "# c"→空白3 ＝ ; 後は空白4
    assert mask_literals("perl", 'my $s = "x=1"; # c') == "my $s =      ;    "


def test_Perlのmyとour代入左辺をsigil除去で抽出する():
    assert extract_chase_symbols("perl", "", "my $code = 1;").vars == ("code",)
    assert extract_chase_symbols("perl", "", "our @list = ();").vars == ("list",)
    assert extract_chase_symbols("perl", "", "$total = 0;").vars == ("total",)


def test_Perlのuse_constantは定数として抽出する():
    cs = extract_chase_symbols("perl", "", "use constant MAX => 10;")
    assert cs.constants == ("MAX",) and cs.vars == ()


def test_Perlのfat_commaと比較は代入抽出しない():
    assert extract_chase_symbols("perl", "", "( $key => 1 )").vars == ()
    assert extract_chase_symbols("perl", "", "$x == 1").vars == ()
    assert extract_chase_symbols("perl", "", "$x =~ /re/").vars == ()


def test_Perlにgetter_setterは無い():
    cs = extract_chase_symbols("perl", "", "my $x = 1;")
    assert cs.getters == () and cs.setters == ()


def test_Groovyのdefと型付き変数代入を抽出する():
    assert extract_chase_symbols("groovy", "", "def code = 1").vars == ("code",)
    assert extract_chase_symbols("groovy", "", "int total = 5").vars == ("total",)


def test_Groovyのfinalは定数として抽出する():
    assert extract_chase_symbols("groovy", "", "final MAX = 100").constants == ("MAX",)
    cs = extract_chase_symbols("groovy", "", "static final int LIMIT = 9")
    assert cs.constants == ("LIMIT",) and "LIMIT" not in cs.vars


def test_Groovyにgetter_setterは無くconstはvarに重複しない():
    cs = extract_chase_symbols("groovy", "", "final MAX = 1")
    assert cs.getters == () and cs.setters == () and cs.vars == ()


def test_PLSQL型付き宣言は型名でなく先頭識別子をvar抽出する():
    assert extract_chase_symbols("sql", "", "v_x NUMBER := 1;").vars == ("v_x",)
    assert extract_chase_symbols(
        "sql", "", "v_name VARCHAR2(100) := 'a';").vars == ("v_name",)


def test_PLSQL_CONSTANTは定数としvarに型名や自身を出さない():
    cs = extract_chase_symbols("sql", "", "c_max CONSTANT NUMBER := 100;")
    assert cs.constants == ("c_max",) and cs.vars == ()


def test_PLSQL小文字constantもリークしない():
    cs = extract_chase_symbols("sql", "", "c_max constant number := 100;")
    assert cs.constants == ("c_max",) and "constant" not in cs.vars and cs.vars == ()


def test_PLSQL複数代入は宣言是正後も全左辺を温存する():
    # R2-C1 回帰: golden 非対象のサイレント退行を unit で守る
    assert extract_var_symbols("sql", "", "a := 1; b := 2;") == ["a", "b"]


def test_extract_chase_symbols_tree_python():
    from grep_analyzer.chase import extract_chase_symbols_tree
    cs = extract_chase_symbols_tree("python", "XX = 1\n", 1)
    assert cs.constants == ("XX",)


def test_extract_chase_symbols_tree_非AST言語は空():
    from grep_analyzer.chase import extract_chase_symbols_tree
    cs = extract_chase_symbols_tree("java", "int x = 1;\n", 1)
    assert cs.constants == () and cs.vars == ()


def test_extract_chase_symbols_from_root_js():
    from grep_analyzer.chase import extract_chase_symbols_from_root
    from grep_analyzer.classifiers.ts_classifier import parse_tree
    cs = extract_chase_symbols_from_root("javascript", parse_tree("javascript", "const A = 1;\n"), 1)
    assert cs.constants == ("A",)
