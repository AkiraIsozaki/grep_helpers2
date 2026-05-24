# `コメント` カテゴリ新設 設計

- 日付: 2026-05-24
- ステータス: ドラフト（ブレインストーミング合意済 → 批判的レビュー前）
- 関連: 本体 spec `2026-05-16-grep-analyzer-design.md` §7（分類）／§9（category taxonomy・line 152）／§8.4（既知限界）。分類実装 `src/grep_analyzer/classify.py` ＋ `classifiers/ts_classifier.py`（AST）／`classifiers/regex_classifier.py`（正規表現）

## 1. 背景・目的

現状、コメント行のヒット（例 `// 777`、`/* … 777 … */`）は category `その他`・confidence `high`（AST）に丸められている。AST 系は `classify_ts` がコメントノードから親へ上昇し該当カテゴリ無しで根まで上り `その他`（`ts_classifier.py:158`）、正規表現系は `_apply` がどのルールにも一致せず `その他`（`regex_classifier.py:43`）。判別情報は手元にあるのに捨てている。

レガシー grep 解析ではコメント中のヒットは「実コードの使用」ではなく文書/コメント参照（多くは偽陽性）であり、レビュアーが TSV で除外・下位表示・優先度判断できるよう、**`コメント` を独立カテゴリにし、confidence も下げる**（ユーザー要望: カテゴリ＋confidence 両方）。

## 2. スコープ

### 2.1 対象

- **AST 系**（`classify_ts` 経由）: java / c / proc / python / javascript / typescript / tsx / jsp / angular / angular_inline。
- **正規表現系**: sql / perl / groovy / shell（bourne・cshell）。

### 2.2 スコープ外（YAGNI）

- **HTML**: `classify_hit` が content を見ず `("その他","high")` 固定（`classify.py:30-31`）。`<!-- -->` 検出は将来課題として記録（§7 に追記）。
- 正規表現系の**複数行ブロックコメント中間行**（`/* …` の途中行）: 行単位判定ゆえ非検出＝`その他` 据置（§8.4 既知限界）。AST 系は内包ノードが comment のため全行カバー。
- 行内コード＋末尾コメント同居行: コード優先（コメント専用行のみ `コメント`）。

## 3. taxonomy

- `category` 列に新値 **`コメント`** を追加。spec §9 の上位カテゴリ（`比較/代入/引数/宣言/出力/分岐` ＋ `その他`）に**ピアとして追加**する。コード意味カテゴリでも `その他` でもない「コメント専用行」を表す独立値。
- `_CATEGORY_*` マップには入れない（ノード型 `*comment` の判定／行頭コメント規則で別途返す）。
- **confidence = `low`**（実コード使用ではない信号）。

## 4. 判定意味（確定）

- **純コメント行のみ `コメント`**。コードを含む行（末尾コメント同居含む）は従来通りコード分類。
- AST: 単行・複数行ブロック両対応。正規表現: 単行コメント＋全行 `/* … */` のみ（複数行ブロック中間行は §2.2 のとおり非対応）。

## 5. 実装

### 5.1 AST 系 `classifiers/ts_classifier.py` `classify_ts`

**重要（実機確認済）**: コメントノード型は文法で異なる — java は `line_comment`/`block_comment`、c/proc/python/js/ts/tsx/angular は `comment`。よって **`node.type.endswith("comment")`** で一律判定する（全文法カバー・将来文法にも頑健）。

`node_at_line` 直後・climb ループ前に1分岐を追加:

```python
node = node_at_line(tree.root_node, lineno)
if node is not None and node.type.endswith("comment"):   # comment/line_comment/block_comment
    return ("コメント", "low")
while node is not None:
    cat = _CATEGORY_BY_LANG[language].get(node.type)
    if cat is not None:
        return (cat, "high")
    node = node.parent
return ("その他", "high")
```

最小ノードが comment＝純コメント行（同居行は最小葉がコード側ノードのため巻き込まない＝コード優先）。複数行ブロックは内包ノードが comment ゆえ全行カバー。

### 5.2 正規表現系 `classifiers/regex_classifier.py`

`_apply` は confidence を `medium` 固定で返すため、コメントは各 `classify_*` の先頭で別経路（`low`）で返す。perl/groovy は `_mask` がコメントを空白化するため **mask 前の生行**で判定する。

```python
_SQL_COMMENT    = re.compile(r"^\s*--|^\s*/\*.*\*/\s*$")
_SHELL_COMMENT  = re.compile(r"^\s*#")
_PERL_COMMENT   = re.compile(r"^\s*#")
_GROOVY_COMMENT = re.compile(r"^\s*//|^\s*/\*.*\*/\s*$")


def classify_sql(line):
    if _SQL_COMMENT.match(line):
        return ("コメント", "low")
    return _apply(_SQL_RULES, line)


def classify_shell(line, dialect="bourne"):
    if _SHELL_COMMENT.match(line):
        return ("コメント", "low")
    rules = _SHELL_RULES_CSHELL if dialect == "cshell" else _SHELL_RULES_BOURNE
    return _apply(rules, line)


def classify_perl(line):
    if _PERL_COMMENT.match(line):
        return ("コメント", "low")          # mask 前の生行で判定
    return _apply(_PERL_RULES, _mask("perl", line))


def classify_groovy(line):
    if _GROOVY_COMMENT.match(line):
        return ("コメント", "low")          # mask 前の生行で判定
    return _apply(_GROOVY_RULES, _mask("groovy", line))
```

`^\s*` アンカーにより、同居行（`x = 777 -- c`）・perl `$#arr`・行中の `#`/`//` は巻き込まない（コード優先維持）。shell の `#!` シェバン行は `コメント` 扱いになるが許容（稀・実害なし）。

### 5.3 HTML

`classify_hit` の `("その他","high")` 固定は現状維持（スコープ外）。

## 6. golden 影響（実測済）

既存 38 件の `その他` 行を全走査した結果、**実際にコメント行なのは 2 ケース 3 行のみ**:

| ケース | 行 | 変化 |
|---|---|---|
| `messy_c_legacy` | legacy.c:1（`/* … */`）, legacy.c:7（`// dead: …`） | `その他/high` → `コメント/low` |
| `grep_jar_artifact` | Main.java:2（`// 777`） | `その他/high` → `コメント/low`（`diagnostics_summary.txt` は不変） |

他の `その他`（`class A {…}` の class 行・`total += 1`・`{{ }}` 補間・`@@@@@` パース失敗・shell `log $CODE` 等）は**コメントでない**ため不変。AST は純コメント行で comment ノードを返すため誤巻き込みなし。

対応: `scripts/gen_golden_case.py` で 2 ケースを再生成し、**diff が当該3行（category＋confidence）のみ**・他行バイト不変を確認する。

## 7. テスト（TDD）

- `tests/unit/test_ts_classifier.py`: コメント行 → `("コメント","low")` を **java（line_comment・block_comment 両方）/ c / python / javascript / typescript** で。コード＋末尾コメント同居行 → コード分類（`コメント` でない）を1件。
- `tests/unit/test_regex_classifier.py`: sql `-- c`・全行 `/* c */`、shell `# c`（bourne・cshell）、perl `# c`、groovy `// c`・`/* c */` → `("コメント","low")`。同居行（`x=777 -- c`）→ コード分類を1件。
- `tests/unit/test_classify.py`: `classify_hit` 経由の統合を AST 1経路・regex 1経路で軽く確認。

## 8. spec/docs 反映

- 本体 spec §9（line 152 taxonomy）: 上位カテゴリ列挙に `コメント` を追加し confidence=low を明記。
- 本体 spec §7 / §8.4: 正規表現系の複数行ブロックコメント中間行は非検出（`その他` 据置）・HTML コメントはスコープ外、を既知限界として記録。
- `tests/golden/cases/README.md`: `messy_c_legacy` / `grep_jar_artifact` の分類注記を更新。

## 9. 検証

- `pytest tests/unit -q`（新規分類テスト緑）。
- `pytest tests/golden -q`（再生成後 45 緑、既存の非コメント行は不変）。
- `git diff` で golden 変更が**2ケース3行のみ**であることを確認。
- 全体 `pytest -q` 緑。

## 10. 作業順序（writing-plans へ引き継ぐ素案）

1. AST 系コメント判定（`classify_ts`）を TDD（`test_ts_classifier.py`）。
2. 正規表現系コメント判定（`classify_*`）を TDD（`test_regex_classifier.py`）。
3. `classify_hit` 統合テスト（`test_classify.py`）。
4. golden 2 ケース再生成（`gen_golden_case.py`）＋ diff が3行のみを確認。
5. 本体 spec §9/§7/§8.4 反映＋ `tests/golden/cases/README.md` 更新。
6. 全体検証（§9）。
