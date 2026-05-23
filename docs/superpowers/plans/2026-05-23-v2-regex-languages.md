# v2 正規表現トラック言語追加（PL/SQL・Perl・Groovy）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** grep_analyzer に PL/SQL（既存 `sql` へ統合）・Perl・Groovy を行単位正規表現（confidence=medium）で追加し、§5.2 v2+ プラグイン規約を確立する。

**Architecture:** 既存の行単位パイプライン（`detect_language → file_meta → automaton走査 → classify_hit → chase抽出 → snippet → TSV`）は無改造。各言語は dispatcher 経由の差分点（dispatch/classify/_CHASERS/snippet）＋ dispatcher 外の言語依存3箇所（`stoplist.LANG_KEYWORDS`・`pipeline` のシェバン診断条件・`build_snippet` 言語分岐）を埋める。新依存ゼロ。

**Tech Stack:** Python 3.12 標準ライブラリ＋既存 `re` ベース分類器。tree-sitter は不使用（正規表現トラック）。

**設計書（正本）:** `docs/superpowers/specs/2026-05-22-v2-regex-languages-design.md`（converged v3）。本計画が触れない判断はすべて設計書を正とする。

**最重要ゲート Inv-B:** v1 既存 golden を byte 不変に保つ＋既存 unit/integration を green に保つ。各タスクは既存テストを壊さないこと。例外はシェバン一般化に伴う `test_dispatch.py`/`test_pipeline_dialect.py` の**意図的改訂**（Task 7/8 で明示）。

---

## Task 0: ベースライン確立（Inv-B 基準）

**Files:** （変更なし・計測のみ）

- [ ] **Step 1: 全テストを実行し green 件数を記録**

Run: `cd /workspaces/grep_helpers2 && python -m pytest -q`
Expected: 全 PASS（例 `254 passed, 5 skipped`）。この件数を Inv-B 基準として記録する。以降のタスクで既存テストの赤化が無いことを確認する基準とする。

- [ ] **Step 2: 現在の golden 出力を基準として確認**

Run: `python -m pytest tests/golden -q`
Expected: 全 PASS。これが Inv-B（golden byte 不変）の基準。

---

## Task 1: stoplist に perl/groovy 予約語と Oracle データ型を追加（設計 §5.3・§5.2／C-G）

**理由:** `admit()` は `LANG_KEYWORDS.get(language, frozenset())` で予約語を引く。perl/groovy 未登録だと空集合＝予約語（`print`/`class`/`while`/`def`）が追跡集合に入り偽陽性爆発。Oracle データ型（`NUMBER` 等）も追跡から除外する二重防御。

**Files:**
- Modify: `src/grep_analyzer/stoplist.py:14-32`
- Test: `tests/unit/test_stoplist.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_stoplist.py` に追記:

```python
from grep_analyzer.stoplist import LANG_KEYWORDS, SymbolPolicy, admit


def test_perl予約語は追跡集合に入らない():
    pol = SymbolPolicy(min_specificity=2, user_stoplist=frozenset())
    r = admit(["print", "my", "sub", "if", "while", "userCode"], "perl", pol)
    assert r.accepted == ["userCode"]
    assert {s for s, _ in r.rejected} == {"print", "my", "sub", "if", "while"}


def test_groovy予約語は追跡集合に入らない():
    pol = SymbolPolicy(min_specificity=2, user_stoplist=frozenset())
    r = admit(["def", "class", "while", "return", "println", "orderId"], "groovy", pol)
    assert r.accepted == ["orderId"]


def test_sqlのOracleデータ型は追跡集合に入らない():
    pol = SymbolPolicy(min_specificity=2, user_stoplist=frozenset())
    r = admit(["NUMBER", "VARCHAR2", "BOOLEAN", "v_code"], "sql", pol)
    assert r.accepted == ["v_code"]
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_stoplist.py -q -k "perl予約語 or groovy予約語 or Oracleデータ型"`
Expected: FAIL（perl/groovy は KeyError でなく空集合のため `accepted` に予約語が混入／sql データ型も accepted に混入）。

- [ ] **Step 3: stoplist.py に予約語集合を追加**

`src/grep_analyzer/stoplist.py` の `_SQL_KW` 定義へ Oracle データ型を**追加**（既存語を消さない）し、`_PERL_KW`/`_GROOVY_KW` を新設、`LANG_KEYWORDS` へ登録:

```python
_SQL_KW = frozenset(
    "select insert update delete from where and or not null is in like between exists into values "
    "set begin end declare if then else elsif loop for while case when decode dual table view "
    "procedure function trigger as order by group having distinct union all "
    # Oracle データ型（型名 var 抽出のすり抜け対策・設計 §5.2 二重防御）
    "number varchar2 varchar char nchar clob blob date timestamp boolean pls_integer "
    "binary_integer integer float decimal long raw rowid".split())
_PERL_KW = frozenset(
    "my our local state sub package use require if unless elsif else while until for foreach do "
    "return last next redo eq ne lt gt le ge cmp and or not xor print printf say warn die "
    "qw q qq tr defined undef ref scalar wantarray bless".split())
_GROOVY_KW = frozenset(
    "def class interface enum trait if else while switch case for return break continue "
    "println print final static import package new this super true false null void in as "
    "instanceof try catch finally throw throws assert abstract extends implements".split())
LANG_KEYWORDS: dict[str, frozenset[str]] = {
    "java": _JAVA_KW, "c": _C_KW, "proc": _C_KW, "sql": _SQL_KW, "shell": _SHELL_KW,
    "perl": _PERL_KW, "groovy": _GROOVY_KW}
```

- [ ] **Step 4: テストが通ることを確認＋既存 stoplist テスト不変**

Run: `python -m pytest tests/unit/test_stoplist.py -q`
Expected: PASS（新規＋既存すべて）。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/stoplist.py tests/unit/test_stoplist.py
git commit -m "feat(stoplist): perl/groovy予約語とOracleデータ型を採否ストップリストに追加(設計§5.3 C-G)"
```

---

## Task 2: Perl の mask/抽出パターンと perl_chaser（設計 §5.1／C-D）

**Files:**
- Modify: `src/grep_analyzer/patterns/literal_masking.py:10-16`
- Modify: `src/grep_analyzer/patterns/symbol_extraction.py`（末尾に追記）
- Create: `src/grep_analyzer/classifiers/perl_chaser.py`
- Modify: `src/grep_analyzer/classifiers/__init__.py`
- Test: `tests/unit/test_chase.py`（追記）

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_chase.py` に追記:

```python
def test_Perlのmaskは文字列とコメントを潰しドル井戸は壊さない():
    # $#array は最終添字 sigil でありコメントではない（設計 §5.1 C-D）
    assert mask_literals("perl", "$last = $#array; # tail") == "$last = $#array;       "
    assert mask_literals("perl", 'my $s = "x=1"; # c') == "my $s =      ;     "


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
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_chase.py -q -k Perl`
Expected: FAIL（`perl` chaser 未登録＝`extract_chase_symbols` が空 ChaseSymbols を返し、`mask_literals("perl",...)` が原行を返す）。

- [ ] **Step 3: mask パターンを追加**

`src/grep_analyzer/patterns/literal_masking.py` の `MASK_SPECS` に追記（`$#`/`@#`/`%#` 除外の `#` コメント）:

```python
    "perl": [r"'[^']*'", r'"(?:\\.|[^"\\])*"', r"\bqq\([^)]*\)", r"\bq\([^)]*\)",
             r"(?<![$@%])#[^\n]*"],
```

- [ ] **Step 4: 抽出パターンを追加**

`src/grep_analyzer/patterns/symbol_extraction.py` の末尾に追記:

```python
# Perl: sigil 付き代入左辺（== / =~ / => は除外）。sigil は剥がして bare 識別子を採る。
PERL_ASSIGN_RE = re.compile(r"[$@%](\w+)\s*=(?![=~>])")
PERL_USE_CONSTANT_RE = re.compile(r"\buse\s+constant\s+(\w+)")
```

- [ ] **Step 5: perl_chaser を作成**

`src/grep_analyzer/classifiers/perl_chaser.py`:

```python
"""Perl 用 Chaser — sigil 付き代入左辺・use constant を抽出する。

sigil（$ @ %）は剥がして bare 識別子を追跡シンボルとする（設計 §5.1）。
getter/setter は型解決依存のため不追跡（§8.4）。heredoc/POD/任意デリミタ
q// は行単位マスクの対象外＝§8.4 既知境界。

chase.py の dispatcher が `_CHASERS["perl"]` 経由で呼び出す。
"""

from grep_analyzer.model import ChaseSymbols
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
from grep_analyzer.patterns.symbol_extraction import (
    PERL_ASSIGN_RE,
    PERL_USE_CONSTANT_RE,
)


def mask(line: str) -> str:
    """Perl のリテラル / コメントを同字数空白に置換する（$# は壊さない）。"""
    pattern = MASK_PATTERNS["perl"]
    return pattern.sub(lambda m: " " * len(m.group(0)), line)


def extract(dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に Perl の規則で分類抽出する（dialect は無視）。"""
    masked = mask(line)
    consts = tuple(m.group(1) for m in PERL_USE_CONSTANT_RE.finditer(masked))
    const_set = set(consts)
    vars_ = tuple(
        v for v in (m.group(1) for m in PERL_ASSIGN_RE.finditer(masked))
        if v not in const_set
    )
    return ChaseSymbols(consts, vars_, (), ())
```

- [ ] **Step 6: _CHASERS に登録**

`src/grep_analyzer/classifiers/__init__.py` を修正:

```python
from grep_analyzer.classifiers import (
    c_chaser,
    java_chaser,
    perl_chaser,
    shell_chaser,
    sql_chaser,
)
from grep_analyzer.classifiers.base import Chaser

_CHASERS: dict[str, Chaser] = {
    "java": java_chaser,
    "c": c_chaser,
    "proc": c_chaser,
    "shell": shell_chaser,
    "sql": sql_chaser,
    "perl": perl_chaser,
}
```

- [ ] **Step 7: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_chase.py -q`
Expected: PASS（新規 Perl＋既存すべて不変）。

- [ ] **Step 8: コミット**

```bash
git add src/grep_analyzer/patterns/literal_masking.py src/grep_analyzer/patterns/symbol_extraction.py src/grep_analyzer/classifiers/perl_chaser.py src/grep_analyzer/classifiers/__init__.py tests/unit/test_chase.py
git commit -m "feat(perl): perl_chaser追加(sigil除去抽出・use constant・\$#非破壊mask 設計§5.1)"
```

---

## Task 3: Groovy の mask/抽出パターンと groovy_chaser（設計 §5.2）

**Files:**
- Modify: `src/grep_analyzer/patterns/literal_masking.py`
- Modify: `src/grep_analyzer/patterns/symbol_extraction.py`
- Create: `src/grep_analyzer/classifiers/groovy_chaser.py`
- Modify: `src/grep_analyzer/classifiers/__init__.py`
- Test: `tests/unit/test_chase.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_chase.py` に追記:

```python
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
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_chase.py -q -k Groovy`
Expected: FAIL（`groovy` chaser 未登録）。

- [ ] **Step 3: mask パターンを追加**

`literal_masking.py` の `MASK_SPECS` に追記（java と同形・triple-quoted/slashy は §8.4）:

```python
    "groovy": [r"'(?:\\.|[^'\\])*'", r'"(?:\\.|[^"\\])*"', r"//[^\n]*", r"/\*.*?\*/"],
```

- [ ] **Step 4: 抽出パターンを追加**

`symbol_extraction.py` の末尾に追記:

```python
# Groovy: final 定数（static 任意・型任意）と一般代入左辺（限定子は剥がす＝§8.4）。
GROOVY_CONST_RE = re.compile(
    r"\b((?:public|protected|private|static|final)(?:\s+(?:public|protected|private|static|final))*)"
    r"\s+(?:[\w.$<>,\[\]\s]+?\s+)?([A-Za-z_]\w*)\s*=")
GROOVY_VAR_RE = re.compile(r"(?<![=!<>+\-*/%&|^])\b([A-Za-z_]\w*)\s*=(?!=)")
```

- [ ] **Step 5: groovy_chaser を作成**

`src/grep_analyzer/classifiers/groovy_chaser.py`:

```python
"""Groovy 用 Chaser — final 定数と def/型付き変数代入を抽出する。

final（static 任意）を constant、それ以外の代入左辺を var とする。getter/setter
は型解決依存のため不追跡（§8.4）。`obj.field=` の限定子剥がし・複数行 GString・
slashy string は §8.4 既知境界。

chase.py の dispatcher が `_CHASERS["groovy"]` 経由で呼び出す。
"""

from grep_analyzer.model import ChaseSymbols
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
from grep_analyzer.patterns.symbol_extraction import (
    GROOVY_CONST_RE,
    GROOVY_VAR_RE,
)


def mask(line: str) -> str:
    """Groovy のリテラル / コメントを同字数空白に置換する。"""
    pattern = MASK_PATTERNS["groovy"]
    return pattern.sub(lambda m: " " * len(m.group(0)), line)


def extract(dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に Groovy の規則で分類抽出する（dialect は無視）。"""
    masked = mask(line)
    consts = tuple(
        g.group(2) for g in GROOVY_CONST_RE.finditer(masked)
        if "final" in g.group(1).split()
    )
    const_set = set(consts)
    vars_ = tuple(
        v for v in (m.group(1) for m in GROOVY_VAR_RE.finditer(masked))
        if v not in const_set
    )
    return ChaseSymbols(consts, vars_, (), ())
```

- [ ] **Step 6: _CHASERS に登録**

`classifiers/__init__.py` の import と dict に `groovy_chaser` / `"groovy": groovy_chaser` を追加（Task 2 と同形）。

- [ ] **Step 7: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_chase.py -q`
Expected: PASS（新規 Groovy＋既存不変）。

- [ ] **Step 8: コミット**

```bash
git add src/grep_analyzer/patterns/literal_masking.py src/grep_analyzer/patterns/symbol_extraction.py src/grep_analyzer/classifiers/groovy_chaser.py src/grep_analyzer/classifiers/__init__.py tests/unit/test_chase.py
git commit -m "feat(groovy): groovy_chaser追加(final定数・def/型付きvar抽出 設計§5.2)"
```

---

## Task 4: PL/SQL 宣言対応の抽出是正（設計 §5.2／C-C・R2-C1）

**理由:** 既存 `ORACLE_ASSIGN_RE` は `:=` 直前トークンを取るため型付き宣言で型名（`NUMBER`）を var 抽出する。宣言形（名前と `:=` の間に実型トークンあり）を per-`:=` で判定し先頭識別子を採る。通常/複数代入は温存。IGNORECASE 必須。

**Files:**
- Modify: `src/grep_analyzer/patterns/symbol_extraction.py`
- Modify: `src/grep_analyzer/classifiers/sql_chaser.py`
- Test: `tests/unit/test_chase.py`

- [ ] **Step 1: 失敗するテストを書く（回帰保護込み）**

`tests/unit/test_chase.py` に追記:

```python
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
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_chase.py -q -k PLSQL`
Expected: FAIL（型付き宣言で `NUMBER` が var に混入／CONSTANT が機能しない）。

- [ ] **Step 3: 宣言対応の抽出パターンを追加**

`symbol_extraction.py` に追記（既存 `ORACLE_ASSIGN_RE` は ORACLE_DECL_ASSIGN_RE に置換され未使用となるが互換のため残置）:

```python
# PL/SQL 宣言対応の := 抽出（C-C/R2-C1）。名前と := の間に実型トークンが
# あれば宣言形＝先頭 id を採り型名を捨てる。型トークン無しは通常代入＝その id。
# PL/SQL はキーワード大小無視＝IGNORECASE 必須（小文字 constant リーク防止）。
ORACLE_DECL_ASSIGN_RE = re.compile(
    r"(?<![:&])\b([A-Za-z_]\w*)(?:\s+(?:CONSTANT\s+)?[A-Za-z_][\w%.]*(?:\([^)]*\))?)?\s*:=",
    re.IGNORECASE)
ORACLE_CONSTANT_RE = re.compile(r"(?<![:&])\b([A-Za-z_]\w*)\s+CONSTANT\b", re.IGNORECASE)
```

- [ ] **Step 4: sql_chaser を是正**

`src/grep_analyzer/classifiers/sql_chaser.py` を修正（import 差替＋ extract で constant 分離）:

```python
from grep_analyzer.model import ChaseSymbols
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
from grep_analyzer.patterns.symbol_extraction import (
    ORACLE_CONSTANT_RE,
    ORACLE_DECL_ASSIGN_RE,
)


def mask(line: str) -> str:
    """SQL のリテラル / コメントを同字数空白に置換する。"""
    pattern = MASK_PATTERNS["sql"]
    return pattern.sub(lambda m: " " * len(m.group(0)), line)


def _extract_var_symbols(dialect: str, line: str) -> list[str]:
    """与えられた行から PL/SQL `:=` の左辺（宣言形は先頭 id）を抽出する。

    型付き宣言 `name TYPE := …` では型名でなく先頭 id を採る（C-C）。
    通常代入 `x := y`・複数代入 `a:=1;b:=2` は全左辺を温存（R2-C1）。
    バインド `:v`／置換 `&v` は lookbehind で除外。
    """
    return [m.group(1) for m in ORACLE_DECL_ASSIGN_RE.finditer(line)]


def extract(dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に SQL(Oracle/PL-SQL) の規則で分類抽出する（dialect 無視）。"""
    masked = mask(line)
    consts = tuple(m.group(1) for m in ORACLE_CONSTANT_RE.finditer(masked))
    const_set = set(consts)
    vars_ = tuple(v for v in _extract_var_symbols(dialect, masked) if v not in const_set)
    return ChaseSymbols(consts, vars_, (), ())
```

- [ ] **Step 5: テストが通ることを確認＋既存 sql/chase 不変**

Run: `python -m pytest tests/unit/test_chase.py -q`
Expected: PASS（新規 PLSQL＋既存の `:=`/複数代入/トリガ相関名/`v_code` すべて不変）。

- [ ] **Step 6: コミット**

```bash
git add src/grep_analyzer/patterns/symbol_extraction.py src/grep_analyzer/classifiers/sql_chaser.py tests/unit/test_chase.py
git commit -m "fix(sql_chaser): PL/SQL宣言の型名var誤抽出を是正し複数代入を温存(設計§5.2 C-C/R2-C1)"
```

---

## Task 5: classify_perl / classify_groovy と classify_hit 分岐（設計 §4.2/§4.3）

**Files:**
- Modify: `src/grep_analyzer/classifiers/regex_classifier.py`
- Modify: `src/grep_analyzer/classify.py`
- Test: `tests/unit/test_classify.py`（新規）

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_classify.py`（新規）:

```python
"""perl/groovy 行分類の仕様（spec §4.2/§4.3・confidence=medium）。"""

from grep_analyzer.classifiers.regex_classifier import classify_groovy, classify_perl


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
    assert classify_groovy("def x = 1") == ("代入", "medium")       # def x= は代入(C-F)
    assert classify_groovy("def foo() {") == ("宣言", "medium")      # メソッド宣言
    assert classify_groovy("class Foo {") == ("宣言", "medium")
    assert classify_groovy("if (a == b) {") == ("比較", "medium")
    assert classify_groovy("switch (x) {") == ("分岐", "medium")
    assert classify_groovy("return v") == ("return", "medium")
    assert classify_groovy("println v") == ("出力", "medium")


def test_Groovy型付き宣言は初期化子があれば代入になる():
    # generics 同居でも = 優先で代入（設計 §9・§4.3）
    assert classify_groovy("List<String> xs = []") == ("代入", "medium")
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_classify.py -q`
Expected: FAIL（`classify_perl`/`classify_groovy` が未定義＝ImportError）。

- [ ] **Step 3: regex_classifier に規則表と分類関数を追加**

`src/grep_analyzer/classifiers/regex_classifier.py` の**ファイル先頭の import 群**に次を追加（mid-file import は規約違反＝coding-conventions）:

```python
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
```

そのうえで**ファイル末尾**に `_mask`・規則表・分類関数を追記（マスクは `MASK_PATTERNS` で内部適用＝chase 非依存・循環回避）:

```python
def _mask(language: str, line: str) -> str:
    pat = MASK_PATTERNS.get(language)
    return line if pat is None else pat.sub(lambda m: " " * len(m.group(0)), line)


# spec §4.2 Perl（先頭一致優先）。比較の裸 < > は -> / => / <= >= を除外。
_PERL_RULES = [
    (re.compile(r"^\s*sub\s+\w+|\bpackage\s+\w+|\buse\s+constant\b"), "宣言"),
    (re.compile(r"^\s*(?:my|our|local|state)\s+[$@%]|[$@%]\w+\s*=(?![=~>])"), "代入"),
    (re.compile(r"\b(?:if|unless|elsif)\b|==|!=|<=|>=|\beq\b|\bne\b|\blt\b|\bgt\b|\ble\b|"
                r"\bge\b|=~|!~|(?<![-=])<(?!=)|(?<![-=])>(?!=)"), "比較"),
    (re.compile(r"\b(?:for|foreach|while|until)\b"), "分岐"),
    (re.compile(r"\b(?:print|printf|say|warn|die)\b"), "出力"),
]
# spec §4.3 Groovy（先頭一致優先）。規則1の def はメソッド宣言形 `def name(` 限定。
_GROOVY_RULES = [
    (re.compile(r"^\s*(?:class|interface|enum|trait)\s+|"
                r"^\s*(?:[\w.<>,\s]+\s+)?def\s+\w+\s*\("), "宣言"),
    (re.compile(r"^\s*(?:def|final|[A-Za-z_]\w*(?:<[^>]*>)?)\s+\w+\s*=(?!=)|"
                r"\b\w+\s*=(?!=)"), "代入"),
    (re.compile(r"\b(?:if|while)\b|==~|<=>|==|!=|<=|>=|=~|"
                r"(?<![-=])<(?!=)|(?<![-=])>(?!=)"), "比較"),
    (re.compile(r"\b(?:switch|for|case)\b"), "分岐"),
    (re.compile(r"\breturn\b"), "return"),
    (re.compile(r"\b(?:println|print|printf)\b|\blog\.\w+"), "出力"),
]


def classify_perl(line: str) -> ClassifyResult:
    """Perl行を分類する（spec §4.2・confidence=medium・内部 mask）。"""
    return _apply(_PERL_RULES, _mask("perl", line))


def classify_groovy(line: str) -> ClassifyResult:
    """Groovy行を分類する（spec §4.3・confidence=medium・内部 mask）。"""
    return _apply(_GROOVY_RULES, _mask("groovy", line))
```

- [ ] **Step 4: classify_hit に分岐を追加**

`src/grep_analyzer/classify.py` を修正:

```python
from grep_analyzer.classifiers.base import ClassifyResult
from grep_analyzer.classifiers.regex_classifier import (
    classify_groovy,
    classify_perl,
    classify_shell,
    classify_sql,
)
from grep_analyzer.classifiers.ts_classifier import classify_ts


def classify_hit(
    language: str, dialect: str, file_text: str, lineno: int, content: str
) -> ClassifyResult:
    """1 ヒットを言語別に分類して (category, confidence) を返す（spec §7/§4）。"""
    if language in ("java", "c", "proc"):
        return classify_ts(language, file_text, lineno)
    if language == "sql":
        return classify_sql(content)
    if language == "perl":
        return classify_perl(content)
    if language == "groovy":
        return classify_groovy(content)
    if language == "shell":
        return classify_shell(content, dialect)
    return classify_shell(content, "bourne")
```

- [ ] **Step 5: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_classify.py tests/unit/test_chase.py -q`
Expected: PASS。

- [ ] **Step 6: 全テストで既存不変を確認**

Run: `python -m pytest -q`
Expected: PASS（Task 0 件数＋新規分）。既存 java/c/sql/shell 分類不変。

- [ ] **Step 7: コミット**

```bash
git add src/grep_analyzer/classifiers/regex_classifier.py src/grep_analyzer/classify.py tests/unit/test_classify.py
git commit -m "feat(classify): classify_perl/classify_groovy追加とclassify_hit分岐(設計§4.2/§4.3)"
```

---

## Task 6: PL/SQL 分類規則の行頭アンカー append（設計 §4.1／C-B）

**理由:** 既存 `_SQL_RULES`（生行・先頭一致）へ手続き型規則を末尾追加。出力を先頭、宣言/ループは行頭アンカーで行中・コメント・文字列内語の誤爆を回避。既存 sql golden の分類を変えない。

**Files:**
- Modify: `src/grep_analyzer/classifiers/regex_classifier.py:12-17`
- Test: `tests/unit/test_classify.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_classify.py` に追記:

```python
from grep_analyzer.classifiers.regex_classifier import classify_sql


def test_PLSQL手続き型分類():
    assert classify_sql("PROCEDURE do_x IS") == ("宣言", "medium")
    assert classify_sql("  FUNCTION calc RETURN NUMBER IS") == ("宣言", "medium")
    assert classify_sql("IF v_x > 0 THEN") == ("比較", "medium")
    assert classify_sql("WHILE i < 10 LOOP") == ("分岐", "medium")
    assert classify_sql("DBMS_OUTPUT.PUT_LINE('hi');") == ("出力", "medium")


def test_PLSQL誤爆回避():
    # 行頭でない手続き型語・文字列内語は誤分類しない（C-B）
    assert classify_sql("DBMS_OUTPUT.PUT_LINE('FUNCTION x');") == ("出力", "medium")
    assert classify_sql("OPEN c FOR SELECT 1 FROM dual;") == ("分岐", "medium")  # 既存規則?
```

注: 2行目 `OPEN c FOR SELECT …` は `FOR` が行頭でないため新ループ規則は不発。既存規則にも該当しないため期待は「その他」になるはず。**Step 3 の規則確定後に実際の出力で期待値を確定**する（下記参照）。

- [ ] **Step 2: 実際の分類を確認して期待値を確定**

Run（規則追加前に現状を確認）: `python -c "from grep_analyzer.classifiers.regex_classifier import classify_sql; print(classify_sql('OPEN c FOR SELECT 1 FROM dual;'))"`
Expected: `('その他', 'medium')`。これに合わせ Step 1 の `OPEN c FOR …` の期待を `("その他", "medium")` に修正する（誤爆しないことの確認＝分岐にならない）。

- [ ] **Step 3: _SQL_RULES に行頭アンカー規則を append**

`regex_classifier.py` の `_SQL_RULES` を修正（規則1-4 は不変・末尾に5-9 を追加）:

```python
_SQL_RULES = [
    (re.compile(r":="), "代入"),
    (re.compile(r"\bWHERE\b.*?[=<>]", re.IGNORECASE), "比較"),
    (re.compile(r"\bCASE\s+WHEN\b|\bDECODE\s*\(|\|\|", re.IGNORECASE), "分岐"),
    (re.compile(r"\b(?:INSERT|UPDATE)\b", re.IGNORECASE), "代入"),
    # --- PL/SQL append（設計 §4.1・出力先頭・宣言/ループ行頭アンカー） ---
    (re.compile(r"^\s*(?:DBMS_OUTPUT\.PUT_LINE|RAISE_APPLICATION_ERROR)\b", re.IGNORECASE), "出力"),
    (re.compile(r"^\s*(?:CREATE\s+(?:OR\s+REPLACE\s+)?)?"
                r"(?:PROCEDURE|FUNCTION|PACKAGE(?:\s+BODY)?|TRIGGER|TYPE)\b", re.IGNORECASE), "宣言"),
    (re.compile(r"^\s*CURSOR\b", re.IGNORECASE), "宣言"),
    (re.compile(r"\bIF\b.*\bTHEN\b|^\s*ELSIF\b", re.IGNORECASE), "比較"),
    (re.compile(r"^\s*(?:WHILE|FOR)\b|\bLOOP\s*$", re.IGNORECASE), "分岐"),
]
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_classify.py -q`
Expected: PASS（Step 2 で確定した期待値で）。

- [ ] **Step 5: 既存 sql golden が byte 不変であることを確認（Inv-B）**

Run: `python -m pytest tests/golden -q`
Expected: PASS（既存 `oracle_direct`/`sql_direct`/`multiline_where` 等が byte 不変）。万一 diff が出たら append 規則が既存行を拾っている＝規則を見直す。

- [ ] **Step 6: コミット**

```bash
git add src/grep_analyzer/classifiers/regex_classifier.py tests/unit/test_classify.py
git commit -m "feat(classify): PL/SQL手続き型規則を行頭アンカーでappend(設計§4.1 C-B・Inv-B保持)"
```

---

## Task 7: dispatch の拡張子追加とシェバン一般化（設計 §3.1/§3.2／C-H・I-6）

**Files:**
- Modify: `src/grep_analyzer/dispatch.py`
- Test: `tests/unit/test_dispatch.py`（既存 perl 期待を改訂＋新規）

- [ ] **Step 1: 失敗するテスト＋既存テスト改訂を書く**

`tests/unit/test_dispatch.py` を修正:
- 既存 `test_拡張子なし非シェルシェバンはshellにしない`（70行目）を**改訂**（perl は track B で perl に昇格）:

```python
def test_拡張子なしperlシェバンはperlと判定する():
    # v2(track B): perl は新 language。版番号付き basename も剥がして解決(I-6)。
    assert detect_language("bin/tool", "#!/usr/bin/perl\nmy $x=1;\n", {}) == "perl"
    assert detect_language("bin/t2", "#!/usr/bin/perl5.36\n", {}) == "perl"
    assert detect_language("bin/t3", "#!/usr/bin/env groovy\n", {}) == "groovy"


def test_拡張子なしpythonシェバンは未対応でcフォールバック():
    # python は track A 未着手＝Shell/perl/groovy に昇格しない(設計 §3.2)
    assert detect_language("bin/p", "#!/usr/bin/python3\nx=1\n", {}) == "c"
```

- 拡張子マップ新規:

```python
def test_新拡張子の言語判定():
    assert detect_language("a/pkg.pkb", "", {}) == "sql"
    assert detect_language("a/spec.pks", "", {}) == "sql"
    assert detect_language("a/s.pl", "", {}) == "perl"
    assert detect_language("a/M.pm", "", {}) == "perl"
    assert detect_language("a/b.groovy", "", {}) == "groovy"
    assert detect_language("a/build.gradle", "", {}) == "groovy"


from grep_analyzer.dispatch import shebang_language


def test_shebang_languageは対応言語かNoneを返す():
    assert shebang_language("#!/bin/sh\n") == "shell"
    assert shebang_language("#!/usr/bin/perl\n") == "perl"
    assert shebang_language("#!/usr/bin/env groovy\n") == "groovy"
    assert shebang_language("#!/usr/bin/python3\n") is None   # 未対応
    assert shebang_language("X=1\n") is None                  # シェバン無し
```

注: 既存 `test_非シェルシェバンはotherを返す`（45-47行）の `shebang_dialect("#!/usr/bin/perl\n")=="other"` は**不変**（`shebang_dialect` は shell 副方言専用＝触らない）。perl が "other" を返すのは設計どおり。

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_dispatch.py -q -k "perl or python or 新拡張子 or shebang_language"`
Expected: FAIL（拡張子未登録／`shebang_language` 未定義）。

- [ ] **Step 3: dispatch.py を修正**

`src/grep_analyzer/dispatch.py`:
- `_EXT_MAP` に追記:

```python
_EXT_MAP = {
    ".java": "java",
    ".sql": "sql",
    ".pkb": "sql", ".pks": "sql", ".prc": "sql", ".fnc": "sql",
    ".trg": "sql", ".pls": "sql", ".plb": "sql",
    ".sh": "shell", ".ksh": "shell", ".bash": "shell",
    ".csh": "shell", ".tcsh": "shell",
    ".pc": "proc",
    ".c": "c", ".h": "c",
    ".pl": "perl", ".pm": "perl", ".t": "perl",
    ".groovy": "groovy", ".gvy": "groovy", ".gradle": "groovy",
}
```

- interpreter→言語マップと `shebang_language` を新設（`shebang_dialect` は不変・版剥がし共有ヘルパ）:

```python
_SHEBANG_LANG = {
    "sh": "shell", "bash": "shell", "ksh": "shell", "dash": "shell",
    "csh": "shell", "tcsh": "shell", "perl": "perl", "groovy": "groovy",
}
_VERSION_SUFFIX_RE = re.compile(r"\d[\d.]*$")


def _shebang_interp(content_sample: str) -> str | None:
    """第1物理行のシェバンから interpreter basename（版番号剥がし）を返す。"""
    first_line = content_sample.split("\n", 1)[0]
    m = _SHEBANG_RE.match(first_line)
    if m is None:
        return None
    interp = m.group(1).rsplit("/", 1)[-1]
    if interp == "env" and m.group(2):
        interp = m.group(2).rsplit("/", 1)[-1]
    return _VERSION_SUFFIX_RE.sub("", interp) or interp


def shebang_language(content_sample: str) -> str | None:
    """第1物理行のシェバンを対応言語（shell/perl/groovy）か None に解決する。"""
    interp = _shebang_interp(content_sample)
    return None if interp is None else _SHEBANG_LANG.get(interp)
```

- `detect_language` の未確定分岐を `shebang_language` で拡張（shell だけでなく perl/groovy へ）:

```python
    # 拡張子が未知または無い: シェバン解決（手順3）→ EXEC SQL（手順4）→ c（手順5）
    sl = shebang_language(content_sample)
    if sl is not None:
        return sl
    if _EXEC_SQL_RE.search(content_sample):
        return "proc"
    return "c"
```

注: `shebang_dialect`（既存）は `_shebang_interp` を使うよう内部リファクタしてよいが、戻り値契約（bourne/cshell/other/None）は不変に保つこと。最小変更なら `shebang_dialect` は現状のまま残置で可。

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_dispatch.py -q`
Expected: PASS（新規＋改訂＋既存 shell/csh すべて）。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/dispatch.py tests/unit/test_dispatch.py
git commit -m "feat(dispatch): perl/groovy拡張子とシェバン一般化(版剥がし・python据置 設計§3.1/§3.2)"
```

---

## Task 8: pipeline の unsupported_shebang 条件を一意化（設計 §3.2／C-H）

**Files:**
- Modify: `src/grep_analyzer/pipeline.py:14-17,84-89`
- Test: `tests/integration/test_pipeline_dialect.py`（perl フィクスチャを python へ移植）

- [ ] **Step 1: 既存テストを改訂＋新規を書く**

`tests/integration/test_pipeline_dialect.py` の `unsupported_shebang` フィクスチャを**改訂**（perl は解決するので python/awk に移植）。実ファイルの当該テスト（24-47行付近）を次の主旨へ:

```python
def test_拡張子なしpythonシェバンはunsupported_shebangを診断に出す(tmp_path):
    # perl/groovy は track B で解決＝診断対象から外れる。python は未対応で診断。
    # （既存 perl フィクスチャからの移植・設計 §3.2/§9）
    ...  # 既存テストの "#!/usr/bin/perl" を "#!/usr/bin/python3" に置換し
        # 期待診断 unsupported_shebang を維持


def test_拡張子なしperlシェバンはunsupported_shebangを出さない(tmp_path):
    # perl は language=perl に解決＝診断しない（誤記録回帰防止・C-H）
    ...  # "#!/usr/bin/perl" のファイルで unsupported_shebang が診断に無いこと
```

（注: 既存テストの構造＝grep/source 配置・`run` 呼び出し・diagnostics 読取をそのまま流用し、interpreter 文字列と期待のみ差し替える。既存 `.c`＋perl シェバンの「診断しない」負契約テストがあれば、`extension_resolves_language` ガードで不変＝そのまま green。）

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/integration/test_pipeline_dialect.py -q`
Expected: FAIL（perl が解決され誤って unsupported_shebang を出す＝旧条件 `language != "shell"` のため）。

- [ ] **Step 3: pipeline.py の条件を一意化**

`src/grep_analyzer/pipeline.py` の import に `shebang_language` を追加し、条件式を差し替え:

```python
from grep_analyzer.dispatch import (
    detect_language,
    detect_shell_dialect,
    extension_resolves_language,
    shebang_dialect,
    shebang_language,
)
```

条件部（84-89行）:

```python
            if (
                not extension_resolves_language(relpath, lang_map)
                and shebang_dialect(sample) is not None      # シェバン行が存在
                and shebang_language(sample) is None         # 対応言語に解決しない
            ):
                diag.add("unsupported_shebang", str(relpath))
```

注: `shebang_dialect(sample) is not None` は「シェバン行あり」を表す（None=シェバン無し）。perl/groovy は `shebang_language` が解決＝記録されない。python/awk は `shebang_language==None ∧ shebang_dialect=="other"` で記録。既知拡張子＋perl シェバンは第1項 False で不変。

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/integration/test_pipeline_dialect.py -q`
Expected: PASS。

- [ ] **Step 5: 全テストで既存不変を確認**

Run: `python -m pytest -q`
Expected: PASS。

- [ ] **Step 6: コミット**

```bash
git add src/grep_analyzer/pipeline.py tests/integration/test_pipeline_dialect.py
git commit -m "fix(pipeline): unsupported_shebang条件を一意化しperl/groovy誤記録を防止(設計§3.2 C-H)"
```

---

## Task 9: snippet の perl/groovy 対応（設計 §6）

**Files:**
- Modify: `src/grep_analyzer/patterns/snippet_boundaries.py`
- Modify: `src/grep_analyzer/snippet/_heuristic.py:37-45`
- Modify: `src/grep_analyzer/snippet/__init__.py:49`
- Test: `tests/unit/test_snippet_heuristic.py`（新規 or 既存へ追記）

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_snippet_heuristic.py`（新規）:

```python
"""perl/groovy ヒューリスティック snippet 境界（spec §6）。"""

from grep_analyzer.snippet import build_snippet


def test_perlのsnippetは文末セミコロンで境界を取る():
    src = "sub f {\n    my $x = 1;\n    return $x;\n}\n"
    out = build_snippet("perl", "bourne", src, 2)   # my $x = 1; の行
    assert "my $x = 1;" in out


def test_groovyのsnippetは波括弧で境界を取る():
    src = "class A {\n    def run() {\n        def x = compute()\n    }\n}\n"
    out = build_snippet("groovy", "bourne", src, 3)
    assert "def x = compute()" in out
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_snippet_heuristic.py -q`
Expected: FAIL or 1行のみ（perl/groovy が `build_snippet` の heuristic 分岐に入らず `(hit,hit)` フォールバックになる）。

- [ ] **Step 3: snippet 境界 regex を追加**

`src/grep_analyzer/patterns/snippet_boundaries.py` に追記:

```python
PERL_TERMINATOR_RE = re.compile(r";|}|^\s*sub\b")
GROOVY_TERMINATOR_RE = re.compile(r";|}|^\s*(?:class|def)\b")
```

- [ ] **Step 4: _heuristic.stop() を分岐化（shell return をガード化）**

`src/grep_analyzer/snippet/_heuristic.py` の import と `stop()` を修正:

```python
from grep_analyzer.patterns.snippet_boundaries import (
    GROOVY_TERMINATOR_RE,
    PERL_TERMINATOR_RE,
    SH_TERMINATOR_RE,
    SQL_CLAUSE_RE,
)
```

```python
    def stop(i: int) -> bool:
        x = masked_lines[i]
        if x.rstrip().endswith("\\"):
            return False
        if not _balanced(x):
            return False
        if language == "sql":
            return x.rstrip().endswith(";") or bool(SQL_CLAUSE_RE.search(x))
        if language == "perl":
            return bool(PERL_TERMINATOR_RE.search(x))
        if language == "groovy":
            return bool(GROOVY_TERMINATOR_RE.search(x))
        return bool(SH_TERMINATOR_RE.search(x))   # shell（明示ガードは不要だが既定）
```

注: shell は末尾 return のまま（既存挙動 literal 不変＝Inv-B (d)）。perl/groovy は手前の elif で受けるため shell return に到達しない。

- [ ] **Step 5: build_snippet の言語分岐に perl/groovy を追加（独立 elif）**

`src/grep_analyzer/snippet/__init__.py` の分岐を修正:

```python
    elif language in ("sql", "shell", "perl", "groovy"):
        span = heuristic_span(lines, hit, language)
```

注: sql/shell の挙動は不変（同じ `heuristic_span` 呼び出し）。perl/groovy が同分岐に加わるが `heuristic_span` 内 `stop()` が言語別に分岐するため干渉なし。

- [ ] **Step 6: テストが通ることを確認＋既存 snippet golden 不変**

Run: `python -m pytest tests/unit/test_snippet_heuristic.py tests/golden -q`
Expected: PASS（新規＋既存 golden byte 不変）。

- [ ] **Step 7: コミット**

```bash
git add src/grep_analyzer/patterns/snippet_boundaries.py src/grep_analyzer/snippet/_heuristic.py src/grep_analyzer/snippet/__init__.py tests/unit/test_snippet_heuristic.py
git commit -m "feat(snippet): perl/groovyのヒューリスティック境界を追加(stop分岐化 設計§6)"
```

---

## Task 10: golden ケース（言語×ref_kind）と統合（設計 §9）

**理由:** 言語×ref_kind を golden で固定。golden は `input/<kw>.grep` ＋ `src/<files>` ＋ `expected/<kw>.tsv`（BOM 付・`{SOURCE_ROOT}` プレースホルダ・snippet は ` \n ` 連結）で構成。expected は**ツールを実行して生成し目視検証してから確定**する（手書きで byte を当てない）。

**Files（各ケースに input/src/expected を作成）:**
- Create: `tests/golden/cases/perl_direct/{input/P.grep,src/p.pl,expected/P.tsv}`
- Create: `tests/golden/cases/perl_indirect_var/{...}`
- Create: `tests/golden/cases/groovy_direct/{...}`
- Create: `tests/golden/cases/groovy_indirect_const/{...}`
- Create: `tests/golden/cases/plsql_proc/{...}`

- [ ] **Step 1: perl_direct ケースの input/src を作成**

`tests/golden/cases/perl_direct/src/p.pl`:

```perl
my $CODE = "X";
print "value=$CODE\n";
```

`tests/golden/cases/perl_direct/input/CODE.grep`:

```
p.pl:1:my $CODE = "X";
p.pl:2:print "value=$CODE\n";
```

- [ ] **Step 2: ツールを実行して expected を生成**

Run:
```bash
cd /workspaces/grep_helpers2
python -m grep_analyzer --input tests/golden/cases/perl_direct/input \
  --output /tmp/g_perl --source-root tests/golden/cases/perl_direct/src
```
生成された `/tmp/g_perl/CODE.tsv` を目視確認: language=perl・direct/indirect 行・category（代入/出力）・snippet が期待どおりか。

- [ ] **Step 3: expected/CODE.tsv を保存（{SOURCE_ROOT} 置換）**

生成 TSV の `file` 列の絶対 source-root を `{SOURCE_ROOT}` に置換して `tests/golden/cases/perl_direct/expected/CODE.tsv` に保存:
```bash
mkdir -p tests/golden/cases/perl_direct/expected
SR=$(python -c "from pathlib import Path; print(Path('tests/golden/cases/perl_direct/src').resolve())")
sed "s#${SR}/#{SOURCE_ROOT}/#g" /tmp/g_perl/CODE.tsv > tests/golden/cases/perl_direct/expected/CODE.tsv
```
保存後、`expected/CODE.tsv` を目視で最終確認（BOM・タブ・snippet の ` \n ` 連結・行順）。

- [ ] **Step 4: golden テストで一致を確認**

Run: `python -m pytest tests/golden -q -k perl_direct`
Expected: PASS。

- [ ] **Step 5: 残りのケースを同手順で作成**

同じ Step 1-4 の手順で:
- `perl_indirect_var`: src に `my $CODE = base();` と別行で `$CODE` 使用＋seed が `base` を経由するケース（多ホップ＝indirect:var の chain を固定）。input の keyword は追跡対象の値。
- `groovy_direct`: `def CODE = "X"` ＋ `println CODE`。
- `groovy_indirect_const`: `final CODE = "X"` を定義し別箇所で参照（indirect:constant）。
- `plsql_proc`: `.pkb` で `PROCEDURE`/`v_x NUMBER := KW;`/`DBMS_OUTPUT.PUT_LINE` を含み、宣言/代入/出力 category と CONSTANT/型名非抽出を固定。

各ケースとも「実行→目視検証→{SOURCE_ROOT}置換保存→golden green」。

- [ ] **Step 6: 統合テストを追加**

`tests/integration/test_v2_langs.py`（新規）で perl/groovy/plsql 混在ツリーを1回の `run` で処理し、各 language のヒットが TSV に出ることを確認:

```python
"""v2 正規表現トラック言語の統合（perl/groovy/plsql 混在）。"""

from grep_analyzer.pipeline import _default_opts, run


def test_perl_groovy_plsql混在を1実行で処理する(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.pl").write_text('my $CODE = "X";\n', "utf-8")
    (src / "b.groovy").write_text('def CODE = "X"\n', "utf-8")
    (src / "c.pkb").write_text("v_CODE VARCHAR2(10) := 'X';\n", "utf-8")
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "CODE.grep").write_text(
        'a.pl:1:my $CODE = "X";\nb.groovy:1:def CODE = "X"\n'
        "c.pkb:1:v_CODE VARCHAR2(10) := 'X';\n", "utf-8")
    out = tmp_path / "out"
    assert run(input_dir=inp, output_dir=out, source_root=src, opts=_default_opts()) == 0
    tsv = (out / "CODE.tsv").read_text("utf-8-sig")
    assert "\tperl\t" in tsv and "\tgroovy\t" in tsv and "\tsql\t" in tsv
```

- [ ] **Step 7: golden と統合をまとめて確認**

Run: `python -m pytest tests/golden tests/integration/test_v2_langs.py -q`
Expected: PASS。

- [ ] **Step 8: コミット**

```bash
git add tests/golden/cases/perl_direct tests/golden/cases/perl_indirect_var tests/golden/cases/groovy_direct tests/golden/cases/groovy_indirect_const tests/golden/cases/plsql_proc tests/integration/test_v2_langs.py
git commit -m "test(golden): perl/groovy/plsql の言語×ref_kind golden と統合を追加(設計§9)"
```

---

## Task 11: Inv-B 最終検証と全スイート green（設計 §8）

**Files:** （変更なし・検証のみ）

- [ ] **Step 1: 全テストを実行**

Run: `python -m pytest -q`
Expected: 全 PASS。件数 = Task 0 基準 ＋ 本計画で追加した件数。既存テストの赤化ゼロ（Task 7/8 の意図的改訂を除く）。

- [ ] **Step 2: 既存 v1 golden が byte 不変であることを最終確認（Inv-B）**

Run: `python -m pytest tests/golden -q`
Expected: 全 PASS。新規 v2 ケース以外の既存 golden（java/c/proc/sql/shell）が byte 一致。

- [ ] **Step 3: Inv-B 補完ゲート（diff 死角＝複数代入回帰）を確認**

Run: `python -m pytest tests/unit/test_chase.py -q -k "複数代入 or 同一行複数"`
Expected: PASS（`a := 1; b := 2;`→`["a","b"]` が温存）。

- [ ] **Step 4: 設計書 §10 のマスター反映を実施**

設計書 §10 に従い、本サブプロジェクト完了をマスター設計 `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md` の §2.3/§14（v2 対応済）・§15（フェーズ5 完了）へ追記する。

```bash
git add docs/superpowers/specs/2026-05-16-grep-analyzer-design.md
git commit -m "docs(spec): マスター§2.3/§14/§15にv2正規表現トラック(PL/SQL・Perl・Groovy)完了を反映"
```

- [ ] **Step 5: perf 非影響の確認（非ゲート）**

Run: `python -m pytest tests/perf -q` （あれば）
Expected: 大きな回帰なし（正規表現追加のみ＝`_ITEMS_PER_MB` 再測定不要・設計 §9）。

---

## 完了基準（設計 §8 Inv-B ＋ §9 必須回帰）

- 全 unit/golden/integration green（既存赤化ゼロ＝Task 7/8 意図的改訂を除く）。
- 既存 v1 golden byte 不変（Task 11 Step 2）。
- 複数代入回帰温存（Task 11 Step 3）。
- 言語×ref_kind golden 網羅（Task 10）。
- マスター設計へ完了反映（Task 11 Step 4）。
