# `コメント` カテゴリ新設 設計

- 日付: 2026-05-24
- ステータス: ドラフト（ブレインストーミング合意済 → 2視点 批判的 AI レビュー反映済 → ユーザー spec レビュー前）
- 関連: 本体 spec `2026-05-16-grep-analyzer-design.md` §7（分類）／§8.3（confidence）／§9（category taxonomy・line 152/229）／§8.4（既知限界）。分類実装 `src/grep_analyzer/classify.py` ＋ `classifiers/ts_classifier.py`（AST）／`classifiers/regex_classifier.py`（正規表現）

## 0. 改訂履歴

- v1: ブレインストーミング合意（AST `endswith("comment")`／正規表現 行頭コメント規則／confidence=low／golden 2ケース3行）。
- **v2（本版）: 2 視点の批判的 AI レビューを実コード検証付きで反映**。
  - 【Critical】Oracle ヒント句 `/*+ … */`・`--+ …` のコメント誤判定を防止（`_SQL_COMMENT` でヒント除外・§5.2/§8.4）。
  - 【Important】背景訂正: ネストしたコメント行は現状 climb で親の `比較/分岐/宣言`(high) に分類される（`その他` だけではない）。新ブランチで全コメントを `コメント` に統一（§1/§6）。golden 影響は 2ケース3行で不変（両レビュー実証）。
  - 【Important】confidence=low の意味を「当該行が keyword の真のコード使用である確信度が低い（型不確実な間接 getter/setter ＋ 非コード行＝コメント）」へ一本化（§3/§8）。
  - 【Minor】正規表現コメントの end-to-end golden を 1 件追加（SQL）＋ヒント除外の負テスト（§7）。
  - 【Minor】既知限界（正規表現の複数行ブロック中間行／jsp・angular の HTML 式コメント／perl POD・heredoc／HTML）を §8.4 へ（§8）。

## 1. 背景・目的

コメント行のヒット（例 `// 777`、`/* … 777 … */`）の現挙動:

- **トップレベルのコメント行** → `その他`/high（AST が comment ノードから climb し該当カテゴリ無しで根まで上る＝`ts_classifier.py:158`／正規表現は `_apply` 無一致＝`regex_classifier.py:43`）。
- **文ブロック内にネストしたコメント行**（例 メソッド内 `if(...){ // 777 }`） → climb が親の `if_statement`/`switch`/宣言 等に到達し **`比較`/`分岐`/`宣言`(high) に分類される**（レビュー実測）。

いずれも「実コードの使用」ではないのに、コード意味カテゴリや `その他` に混ざっている。レガシー grep 解析ではコメント中のヒットは文書/コメント参照（多くは偽陽性）であり、レビュアーが TSV で除外・下位表示・優先度判断できるよう、**コメント専用行を独立カテゴリ `コメント`（confidence=low）へ統一**する（ユーザー要望: カテゴリ＋confidence 両方）。

## 2. スコープ

### 2.1 対象

- **AST 系**（`classify_ts` 経由）: java / c / proc / python / javascript / typescript / tsx / jsp / angular / angular_inline。
  - 注: jsp/angular/angular_inline で検出されるのは **逆マスク後のホスト言語（Java/TypeScript）スタイルのコメント**のみ。HTML/JSP スタイルのコメント（`<!-- -->`・`<%-- --%>`）は host 変換で空白化され comment ノードにならず非検出（§8.4）。
- **正規表現系**: sql / perl / groovy / shell（bourne・cshell）。

### 2.2 スコープ外（YAGNI）

- **HTML**: `classify_hit` が content を見ず `("その他","high")` 固定（`classify.py:30-31`）。`<!-- -->` 検出は将来課題（§8.4 に記録）。
- 正規表現系の**複数行ブロックコメント中間行**（`/* …` の途中行）: 行単位判定ゆえ非検出＝`その他` 据置（§8.4）。AST 系は内包ノードが comment のため全行カバー。
- 行内コード＋末尾コメント同居行: コード優先（コメント専用行のみ `コメント`）。

## 3. taxonomy と confidence

- `category` 列に新値 **`コメント`** を追加。spec §9 の上位カテゴリ（`比較/代入/引数/宣言/出力/分岐` ＋ `その他`）に**ピアとして追加**する。
  - 注（軸の違い）: 既存上位は「コードの意味的役割」、`コメント` は「ソース種別（コードでなくコメント）」で軸が異なる。実用上はフィルタ可能な上位値とするのが簡潔ゆえピア追加とする（spec §9 の上位カテゴリ定義語を「意味的役割」から「ソース種別を含む上位分類」へ概念拡張する旨を §8 で明記）。
  - `_CATEGORY_*` マップには入れない（ノード型 `*comment` 判定／行頭コメント規則で別途返す）。
- **confidence = `low`**。意味を統一: **`low` ＝ 当該行が keyword の真のコード使用である確信度が低い**（① 型解決を要する間接 getter/setter ＝既存、② 非コード行＝コメント ＝本追加）。両者は「genuine なコード参照である確信度が低い」という単一意味に包含され、`confidence=low` フィルタの一貫性を保つ（spec §8.3 の定義を §8 で拡張明記）。

## 4. 判定意味（確定）

- **純コメント行のみ `コメント`**。コードを含む行（末尾コメント同居含む）は従来通りコード分類。
- AST: 単行・複数行ブロック両対応。正規表現: 単行コメント＋全行 `/* … */` のみ（複数行ブロック中間行は §2.2 のとおり非対応）。

## 5. 実装

### 5.1 AST 系 `classifiers/ts_classifier.py` `classify_ts`

**実機確認済**: コメントノード型は文法で異なる — java は `line_comment`/`block_comment`、c/proc/python/js/ts/tsx/angular は `comment`（js は legacy `html_comment` もあるが真コメント）。`endswith("comment")` で終わる非コメント型は全 grammar に存在しない（誤検出ゼロ）。よって **`node.type.endswith("comment")`** で一律判定する。

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

最小ノードが comment＝純コメント行（同居行は最小葉がコード側ノードのため巻き込まない＝コード優先）。複数行ブロックは内包ノードが comment ゆえ全行カバー。ネストしたコメントも climb 前に短絡するため `コメント` に統一される。

### 5.2 正規表現系 `classifiers/regex_classifier.py`

`_apply` は confidence を `medium` 固定で返すため、コメントは各 `classify_*` の先頭で別経路（`low`）で返す。perl/groovy は `_mask` がコメントを空白化するため **mask 前の生行**で判定する。

```python
# Oracle ヒント句 /*+ ... */ ・ --+ ... は最適化指示でありコメントではない（除外）。
_SQL_COMMENT    = re.compile(r"^\s*--(?!\+)|^\s*/\*(?!\+).*\*/\s*$")
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

`^\s*` アンカーにより同居行（`x = 777 -- c`）・perl `$#arr`・行中の `#`/`//` を巻き込まない（コード優先維持）。SQL は `(?!\+)` で `--+`/`/*+` ヒント句を除外（ヒントは `コメント` でなく通常分類＝多くは `その他`）。shell の `#!` シェバン行は `コメント` 扱いになるが許容（稀・実害なし）。

### 5.3 HTML

`classify_hit` の `("その他","high")` 固定は現状維持（スコープ外）。

## 6. golden 影響（実測済・両レビュー実証）

既存 38 件の `その他` 行を全走査し、さらにネストコメントの climb 挙動も考慮した結果、**実際にコメント行で分類が変わるのは 2 ケース 3 行のみ**:

| ケース | 行 | 変化 |
|---|---|---|
| `messy_c_legacy` | legacy.c:1（`/* … */`）, legacy.c:7（`// dead: …`） | `その他/high` → `コメント/low` |
| `grep_jar_artifact` | Main.java:2（`// 777`） | `その他/high` → `コメント/low`（`diagnostics_summary.txt` 不変） |

他の `その他`（`class A {…}` の class 行・`total += 1`・`{{ }}` 補間・`@@@@@` パース失敗・shell `log $CODE` 等）はコメントでないため不変。ネストコメントを持つ既存ケースは無いため、`比較/分岐/宣言`→`コメント` の flip は既存 golden には発生しない。

対応: `scripts/gen_golden_case.py` で 2 ケースを再生成し、**diff が当該3行（category＋confidence）のみ**・他行バイト不変を確認する。

## 7. テスト（TDD）

- `tests/unit/test_ts_classifier.py`:
  - コメント行 → `("コメント","low")` を **java（line_comment・block_comment 両方）/ c / python / javascript / typescript** で。
  - **ネストしたコメント行**（メソッド内 `if(...){ // c }` の `//` 行）→ `("コメント","low")`（climb で `比較` にならないこと）を1件。
  - コード＋末尾コメント同居行 → コード分類（`コメント` でない）を1件。
- `tests/unit/test_regex_classifier.py`:
  - sql `-- c`・全行 `/* c */`、shell `# c`（bourne・cshell）、perl `# c`、groovy `// c`・`/* c */` → `("コメント","low")`。
  - **Oracle ヒント負テスト**: `/*+ INDEX(t) */`・`--+ hint` → `コメント` で**ない**こと。
  - 同居行（`x=777 -- c`）→ コード分類を1件。
- `tests/unit/test_classify.py`: `classify_hit` 経由の統合を AST 1経路・regex 1経路で軽く確認。
- **新規 golden ケース `sql_comment`**（正規表現系の end-to-end 担保）:
  - `src/q.sql`: 1行目 `-- 777 はコメント`、2行目 `SELECT name FROM t WHERE code = '777';`。
  - `input/777.grep`: 両行。`expected/777.tsv`: 1行目 `コメント/low`、2行目 `比較/medium`（実 run 凍結＝`gen_golden_case.py`）。

## 8. spec/docs 反映

- 本体 spec §9（line 152/229 taxonomy）: 上位カテゴリ列挙に `コメント` を追加。上位カテゴリ定義語を「意味的役割」から「ソース種別（コメント）を含む上位分類」へ概念拡張する旨を明記。
- 本体 spec §8.3（confidence）: `low` の定義を「当該行が keyword の真のコード使用である確信度が低い（型不確実な間接 getter/setter ＋ 非コード行＝コメント）」へ拡張明記。
- 本体 spec §8.4（既知限界）に追記:
  - 正規表現系の複数行ブロックコメント中間行は非検出（`その他` 据置）。
  - jsp/angular の HTML/JSP スタイルコメント（`<!-- -->`・`<%-- --%>`）は host 空白化で非検出（Java/TS スタイルのみ）。HTML 言語はコメント分類スコープ外。
  - perl `^\s*#` は POD（`=pod`〜`=cut`）・heredoc 本文中の `#` 始まり行を `コメント` と誤判定し得る（行単位正規表現の既存限界）。
  - Oracle ヒント句 `--+ …`・`/*+ … */`（単独行）は `(?!\+)` で `コメント` から除外済（コメントでなく通常分類）。
- `tests/golden/cases/README.md`: `messy_c_legacy` / `grep_jar_artifact` の分類注記を更新、`sql_comment` を追記。

## 9. 検証

- `pytest tests/unit -q`（新規分類テスト緑）。
- `pytest tests/golden -q`（再生成後 46 緑＝既存45＋`sql_comment`、既存の非コメント行は不変）。
- `git diff` で golden 変更が **2ケース3行の再生成＋新規 `sql_comment` 1ケース**のみであることを確認。
- 全体 `pytest -q` 緑。

## 10. 作業順序（writing-plans へ引き継ぐ素案）

1. AST 系コメント判定（`classify_ts`）を TDD（`test_ts_classifier.py`／ネスト・同居含む）。
2. 正規表現系コメント判定（`classify_*`・ヒント除外）を TDD（`test_regex_classifier.py`／ヒント負テスト含む）。
3. `classify_hit` 統合テスト（`test_classify.py`）。
4. golden 2 ケース再生成（`gen_golden_case.py`）＋ diff が3行のみを確認。
5. 新規 golden `sql_comment` 作成（`gen_golden_case.py`）。
6. 本体 spec §9/§8.3/§8.4 反映＋ `tests/golden/cases/README.md` 更新。
7. 全体検証（§9）。
