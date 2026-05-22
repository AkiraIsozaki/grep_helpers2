# grep_analyzer v2 設計書: 正規表現トラック言語追加（PL/SQL・Perl・Groovy）

- 作成日: 2026-05-22
- ステータス: **ドラフト（批判的AIレビュー前・フェーズ移行前提）**。本書は writing-plans の入力候補だが、`ai-review-before-advancing` 方針によりレビュー収束まで plan を確定しない。
- 位置づけ: マスター設計 `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`（以下「マスター」）を **base** とする **差分設計**。本書が触れない事項はすべてマスターを正とする。PRD `docs/product-requirements.md` の v2+ のうち、ユーザー確定スコープ（jsp / PL/SQL / TS・JS / Angular / Python / Perl / Groovy）を **分類戦略で3サブプロジェクトに分割**したうちの **B: 正規表現トラック** を対象とする。
  - **B（本書）**: PL/SQL・Perl・Groovy（新依存ゼロ・行単位正規表現）。§5.2 v2+ プラグイン規約を最小リスクで確立する。
  - A（後続）: TypeScript/JS・Python（tree-sitter grammar wheel ＋ §4.2 G1 ゲート）。
  - C（後続）: JSP・Angular（Pro\*C 流の埋め込み前処理・A に依存）。
  - 順序 **B → A → C**（供給網リスクの無い B でプラグイン規約を確立してから wheel 追加・埋め込みへ）。

---

## 1. 目的とスコープ

PRD の v2+ 対応言語のうち **PL/SQL・Perl・Groovy** を、マスター §5.2 の言語別プラグイン経由で追加する。3言語とも **既存 v1 の行単位正規表現パイプライン（confidence=medium）にそのまま乗せる**。新規ネイティブ依存・tree-sitter grammar は導入しない（wheelhouse / `requirements.lock` 不変）。

### 1.1 各言語の確定方針（ユーザー確定）

| 言語 | TSV `language` | 方式 | confidence | 依存追加 |
|---|---|---|---|---|
| PL/SQL | **`sql`**（既存 Oracle 方言へ統合・不変） | 行単位正規表現（既存 Oracle 規則を手続き型へ append 拡充＋拡張子追加） | medium | なし |
| Perl | **`perl`**（新規 language 値） | 行単位正規表現 | medium | なし |
| Groovy | **`groovy`**（新規 language 値） | 行単位正規表現 | medium | なし |

- **PL/SQL は新 language を作らず既存 `sql` に統合する**。既存 `sql` は既に Oracle 方言（`:=`・DECODE・CASE WHEN を扱う）であり、PL/SQL はその手続き拡張であるため、方言的に正直かつ churn 最小。
- **複数行解析はしない**（ユーザー確定）。複数行 PL/SQL ブロック・Perl heredoc/POD・Groovy 複数行 GString は v1 同様 §8.4 の既知境界に据え置く。マスター §12/§14 の「SQL/PL-SQL は複数行非解析・正規表現維持」方針を本書でも維持する。

### 1.2 スコープ外（本書では扱わない）

- 複数行ステートフル解析（PL/SQL ブロック追跡・Perl heredoc マスク・Groovy triple-quoted マスク）。§8.4 既知境界。
- track A（TypeScript/JS・Python＝tree-sitter）・track C（JSP・Angular＝埋め込み）。別サブプロジェクト・別設計書。
- tree-sitter Oracle/PL-SQL grammar 採用（マスター §14 の条件付き将来候補のまま）。
- getter/setter の追跡（Perl/Groovy とも型解決依存のため §8.3 と同じく不投入。§8.4）。

---

## 2. アーキテクチャと拡張点（マスター §5.1/§5.2 への差分）

既存の行単位パイプライン（`detect_language → file_meta → automaton走査 → classify_hit → chase抽出 → snippet → TSV`）は無改造。各言語は以下の差分点のみを埋める（**案1: v1 パターン踏襲・churn 最小**）。

| # | ファイル | 差分 |
|---|---|---|
| 1 | `dispatch.py` | 拡張子マップ追加（§3.1）＋シェバン検出の interpreter→言語 一般化（§3.2） |
| 2 | `classify.py:classify_hit` | `perl`→`classify_perl`、`groovy`→`classify_groovy` の分岐追加。`sql` は規則拡充のみで分岐不変 |
| 3 | `classifiers/regex_classifier.py` | `classify_perl`/`classify_groovy` の規則表追加（`classify_sql`/`classify_shell` と同形）。`_SQL_RULES` へ PL/SQL 規則を **末尾 append**（§4.1） |
| 4 | `classifiers/perl_chaser.py` / `groovy_chaser.py`（新規） | Chaser プロトコル（`extract`/`mask`）実装。`classifiers/__init__.py:_CHASERS` に登録 |
| 5 | `classifiers/sql_chaser.py` | PL/SQL `CONSTANT` 宣言を constant として抽出する軽微拡充（§5.2）。それ以外不変 |
| 6 | `patterns/` | Perl/Groovy 用の assign/constant/mask 正規表現を追加 |
| 7 | `snippet/_heuristic.py` | perl/groovy の境界語追加（§6） |
| 8 | `model.py` | **コード変更なし**（言語非依存）。ref_kind×言語マッピングは本書 §5.3 の表を spec 上の正本とする |
| 9 | `wheelhouse` / `requirements.lock` / `pyproject.toml` | **変更なし** |
| 10 | `pipeline.py` | `unsupported_shebang` 記録条件の更新（§3.2） |

**プラグイン構造の選択**: 既存 v1 の構造（classify 規則は `regex_classifier.py` に共置、chase は `{lang}_chaser.py` に分離）を踏襲する。§5.2 完全プラグイン化（1言語1自己完結モジュール）への移行や既存 sql/shell の移行は**本書スコープ外**（マスター §15「無関係なリファクタはしない／churn＝構造を疑う」原則に従う）。

---

## 3. 言語識別（マスター §5.1 への差分）

### 3.1 拡張子マップ追加（`dispatch.py:_EXT_MAP`）

| 拡張子 | 言語 | 備考 |
|---|---|---|
| `.pkb` `.pks` `.prc` `.fnc` `.trg` `.pls` `.plb` | `sql` | PL/SQL（パッケージ本体/仕様・プロシージャ・関数・トリガ等）。既存 `.sql`→`sql` と同値 |
| `.pl` `.pm` `.t` | `perl` | Perl スクリプト/モジュール/テスト |
| `.groovy` `.gvy` `.gradle` | `groovy` | Groovy スクリプト/Gradle ビルド |

- 上記拡張子セットは writing-plans 着手時に最終確定する（代表的な Oracle/Perl/Groovy 拡張子。`.gradle` を含めるかは実プロジェクトの方針次第で `--lang-map` 上書きでも吸収可）。
- `--lang-map EXT=LANG` 上書き（マスター §5.1 手順1）は不変＝ユーザーが任意拡張子を割当可能。

### 3.2 シェバン検出の一般化（既存 shell 経路は byte 不変）

現状 `shebang_dialect()` は shell 専用（`bourne`/`cshell`/`other`/`None`）。pipeline は「拡張子未確定 ∧ 非shell ∧ shebang=`other`」で `unsupported_shebang` を記録する（`pipeline.py:84-89`）。

差分:

- **interpreter→言語マップ** `_SHEBANG_LANG` を導入: `sh`/`bash`/`ksh`/`dash`→`shell`、`csh`/`tcsh`→`shell`、`perl`→`perl`、`groovy`→`groovy`。**`python` は意図的に未登録**（track A 未着手＝B では昇格させない）。
- `detect_language`: 拡張子で言語が確定しない場合、第1物理行のシェバンを解釈し:
  - perl/groovy/shell に解決 → その言語を返す（shell の bourne/cshell 副方言は従来どおり `detect_shell_dialect` が別途決定）。
  - シェバンはあるが未登録 interpreter（python/awk/ruby 等）→ 従来どおり `unsupported_shebang` 経路：EXEC SQL ヒューリスティック→ C フォールバック（マスター §5.1 手順4-5 不変）。
  - シェバン無し → 従来どおり。
- **`unsupported_shebang` 記録条件の更新（`pipeline.py`）**: 「拡張子未確定 ∧ シェバン行はあるが対応言語に解決しない」で記録。perl/groovy は解決するため記録されない／python 等は引き続き記録される。
- `#!/usr/bin/env X` は X を interpreter とみなす規則（マスター §5.1）を踏襲。
- `shebang_dialect`/`detect_shell_dialect`（bourne/cshell 副方言判定）は**不変**（language=shell のときのみ作用）。判定はファイル名と第1物理行のみに依存し走査順非依存（決定性）。

> 実装メモ: 「シェバン行が存在するか」と「対応言語に解決したか」を区別する必要があるため、interpreter 解析結果を `str(言語) | None`（解決）と「シェバン行の有無」の2情報で返せる形にする（既存 `shebang_dialect` の `"other"` 相当＝シェバンあり・未解決を保持）。詳細 API は writing-plans で確定。

---

## 4. 分類器規則（マスター §7 への差分・confidence=medium）

`category` はマスター §7 の共通上位（比較/代入/引数/宣言/出力/分岐）＋ return を用いる。`category_sub` は初版**空固定**（マスター §9・churn 回避）。規則は **先頭一致優先**（既存 `regex_classifier._apply` の挙動）。

### 4.1 PL/SQL（既存 `_SQL_RULES` への append-only 拡充）

既存規則（順序・挙動とも**不変**）:

```
1. :=                          → 代入
2. \bWHERE\b.*?[=<>]           → 比較   (IGNORECASE)
3. \bCASE\s+WHEN\b|\bDECODE\s*\(|\|\|  → 分岐 (IGNORECASE)
4. \b(?:INSERT|UPDATE)\b       → 代入   (IGNORECASE)
```

末尾に append（既存ヒット行は規則1-4 で先に確定するため分類不変。新規則は現状「その他」へ落ちる行のみを拾う・すべて IGNORECASE・語境界付き）:

```
5. \b(?:PROCEDURE|FUNCTION|PACKAGE(?:\s+BODY)?|TRIGGER|CURSOR|TYPE)\b  → 宣言
6. \bIF\b.*\bTHEN\b | \bELSIF\b                                        → 比較
7. \b(?:LOOP|FOR|WHILE)\b                                              → 分岐
8. \bDBMS_OUTPUT\.PUT_LINE\b | \bRAISE_APPLICATION_ERROR\b             → 出力
```

- 規則6を「比較」とするのは Java `if_statement`→比較（マスター `_CATEGORY_BY_NODE`）との整合。
- **Inv-B（§8）により、append が既存 sql golden 行の分類を変えないことを再生成 diff で実証する**。語境界・`THEN` アンカーで列名等への誤爆を抑止するが、最終確認は diff を正本とする。

### 4.2 Perl（`classify_perl`・新規規則表・先頭一致優先）

| 順 | 規則 | category |
|---|---|---|
| 1 | `^\s*sub\s+\w+` ／ `\bpackage\s+\w+` ／ `\buse\s+constant\b` | 宣言 |
| 2 | `^\s*(?:my\|our\|local\|state)\s+[$@%]` ／ `[$@%]\w+\s*=(?!=\|~)` | 代入 |
| 3 | `\b(?:if\|unless\|elsif)\b` ／ `(?:==\|!=\|<=\|>=\|<\|>\|\beq\b\|\bne\b\|\blt\b\|\bgt\b\|\ble\b\|\bge\b\|=~\|!~)` | 比較 |
| 4 | `\b(?:for\|foreach\|while\|until)\b` | 分岐 |
| 5 | `\b(?:print\|printf\|say\|warn\|die)\b` | 出力 |
| — | 上記いずれも不一致 | その他 |

判定対象行は `chase.mask_literals("perl", line)` でリテラル/コメントをマスクした行（`#` コメント内の `=` 等の誤爆抑止）。マスク桁数保存により行頭アンカーは不変。

### 4.3 Groovy（`classify_groovy`・新規規則表・先頭一致優先）

| 順 | 規則 | category |
|---|---|---|
| 1 | `^\s*(?:class\|interface\|enum\|trait\|def)\s+` | 宣言 |
| 2 | `(?:\bdef\b\|\bfinal\b\|[A-Za-z_]\w*(?:<[^>]*>)?)\s+\w+\s*=(?!=)` ／ `\b\w+\s*=(?!=)` | 代入 |
| 3 | `\b(?:if\|while)\b` ／ `(?:==\|!=\|<=\|>=\|<\|>\|<=>\|=~\|==~)` | 比較 |
| 4 | `\b(?:switch\|for\|case)\b` | 分岐 |
| 5 | `\breturn\b` | return |
| 6 | `\b(?:println\|print\|printf)\b\|\blog\.\w+` | 出力 |
| — | 上記いずれも不一致 | その他 |

判定対象行は `chase.mask_literals("groovy", line)` でマスクした行。`def foo() { ... }`（宣言）と `def x = ...`（代入）の弁別は規則1（`def\s+\w+\s*(?=\()` を含む宣言形）と規則2の順序で確定する（最終的な precedence は writing-tests で固定）。

> 規則の正確な precedence・境界は writing-plans/writing-tests で golden により確定する。本書は category 語彙と判定軸を確定する。

---

## 5. chase 抽出・ref_kind（マスター §8.1/§8.3/§9 への差分）

### 5.1 Perl Chaser（`perl_chaser.py`・新規）

- `mask(line)`: Perl のリテラル・コメントを同字数空白へ。対象＝`'…'`・`"…"`・`q(…)`・`qq(…)`・`#` から行末コメント。**行単位**（heredoc・POD は対象外＝§8.4）。`patterns/literal_masking.py` に `MASK_PATTERNS["perl"]` を追加。
- `extract(dialect, line)`（dialect は無視）:
  - **var**: `^\s*(?:my|our|local|state)\s+[$@%](\w+)\s*=` の捕捉名、および一般代入 `[$@%](\w+)\s*=(?!=|~)` の捕捉名。**sigil（`$`/`@`/`%`）は剥がして bare 識別子 `\w+` を追跡シンボルとする**（マスター §8.1 の字句追跡＝`:var`→var と同方針）。
  - **constant**: `\buse\s+constant\s+(\w+)` の捕捉名。
  - **getter/setter**: なし（型解決依存・§8.4）。
- 抽出はマスク済み行に対して行う（コメント内 `=` 等を除外）。

### 5.2 Groovy Chaser（`groovy_chaser.py`・新規）＋ PL/SQL constant 拡充

- Groovy `mask(line)`: `'…'`・`"…"`・`//`・`/* */`（行単位）。triple-quoted・slashy string は §8.4。`MASK_PATTERNS["groovy"]` を追加。
- Groovy `extract`:
  - **var**: `\bdef\s+(\w+)\s*=` ／ 型付き宣言 `[A-Za-z_]\w*(?:<[^>]*>)?\s+(\w+)\s*=(?!=)` の捕捉名、および一般代入。
  - **constant**: `\b(?:static\s+)?final\s+(?:[A-Za-z_]\w*\s+)?(\w+)\s*=` の捕捉名。
  - **getter/setter**: なし（§8.4）。
- **PL/SQL constant 拡充（`sql_chaser.py`）**: `\b(\w+)\s+CONSTANT\b` の左辺識別子を **constant** として抽出する（現状は `:=` 左辺を一律 var）。`:=` 左辺で CONSTANT を伴わないものは従来どおり var。これ以外の sql_chaser 挙動は不変。

### 5.3 ref_kind × 言語マッピング（マスター §9 の表へ追記・本書が正本）

| 言語 | constant | var | getter/setter |
|---|---|---|---|
| SQL(Oracle/PL/SQL) | `CONSTANT` 宣言 | `:=` 代入（バインド `:v`・置換 `&v` は対象外＝§8.4） | — |
| Perl | `use constant` | `my`/`our`/`local`/`state`・代入左辺（sigil 除去） | —（§8.4） |
| Groovy | `final`/`static final` | `def`/型付き宣言・代入左辺 | —（§8.4） |

- 停止性（マスター §8.1 手順5）は不変＝抽出シンボルはすべてソース上に字句出現する有限の識別子。sigil 剥がし後の `\w+` も有限母集合に属する。
- §8.3 シンボル採否ポリシー（静的ストップリスト・min-specificity・決定的切り捨て）は言語非依存で**不変適用**。短い汎用名（sigil 剥がしで増えうる）は `--min-specificity` と `--stoplist` で抑止。

---

## 6. snippet（マスター §9「snippet 切り出し規則」への差分）

Perl/Groovy は AST 非使用のため、sql/shell と同じ**決定的ヒューリスティック**（`snippet/_heuristic.py`）で切り出す。`chase.mask_literals(language, line)` を各物理行に適用したマスク後行で句境界・括弧・クオートを評価し、`hit` から上下に拡張する（マスター §9 の上下対称展開＋上限クランプ＝既定 12 行/800 文字、両端省略マーカは不変）。

境界キーワード追加（大文字小文字無視・マスター §9 の停止条件群へ言語別に追加）:

- **perl**: 文末 `;` ／ ブロック `}` ／ `sub`。
- **groovy**: 文末 `;` ／ ブロック `}` ／ `class` ／ `def`。

PL/SQL は既存 sql 境界語を据え置く。**新たな PL/SQL 境界語を sql に追加しない**（既存 sql snippet golden を変えないため＝Inv-B）。複数行 PL/SQL ブロックの snippet 整形は §8.4 既知境界（上限クランプで有限化）。

---

## 7. §8.4 既知境界（マスター §8.4 への追記）

マスター §8.4 を唯一の正本とし、本書は以下を追記する:

- **Perl の限界**: heredoc・POD（`=pod`/`=cut`）・`eval`・シンボリックリファレンス・typeglob・正規表現で合成される名前は追跡不可。**sigil 剥がしによる過剰一致**＝`$foo`/`@foo`/`%foo`・hash キー・sub 名が同名 `foo` で合流しうる（誤検出ではなく字句追跡の仕様。§8.3 min-specificity/stoplist で緩和、confidence=medium で人間確認前提）。
- **Groovy の限界**: 複数行 GString／triple-quoted 文字列・slashy string `/…/`・closure 動的ディスパッチ・`${}` 補間で生成される名前・メタプログラミング（methodMissing/propertyMissing）・型解決依存の auto getter/setter は追跡不可。
- **PL/SQL の限界（据え置き・再掲）**: 複数行 DECLARE/BEGIN/END ブロック・動的SQL（EXECUTE IMMEDIATE・文字列連結 SQL）・複数行文の非折り畳み・`%TYPE`/`%ROWTYPE` は構文追跡不可（マスター §8.4 既存項を維持）。
- **非対応シェバン**: `python`/`awk`/`ruby` 等は対応言語に解決せず `unsupported_shebang`（§3.2）。python は track A で昇格予定。

---

## 8. 不変条件 Inv-B（受け入れゲート）

> **Inv-B: 本サブプロジェクトは v1 の既存 golden を byte 不変に保つ。**

- 触れる v1 経路は (a) `_SQL_RULES` への append（§4.1）、(b) sql_chaser の CONSTANT 拡充（§5.2）、(c) シェバン検出の一般化（§3.2）、(d) `_heuristic.py` への perl/groovy 境界語追加（§6・既存言語の分岐に影響しないこと）。
- これらが既存 sql/shell/java/c/proc の golden 出力を変えないことを、**既存 golden 全件の再生成 diff がゼロ**であることで実証する。
- 変える差分が出た場合は「意図的変更か誤りか」をレビュー承認の対象とし、誤りは設計・実装で除去する（churn を放置しない）。
- Inv-B は本サブプロジェクトのフェーズ完了ゲート（マスター §15 のフェーズ完了基準に準ずる）。

---

## 9. テスト/golden 計画（マスター §11 への差分）

`.claude/skills/writing-tests.md` 準拠（古典学派＋TDD・日本語テスト名・層の縄張り）。カバレッジ原則: 言語×ref_kind は必須網羅、文字コード/多ホップは pairwise 直交。

**必須回帰ケース（名指し）**:

- **Inv-B**: 既存 v1 golden 全件 byte 不変（§8）。
- **PL/SQL**: 手続き型宣言分類（PROCEDURE/FUNCTION/PACKAGE→宣言）・`IF…THEN`→比較・`LOOP`→分岐・`DBMS_OUTPUT.PUT_LINE`→出力・`CONSTANT`→constant 追跡・拡張子 `.pkb`/`.pks`→sql。
- **Perl**: direct・indirect:var（`my $x`）・indirect:constant（`use constant`）・sigil 剥がし過剰一致の代表ケース（`$foo`/`@foo` が同名で拾われる挙動の固定）・拡張子なし＋`#!/usr/bin/perl`→perl のシェバン判別・各 category。
- **Groovy**: direct・indirect:var（`def`）・indirect:constant（`final`）・拡張子なし＋`#!/usr/bin/groovy`→groovy のシェバン判別・各 category。
- **一般化シェバン回帰**: 拡張子なし＋`#!/usr/bin/python` が引き続き `unsupported_shebang`（B では昇格しない）。
- **多ホップ**: perl var→chain・groovy var→chain を各1（新 chaser で §8.1 不動点を発火・chain 正規形を固定）。
- **文字コード直交**: 新言語1ケースを非UTF-8（cp932 または euc-jp・判定値を pin）。

**層**:

- `tests/unit/`: classify 規則（perl/groovy/PL/SQL append）・chaser extract/mask（sigil 剥がし・CONSTANT）・シェバン一般化（interpreter→言語・unsupported 判定）。
- `tests/golden/`: 言語×ref_kind の合成小規模ツリーで TSV 完全一致（マスター §11 の `{SOURCE_ROOT}` 逆置換比較機構を踏襲）。
- `tests/integration/`: perl/groovy/plsql 混在ツリーの CLI 契約・複数 keyword・`--resume`。
- `tests/handcrafted/`（非ゲート）: 分類精度ダッシュボードに新言語サンプル追加。
- `tests/perf/`（非ゲート）: 新言語は正規表現のみ＝既存 perf ベースラインに本質的影響なし（`_ITEMS_PER_MB` 再測定不要）。

---

## 10. マスター §14/§15 への反映

- **§2.3 v1 スコープ**: 本書完了で PL/SQL（sql 統合）・Perl・Groovy が「v2 対応済」となる旨を追記（v1 スコープ自体は不変）。
- **§14 今後（v2+）**: 「PL/SQL（sql 統合・正規表現）・Perl・Groovy は v2 で対応済」へ更新。残り（Kotlin・C#/VB.NET）は本ユーザースコープ外、TS/JS・Python・JSP・Angular は track A/C で継続。
- **§15 実装フェーズ**: 本書を **フェーズ5（v2 正規表現トラック）** として追加（フェーズ4 完了後・決定的コア＋出力スキーマ確定の上に乗る）。着手前提: フェーズ1〜4 完了済（本リポジトリは充足）。本フェーズ完了基準＝§8 Inv-B ＋ §9 必須回帰グリーン。
- これらマスター本体への追記は、本書がユーザーレビュー承認された後にマスターへ反映する（本書はマスターを base とする差分のため、確定までマスターを変更しない）。

---

## 11. 決定事項サマリ（レビュー観点の明示）

1. PL/SQL は **既存 `sql`（Oracle 方言）へ統合**（新 language を作らない）。
2. **複数行解析はしない**（PL/SQL ブロック・Perl heredoc/POD・Groovy 複数行 GString は §8.4 据え置き）。
3. Perl/Groovy は **新 language 値**・行単位正規表現・confidence=medium。
4. Perl は **sigil 剥がしで bare 識別子を追跡**（過剰一致は §8.4・§8.3 で緩和）。
5. getter/setter は Perl/Groovy とも **不追跡**（型解決依存・§8.4）。
6. シェバン検出を **interpreter→言語 一般化**（perl/groovy 昇格・python は据え置き unsupported）。
7. プラグイン構造は **v1 パターン踏襲（案1・churn 最小）**。§5.2 完全プラグイン化・既存移行はスコープ外。
8. **Inv-B（v1 golden byte 不変）** を完了ゲートとする。
9. **新依存ゼロ**（wheelhouse/lock/pyproject 不変）。
