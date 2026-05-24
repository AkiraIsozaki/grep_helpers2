# `コメント` カテゴリ新設 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 分類で `その他`／親文カテゴリに丸められているコメント専用行を、新カテゴリ `コメント`（confidence=low）へ分離する。

**Architecture:** 設計 `docs/superpowers/specs/2026-05-24-comment-category-design.md`。AST 系（`classify_ts`）は `node.type.endswith("comment")` で判定、正規表現系（`classify_sql/shell/perl/groovy`）は行頭アンカーのコメント規則を各 classify_* 先頭で判定（perl/groovy は mask 前の生行、SQL は Oracle ヒント `--+`/`/*+` を除外）。期待値は実 run を凍結（characterization）。

**Tech Stack:** Python 3.12 / pytest / tree-sitter / `grep_analyzer`。

**前提:**
- 既存テスト `tests/unit/test_regex_classifier.py:22-23`（`test_該当規則がなければその他と判定する`）は `classify_sql("-- just a comment") == ("その他","medium")` を assert しており、本変更で**コメント判定に変わるため更新が必要**（Task 2）。
- golden 影響は実測済で `messy_c_legacy`(2行)・`grep_jar_artifact`(1行) のみ（設計 §6）。
- `category`/`confidence` は出力メタのみで chase/resume に非影響（レビュー実証）。
- 作業ブランチ: main 直接（ソロ・許可済）。

---

## File Structure

| ファイル | 役割 | 操作 |
|---|---|---|
| `src/grep_analyzer/classifiers/ts_classifier.py` | `classify_ts` に comment ノード分岐を追加 | 変更 |
| `src/grep_analyzer/classifiers/regex_classifier.py` | 4 言語の classify_* にコメント判定を追加 | 変更 |
| `tests/unit/test_ts_classifier.py` | AST コメント分類テスト | 変更 |
| `tests/unit/test_regex_classifier.py` | sql/shell コメント＋ヒント負テスト＋既存その他テスト更新 | 変更 |
| `tests/unit/test_classify.py` | perl/groovy コメント＋classify_hit 統合 | 変更 |
| `tests/golden/cases/messy_c_legacy/expected/777.tsv` | 再生成（2行 → コメント/low） | 変更 |
| `tests/golden/cases/grep_jar_artifact/expected/777.tsv` | 再生成（1行 → コメント/low） | 変更 |
| `tests/golden/cases/sql_comment/**` | 新規 golden（正規表現 end-to-end） | 作成 |
| `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md` | §9/§8.3/§8.4 反映 | 変更 |
| `tests/golden/cases/README.md` | 注記更新 | 変更 |

---

## Task 1: AST 系コメント判定（`classify_ts`）

**Files:**
- Test: `tests/unit/test_ts_classifier.py`
- Modify: `src/grep_analyzer/classifiers/ts_classifier.py`

- [ ] **Step 1: 失敗するテストを追加**（`tests/unit/test_ts_classifier.py` 末尾に追記）

```python
def test_コメント行はコメントlowと判定する_各AST言語():
    # java は line_comment / block_comment、他は comment ノード
    assert classify_ts("java", "class A {\n // 777\n}\n", 2) == ("コメント", "low")
    assert classify_ts("java", "class A {\n /* 777 */\n}\n", 2) == ("コメント", "low")
    assert classify_ts("c", "int x;\n// 777\n", 2) == ("コメント", "low")
    assert classify_ts("c", "int x;\n/* 777 */\n", 2) == ("コメント", "low")
    assert classify_ts("python", "# 777\nx = 1\n", 1) == ("コメント", "low")
    assert classify_ts("javascript", "// 777\nconst x = 1;\n", 1) == ("コメント", "low")
    assert classify_ts("typescript", "// 777\nconst x = 1;\n", 1) == ("コメント", "low")


def test_文ブロック内ネストコメントもコメントになる():
    # 従来は climb で if_statement に到達し 比較 になっていた行
    src = "class A {\n void m(int x){\n  if (x == 1) {\n   // 777\n  }\n }\n}\n"
    assert classify_ts("java", src, 4) == ("コメント", "low")


def test_コード同居行はコメントにせずコード分類():
    # 末尾コメント同居行は最小葉がコード側ゆえ従来通り宣言
    assert classify_ts("java", 'class A {\n int x = 1; // 777\n}\n', 2) == ("宣言", "high")
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest tests/unit/test_ts_classifier.py::test_コメント行はコメントlowと判定する_各AST言語 -v`
Expected: FAIL（現状はコメント行が `その他`/親文カテゴリを返す）

- [ ] **Step 3: `classify_ts` に comment 分岐を追加**

`src/grep_analyzer/classifiers/ts_classifier.py` の `classify_ts`（現 148-158 行）を次へ置換:

```python
def classify_ts(language: str, source: str, lineno: int) -> ClassifyResult:
    """ファイル全体を AST 解析し、対象行を含む構文要素から分類する。"""
    src = host_source(language, source)
    tree = _parser(language).parse(src.encode("utf-8"))
    node = node_at_line(tree.root_node, lineno)
    # コメント専用行（最小ノードが comment）は climb 前に短絡（spec §7・コメントカテゴリ）。
    # java=line_comment/block_comment、他=comment を endswith で一律カバー。
    if node is not None and node.type.endswith("comment"):
        return ("コメント", "low")
    while node is not None:
        cat = _CATEGORY_BY_LANG[language].get(node.type)
        if cat is not None:
            return (cat, "high")
        node = node.parent
    return ("その他", "high")
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest tests/unit/test_ts_classifier.py -v`
Expected: 全 PASS（新3件＋既存）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/classifiers/ts_classifier.py tests/unit/test_ts_classifier.py
git commit -m "feat(classify): AST系でコメント専用行を コメント/low に分類(spec §7)"
```

---

## Task 2: 正規表現系コメント判定（`classify_sql/shell/perl/groovy`）

**Files:**
- Test: `tests/unit/test_regex_classifier.py`（sql/shell＋ヒント負＋既存更新）, `tests/unit/test_classify.py`（perl/groovy）
- Modify: `src/grep_analyzer/classifiers/regex_classifier.py`

- [ ] **Step 1: 失敗するテストを追加し、既存テストを更新**

`tests/unit/test_regex_classifier.py` の `test_該当規則がなければその他と判定する`（22-23 行）を次へ**置換**（`--` 始まりはコメントになるため非コメントの fallthrough 行へ変更）:

```python
def test_該当規則がなければその他と判定する():
    assert classify_sql("SELECT 1 FROM dual") == ("その他", "medium")
```

同ファイル末尾に追記:

```python
def test_SQLのコメント行はコメントlow():
    assert classify_sql("-- comment 777") == ("コメント", "low")
    assert classify_sql("  -- indented") == ("コメント", "low")
    assert classify_sql("/* block 777 */") == ("コメント", "low")


def test_SQLのOracleヒント句はコメントにしない():
    # /*+ ... */ ・ --+ ... は最適化指示でコメントではない（その他へ）
    assert classify_sql("/*+ INDEX(t idx) */") == ("その他", "medium")
    assert classify_sql("--+ INDEX(t idx)") == ("その他", "medium")


def test_SQLの同居コメントはコード優先():
    assert classify_sql("WHERE col = 'X' -- trailing") == ("比較", "medium")


def test_Shellのコメント行はコメントlow():
    assert classify_shell("# comment 777") == ("コメント", "low")
    assert classify_shell("  # indented") == ("コメント", "low")
    assert classify_shell("# cshell comment", "cshell") == ("コメント", "low")
```

`tests/unit/test_classify.py` 末尾に追記:

```python
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
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest tests/unit/test_regex_classifier.py::test_SQLのコメント行はコメントlow tests/unit/test_classify.py::test_Perlのコメント行はコメントlow -v`
Expected: FAIL（現状はコメント行が `その他` を返す）

- [ ] **Step 3: `regex_classifier.py` にコメント判定を追加**

`src/grep_analyzer/classifiers/regex_classifier.py` の `classify_sql`/`classify_shell`（46-57 行）と `classify_perl`/`classify_groovy`（88-95 行）を次の形へ変更し、コメント正規表現を定義する。`classify_sql` の直前（45 行 `_apply` 定義の後）に追加:

```python
# spec §7 コメントカテゴリ。行頭アンカーで純コメント行のみ（同居行はコード優先）。
# Oracle ヒント句 /*+ ... */ ・ --+ ... は最適化指示でコメントではない（(?!\+) で除外）。
_SQL_COMMENT = re.compile(r"^\s*--(?!\+)|^\s*/\*(?!\+).*\*/\s*$")
_SHELL_COMMENT = re.compile(r"^\s*#")
_PERL_COMMENT = re.compile(r"^\s*#")
_GROOVY_COMMENT = re.compile(r"^\s*//|^\s*/\*.*\*/\s*$")
```

`classify_sql` を:

```python
def classify_sql(line: str) -> ClassifyResult:
    """SQL行（Oracle方言）を分類する（spec §7・confidence=medium／コメントは low）。"""
    if _SQL_COMMENT.match(line):
        return ("コメント", "low")
    return _apply(_SQL_RULES, line)
```

`classify_shell` を:

```python
def classify_shell(line: str, dialect: str = "bourne") -> ClassifyResult:
    """Shell行を分類する（spec §7・confidence=medium／コメントは low）。

    dialect="cshell" のとき csh/tcsh 規則、それ以外（既定）は bourne 規則。
    """
    if _SHELL_COMMENT.match(line):
        return ("コメント", "low")
    rules = _SHELL_RULES_CSHELL if dialect == "cshell" else _SHELL_RULES_BOURNE
    return _apply(rules, line)
```

`classify_perl` を（コメント判定は mask 前の生行で）:

```python
def classify_perl(line: str) -> ClassifyResult:
    """Perl行を分類する（spec §4.2・confidence=medium／コメントは low・内部 mask）。"""
    if _PERL_COMMENT.match(line):
        return ("コメント", "low")
    return _apply(_PERL_RULES, _mask("perl", line))
```

`classify_groovy` を:

```python
def classify_groovy(line: str) -> ClassifyResult:
    """Groovy行を分類する（spec §4.3・confidence=medium／コメントは low・内部 mask）。"""
    if _GROOVY_COMMENT.match(line):
        return ("コメント", "low")
    return _apply(_GROOVY_RULES, _mask("groovy", line))
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest tests/unit/test_regex_classifier.py tests/unit/test_classify.py -v`
Expected: 全 PASS（更新した既存テスト＋新規）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/classifiers/regex_classifier.py tests/unit/test_regex_classifier.py tests/unit/test_classify.py
git commit -m "feat(classify): 正規表現系でコメント行を コメント/low に分類・Oracleヒント除外(spec §7)"
```

---

## Task 3: `classify_hit` 統合テスト

**Files:**
- Test: `tests/unit/test_classify.py`

- [ ] **Step 1: 統合テストを追加**（`tests/unit/test_classify.py` 末尾）

```python
def test_classify_hit_コメント統合_ASTとregex():
    # AST(java) 経路
    assert classify_hit("java", "", "class A {\n // 777\n}\n", 2, "// 777") == \
        ("コメント", "low")
    # regex(sql) 経路
    assert classify_hit("sql", "", "", 1, "-- 777 comment") == ("コメント", "low")
```

- [ ] **Step 2: テストが通ることを確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest tests/unit/test_classify.py::test_classify_hit_コメント統合_ASTとregex -v`
Expected: PASS（Task 1/2 実装済のため）

- [ ] **Step 3: コミット**

```bash
git add tests/unit/test_classify.py
git commit -m "test(classify): classify_hit 経由のコメント分類統合テスト"
```

---

## Task 4: 既存 golden 2 ケースを再生成

**Files:**
- Modify: `tests/golden/cases/messy_c_legacy/expected/777.tsv`, `tests/golden/cases/grep_jar_artifact/expected/777.tsv`

- [ ] **Step 1: 2 ケースを再生成**

```bash
cd /workspaces/grep_helpers2
python scripts/gen_golden_case.py tests/golden/cases/messy_c_legacy
python scripts/gen_golden_case.py tests/golden/cases/grep_jar_artifact --with-diag-summary
```

- [ ] **Step 2: diff が当該3行（category その他→コメント・confidence high→low）のみであることを確認**

Run: `cd /workspaces/grep_helpers2 && git diff tests/golden/cases/messy_c_legacy tests/golden/cases/grep_jar_artifact`
確認:
- `messy_c_legacy/expected/777.tsv`: legacy.c:1 と legacy.c:7 の行が `その他...high` → `コメント...low`。他行（legacy.c:3 比較、legacy.c:4 宣言）不変。
- `grep_jar_artifact/expected/777.tsv`: Main.java:2 が `その他...high` → `コメント...low`。Main.java:3（宣言）不変。`diagnostics_summary.txt` は差分なし。
- 他のファイルに差分が出ていないこと。

- [ ] **Step 3: 当該ケースの golden テストが通ることを確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest "tests/golden/test_golden.py::test_合成ケースのTSVが期待値と完全一致する[messy_c_legacy]" "tests/golden/test_golden.py::test_合成ケースのTSVが期待値と完全一致する[grep_jar_artifact]" -v`
Expected: 2 PASS

- [ ] **Step 4: コミット**

```bash
git add tests/golden/cases/messy_c_legacy tests/golden/cases/grep_jar_artifact
git commit -m "test(golden): コメントカテゴリ反映で messy_c_legacy/grep_jar_artifact を再生成(3行 コメント/low)"
```

---

## Task 5: 新規 golden ケース `sql_comment`（正規表現 end-to-end）

**Files:**
- Create: `tests/golden/cases/sql_comment/src/q.sql`, `tests/golden/cases/sql_comment/input/777.grep`, `tests/golden/cases/sql_comment/expected/777.tsv`（生成）

- [ ] **Step 1: fixture を作成**

```bash
cd /workspaces/grep_helpers2 && python - <<'PY'
from pathlib import Path
base = Path("tests/golden/cases/sql_comment")
(base/"src").mkdir(parents=True, exist_ok=True)
(base/"input").mkdir(parents=True, exist_ok=True)
(base/"src/q.sql").write_bytes(
    "-- 777 はステータスコードのコメント\n"
    "SELECT name FROM t WHERE code = '777';\n".encode("utf-8"))
(base/"input/777.grep").write_bytes(
    "q.sql:1:-- 777 はステータスコードのコメント\n"
    "q.sql:2:SELECT name FROM t WHERE code = '777';\n".encode("utf-8"))
print("fixtures written")
PY
```

- [ ] **Step 2: expected を生成して人手レビュー**

Run: `cd /workspaces/grep_helpers2 && python scripts/gen_golden_case.py tests/golden/cases/sql_comment`
レビュー基準:
- `expected/777.tsv` に 2 データ行＋ヘッダ。q.sql:1 が `category=コメント`・`confidence=low`、q.sql:2 が `category=比較`・`confidence=medium`。
- 確認: `cut -f3,4,6,13 tests/golden/cases/sql_comment/expected/777.tsv`（file/lineno/category/confidence）。

- [ ] **Step 3: 当該ケースの golden テストが通ることを確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest "tests/golden/test_golden.py::test_合成ケースのTSVが期待値と完全一致する[sql_comment]" -v`
Expected: PASS

- [ ] **Step 4: コミット**

```bash
git add tests/golden/cases/sql_comment
git commit -m "test(golden): sql_comment — 正規表現系コメント分類の end-to-end 固定(コメント/low)"
```

---

## Task 6: 本体 spec ＋ README 反映

**Files:**
- Modify: `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`（§9 line 152・§8.3 confidence・§8.4）
- Modify: `tests/golden/cases/README.md`

- [ ] **Step 1: spec §9 taxonomy（line 152）にコメントを追記**

`docs/superpowers/specs/2026-05-16-grep-analyzer-design.md` の line 152（`category` は**二層**…）の文末に追記:

```
（2026-05-24）上位に **`コメント`**（コメント専用行・confidence=low）を追加。上位カテゴリは「コードの意味的役割」に加え「ソース種別（コメント）」を含む上位分類へ概念拡張する。判定: AST はコメントノード（java=line/block_comment・他=comment）、正規表現は行頭コメント規則（SQL は Oracle ヒント `--+`/`/*+` を除外）。コメント専用行のみ（コード同居行はコード優先）。回帰は `tests/golden/cases/sql_comment`・`messy_c_legacy`・`grep_jar_artifact`。
```

- [ ] **Step 2: spec confidence 定義（§8.3 付近）に追記**

Run: `cd /workspaces/grep_helpers2 && grep -n "confidence" docs/superpowers/specs/2026-05-16-grep-analyzer-design.md | head` で confidence の定義行を特定し、`low` を説明している箇所（getter/setter 型解決の文脈）に次の一文を追記:

```
（2026-05-24）`confidence=low` の意味を「当該行が keyword の真のコード使用である確信度が低い」と一本化する＝① 型解決を要する間接（getter/setter）＝既存、② 非コード行（`コメント` カテゴリ）＝追加。`confidence=low` フィルタの一貫性を保つ。
```

該当が `low` を明示する箇所に見当たらない場合は、§9 の `confidence` 列説明行（`grep -n "confidence" ...` で特定）に同文を追記する。

- [ ] **Step 3: spec §8.4 既知限界に追記**

`grep -n "8.4\|既知の取りこぼし" docs/superpowers/specs/2026-05-16-grep-analyzer-design.md` で §8.4 の箇所を特定し、その節の末尾付近に追記:

```
- **コメント分類の限界（2026-05-24）**: (1) 正規表現系（sql/perl/groovy/shell）の複数行ブロックコメント `/* … */` の中間行は行単位判定ゆえ非検出（`その他` 据置。AST 系は全行 `コメント`）。(2) jsp/angular/angular_inline は逆マスク後のホスト言語（Java/TS）スタイルコメントのみ検出。HTML/JSP スタイル（`<!-- -->`・`<%-- --%>`）は host 空白化で非検出。HTML 言語はコメント分類スコープ外（`その他` 固定）。(3) perl `^\s*#` は POD（`=pod`〜`=cut`）・heredoc 本文中の `#` 始まり行を `コメント` と誤判定し得る。(4) Oracle ヒント句 `--+ …`・`/*+ … */`（単独行）は `(?!\+)` で `コメント` から除外し通常分類とする。
```

- [ ] **Step 4: `tests/golden/cases/README.md` を更新**

`messy_c_legacy` 行の「固定する挙動」に「コメント行(1,7)は `コメント/low`」、`grep_jar_artifact` 行に「Main.java:2 は `コメント/low`」を追記し、新規行 `sql_comment | ② / コメント | SQL の `--` コメント行を `コメント/low`、コード行を `比較/medium` に固定（正規表現系 end-to-end）` を表へ追加する。

- [ ] **Step 5: コミット**

```bash
git add docs/superpowers/specs/2026-05-16-grep-analyzer-design.md tests/golden/cases/README.md
git commit -m "docs(spec): §9 にコメントカテゴリ・§8.3 confidence一本化・§8.4 限界を反映"
```

---

## Task 7: 最終検証

**Files:** なし（検証のみ）

- [ ] **Step 1: golden 全体（46 件）**

Run: `cd /workspaces/grep_helpers2 && python -m pytest tests/golden -q`
Expected: `46 passed`（既存45 ＋ `sql_comment`）

- [ ] **Step 2: ユニット全体**

Run: `cd /workspaces/grep_helpers2 && python -m pytest tests/unit -q`
Expected: 全 PASS

- [ ] **Step 3: 全体テスト**

Run: `cd /workspaces/grep_helpers2 && python -m pytest -q`
Expected: 全 PASS（skip 既存数のみ）

- [ ] **Step 4: golden 変更範囲の確認**

Run: `cd /workspaces/grep_helpers2 && git diff --stat 5de1ff0..HEAD -- tests/golden/cases`
Expected: 変更は `messy_c_legacy`・`grep_jar_artifact`（再生成）・`sql_comment`（新規）・`README.md` のみ。他の既存ケース expected に変更が無いこと。

---

## Self-Review（プラン作成者による点検結果）

- **Spec coverage:** 設計 §5.1(AST)→Task1、§5.2(regex＋ヒント除外)→Task2、§7(テスト)→Task1-3・5、§6(golden再生成)→Task4、§7新規golden→Task5、§8(spec/README)→Task6、§9(検証)→Task7。全項目にタスク対応。
- **既存テスト破壊の対応:** `test_該当規則がなければその他と判定する`（`-- just a comment` 依存）を Task2 Step1 で非コメント行へ更新済。
- **Placeholder scan:** spec 編集（Task6）は巨大 dense ファイルゆえ grep でアンカー特定→指定文追記の手順（追記文は完全提示）。コード/テストは全て完全提示。
- **型/名称整合:** `_SQL_COMMENT`/`_SHELL_COMMENT`/`_PERL_COMMENT`/`_GROOVY_COMMENT`、`("コメント","low")`、`endswith("comment")` はタスク間一貫。confidence 列は 13 列目（`cut -f13`）。
