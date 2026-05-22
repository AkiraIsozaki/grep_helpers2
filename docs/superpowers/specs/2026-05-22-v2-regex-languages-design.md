# grep_analyzer v2 設計書: 正規表現トラック言語追加（PL/SQL・Perl・Groovy）

- 作成日: 2026-05-22
- ステータス: **ドラフト（批判的AIレビュー反復中・フェーズ移行前提）**。`ai-review-before-advancing` 方針によりレビュー収束まで plan を確定しない。
- 改訂:
  - v1: ブレインストーミング初版（ユーザー確定スコープ反映）。
  - **v2（批判的AIレビュー round1 反映）: 3観点並列レビュー（決定性/Inv-B・正規表現の正しさ・アーキ統合）の Critical/Important を反映。** 主な収束点: (C-G)`stoplist.LANG_KEYWORDS` への perl/groovy 予約語追加を拡張点に明記（未対応だと §8.3 採否が新言語で無効化＝偽陽性爆発）／(C-H)`pipeline.py` の `unsupported_shebang` 条件を「解決済み言語を除外」へ具体化（perl/groovy 誤診断の防止）／(C-A)classify のマスク経路を確定（perl/groovy は classifier 内 mask・sql は生行維持＋新規則を行頭アンカー化）／(C-B)PL/SQL 規則 precedence の是正（出力先頭・宣言/ループの行頭アンカー）／(C-C)PL/SQL 型付き宣言の var 抽出を「先頭識別子」へ是正＋データ型名ストップリスト／(C-D)Perl `#` マスクの `$#`/`@#` 除外／(C-E)Perl `->`・Groovy generics の比較誤爆除外／(C-F)Groovy `def x=` を代入へ（宣言形は `def name(` 限定）。Inv-B を「規則固有安全」でなく**再生成 diff ゼロのゲート**として正直化。
  - **v3（批判的AIレビュー round2 反映）: round1 修正が生んだ回帰の是正と残 Important の反映。** 最重要 (R2-C1): v2 の PL/SQL 宣言抽出正規表現が**通常の複数代入 `a := 1; b := 2;` を宣言形と誤判定し第2左辺以降を脱落**させ既存 `tests/unit/test_chase.py` を破壊（golden 非対象＝Inv-B diff ゲートの死角・サイレント回帰）。宣言形検出を「名前と `:=` の**間に実型トークンが在る**場合に限定」へ是正し通常/複数代入の per-`:=` 抽出を温存（§5.2）。併せて: `unsupported_shebang` 条件の擬似コード一意化（§3.2）／`_heuristic.stop()` の shell return 分岐化を Inv-B 担保条件として明記＋chaser.mask の snippet 二重用途を明記（§6）／§4.1 の `:=` 最優先 precedence 注記／§8.4 に複合代入（`+=`/`.=`/`||=` 等）・Perl リスト宣言 `my ($a,$b)=`・shell 版番号シェバン未対応を追記／§8・§9 に `test_chase.py`（複数代入）と constant→`indirect:constant` 経路の回帰を明示。
- 位置づけ: マスター設計 `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`（以下「マスター」）を **base** とする **差分設計**。本書が触れない事項はすべてマスターを正とする。PRD `docs/product-requirements.md` の v2+ のうちユーザー確定スコープ（jsp / PL/SQL / TS・JS / Angular / Python / Perl / Groovy）を **分類戦略で3サブプロジェクトに分割**したうちの **B: 正規表現トラック** を対象とする。
  - **B（本書）**: PL/SQL・Perl・Groovy（新依存ゼロ・行単位正規表現）。§5.2 v2+ プラグイン規約を最小リスクで確立する。
  - A（後続）: TypeScript/JS・Python（tree-sitter grammar wheel ＋ §4.2 G1 ゲート）。
  - C（後続）: JSP・Angular（Pro\*C 流の埋め込み前処理・A に依存）。
  - 順序 **B → A → C**。

---

## 1. 目的とスコープ

PRD の v2+ 対応言語のうち **PL/SQL・Perl・Groovy** を、マスター §5.2 の言語別プラグイン経由で追加する。3言語とも **既存 v1 の行単位正規表現パイプライン（confidence=medium）にそのまま乗せる**。新規ネイティブ依存・tree-sitter grammar は導入しない（wheelhouse / `requirements.lock` / `pyproject.toml` 不変）。

### 1.1 各言語の確定方針（ユーザー確定）

| 言語 | TSV `language` | 方式 | confidence | 依存追加 |
|---|---|---|---|---|
| PL/SQL | **`sql`**（既存 Oracle 方言へ統合・不変） | 行単位正規表現（既存 Oracle 規則を行頭アンカーで append 拡充＋拡張子追加） | medium | なし |
| Perl | **`perl`**（新規 language 値） | 行単位正規表現 | medium | なし |
| Groovy | **`groovy`**（新規 language 値） | 行単位正規表現 | medium | なし |

- **PL/SQL は新 language を作らず既存 `sql` に統合する**（Oracle の手続き拡張＝方言的に正直・churn 最小）。
- **複数行解析はしない**（ユーザー確定）。複数行 PL/SQL ブロック・Perl heredoc/POD・Groovy 複数行 GString は v1 同様 §8.4 既知境界。マスター §12/§14 の「PL-SQL は複数行非解析・正規表現維持」方針を本書でも維持。

### 1.2 スコープ外

複数行ステートフル解析／track A・C／tree-sitter Oracle-PL/SQL grammar／getter/setter 追跡（Perl/Groovy とも型解決依存＝§8.4）。

---

## 2. アーキテクチャと拡張点（マスター §5.1/§5.2 への差分）

既存の行単位パイプライン（`detect_language → file_meta → automaton走査 → classify_hit → chase抽出 → snippet → TSV`）は無改造。各言語は以下の差分点のみを埋める（**案1: v1 パターン踏襲・churn 最小**）。

> **重要（review round1・C-G/C-H/M-1）**: dispatcher（classify/chase/snippet）の外に **言語依存データが3箇所**ある。これらを拡張点表に明記する: `stoplist.LANG_KEYWORDS`（#11）・`pipeline.py` の `unsupported_shebang` 条件式（#10）・`snippet/__init__.py:build_snippet` の言語分岐（#7）。dispatcher 経由（`_CHASERS`/`classify_hit`）だけ埋めると採否・診断・snippet が新言語で機能しない。

| # | ファイル | 差分 |
|---|---|---|
| 1 | `dispatch.py` | 拡張子マップ追加（§3.1）＋シェバン検出の interpreter→言語 一般化（§3.2） |
| 2 | `classify.py:classify_hit` | `perl`→`classify_perl`、`groovy`→`classify_groovy` の分岐追加（signature 不変）。`sql` は規則拡充のみで分岐不変 |
| 3 | `classifiers/regex_classifier.py` | `classify_perl`/`classify_groovy`（**内部で mask 適用**・§4）追加。`_SQL_RULES` へ PL/SQL 規則を**行頭アンカー付きで append**（§4.1） |
| 4 | `classifiers/perl_chaser.py` / `groovy_chaser.py`（新規） | Chaser プロトコル（`extract`/`mask`）実装。`classifiers/__init__.py:_CHASERS` に登録 |
| 5 | `classifiers/sql_chaser.py` | PL/SQL 宣言形（`name [CONSTANT] TYPE := …`）の**先頭識別子**を var/constant 抽出（型名誤抽出の是正・§5.2） |
| 6 | `patterns/literal_masking.py` / `patterns/symbol_extraction.py` / `patterns/snippet_boundaries.py` | Perl/Groovy の mask・assign/constant・snippet 境界正規表現を追加。PL/SQL 宣言抽出正規表現を追加 |
| 7 | `snippet/__init__.py` ＋ `snippet/_heuristic.py` | `build_snippet` の `elif language in ("sql","shell")` 分岐に perl/groovy 追加（**独立 elif・sql/shell の既存分岐は literal 不変**）＋ `_heuristic.stop()` に perl/groovy ブランチ追加 |
| 8 | `model.py` | **コード変更なし**（言語非依存）。ref_kind×言語マッピングは本書 §5.4 の表を正本とする |
| 9 | `wheelhouse` / `requirements.lock` / `pyproject.toml` | **変更なし** |
| 10 | `pipeline.py` | `unsupported_shebang` 記録条件を「シェバンが**対応言語に解決しない**とき」へ具体化（§3.2・現 `language != "shell"` のままだと perl/groovy 誤記録） |
| 11 | `stoplist.py:LANG_KEYWORDS` | **`perl`/`groovy` の予約語 frozenset を追加**（§5.3・未追加だと §8.3 keyword 篩が新言語で無効化＝偽陽性爆発） |

**プラグイン構造**: 既存 v1 の構造（classify 規則は `regex_classifier.py` 共置、chase は `{lang}_chaser.py` 分離）を踏襲。§5.2 完全プラグイン化・既存 sql/shell の移行は**スコープ外**（マスター §15「無関係なリファクタはしない」）。

---

## 3. 言語識別（マスター §5.1 への差分）

### 3.1 拡張子マップ追加（`dispatch.py:_EXT_MAP`）

| 拡張子 | 言語 |
|---|---|
| `.pkb` `.pks` `.prc` `.fnc` `.trg` `.pls` `.plb` | `sql`（PL/SQL） |
| `.pl` `.pm` `.t` | `perl` |
| `.groovy` `.gvy` `.gradle` | `groovy` |

- 拡張子セットは writing-plans 着手時に最終確定。`--lang-map EXT=LANG` 上書きは不変。
- **EXEC SQL ヒューリスティックと非衝突（review I-3）**: PL/SQL 拡張子は `_EXT_MAP` で先に `sql` へ確定するため `detect_language` の EXEC SQL 分岐（`lang in ("c","proc")` または未知拡張子）には到達しない＝Pro\*C 判定と独立。

### 3.2 シェバン検出の一般化（既存 shell 経路は byte 不変・review C-H 反映）

現状 `shebang_dialect` は shell 専用（`bourne`/`cshell`/`other`/`None`）。pipeline は `not extension_resolves_language ∧ language != "shell" ∧ shebang_dialect == "other"` で `unsupported_shebang` を記録（`pipeline.py:84-89`）。

差分:

- **interpreter→言語マップ** `_SHEBANG_LANG` を導入: `sh`/`bash`/`ksh`/`dash`→`shell`、`csh`/`tcsh`→`shell`、`perl`→`perl`、`groovy`→`groovy`。**`python` は意図的に未登録**（track A 未着手）。
- **interpreter basename の版番号除去（review I-6）**: `#!/usr/bin/perl5.36` 等の版サフィックスを剥がして照合（`perl5.36`/`perl5`→`perl`）。`#!/usr/bin/env X` は X を interpreter とみなす規則を踏襲。
- **新解決関数** `shebang_language(content_sample) -> str | None` を新設（解決言語または None）。**`shebang_dialect`（bourne/cshell 副方言判定）は不変**＝`detect_shell_dialect` への波及なし。`detect_language` は拡張子未確定時に `shebang_language` を使い perl/groovy/shell に解決、未解決 interpreter（python/awk/ruby）は従来どおり EXEC SQL→C フォールバック。
- **`unsupported_shebang` 記録条件の具体化（C-H・R2 擬似コード一意化）**: 現条件 `not extension_resolves_language ∧ language != "shell" ∧ shebang_dialect == "other"` のままだと perl ファイルは `language="perl"`（≠shell）・`shebang_dialect="other"` で**3条件成立し誤記録**する。`shebang_dialect`（None=シェバン行なし／non-None=シェバン行あり）と新設 `shebang_language`（解決言語 or None）を併用し、条件を擬似コードで一意化する:

  ```
  記録する ⟺
      not extension_resolves_language(relpath, lang_map)   # 拡張子で未確定
      and shebang_dialect(sample) is not None              # シェバン行が存在
      and shebang_language(sample) is None                 # 対応言語に解決しない
  ```

  `shebang_language` と `shebang_dialect` は**同一の第1物理行解釈・同一の env/版剥がし規則**を共有する（両者の不整合を禁ずる＝writing-plans で共通ヘルパに集約）。perl/groovy は `shebang_language` が解決するため記録されず、python/awk 等は `shebang_language==None ∧ shebang_dialect=="other"` で引き続き記録。既知拡張子＋非シェルシェバン（`.c`＋`#!/usr/bin/perl` 等＝`test_pipeline_dialect.py` の負契約）は第1項 `not extension_resolves_language` が False で記録されない（v1 不変）。

---

## 4. 分類器規則（マスター §7 への差分・confidence=medium）

`category` はマスター §7 の共通上位（比較/代入/引数/宣言/出力/分岐）＋ return。`category_sub` 初版**空固定**。規則は**先頭一致優先**（`regex_classifier._apply`）。

**マスク経路の確定（review C-A）**: 既存 `classify_sql`/`classify_shell` は**生行**で判定する（マスクしない）。本書はこれを変えない（Inv-B）。新規 `classify_perl`/`classify_groovy` は **classifier 内で対応 `mask()` を適用してから**規則を当てる（コメント/文字列内キーワード誤爆の抑止・signature は `classify_hit` 不変）。**PL/SQL（sql）は生行のまま**新規則を当て、文字列/コメント内キーワードの誤爆は §8.4 既知境界（v1 の生行 sql 分類と同クラス・medium）。誤爆は §4.1 の**行頭アンカー化**で実務上ほぼ回避する。

### 4.1 PL/SQL（既存 `_SQL_RULES` への行頭アンカー付き append・review C-B/I-2 反映）

既存規則（順序・挙動とも**不変**）:

```
1. :=                          → 代入
2. \bWHERE\b.*?[=<>]           → 比較   (IGNORECASE)
3. \bCASE\s+WHEN\b|\bDECODE\s*\(|\|\|  → 分岐 (IGNORECASE)
4. \b(?:INSERT|UPDATE)\b       → 代入   (IGNORECASE)
```

末尾に append（**出力を宣言/分岐より前に置く**・宣言とループは**行頭アンカー**＝行中の同名語/コメント/文字列内語を拾わない。すべて IGNORECASE）:

```
5. ^\s*(?:DBMS_OUTPUT\.PUT_LINE|RAISE_APPLICATION_ERROR)\b              → 出力
6. ^\s*(?:CREATE\s+(?:OR\s+REPLACE\s+)?)?(?:PROCEDURE|FUNCTION|PACKAGE(?:\s+BODY)?|TRIGGER|TYPE)\b → 宣言
7. ^\s*CURSOR\b                                                          → 宣言
8. \bIF\b.*\bTHEN\b | ^\s*ELSIF\b                                       → 比較
9. ^\s*(?:WHILE|FOR)\b | \bLOOP\s*$                                     → 分岐
```

- 規則8（IF…THEN）を「比較」とするのは Java `if_statement`→比較 と整合。
- 行頭アンカーにより `DBMS_OUTPUT.PUT_LINE('FUNCTION x')`（→ 規則5 出力・規則6 は FUNCTION が行頭でないので不発）・`OPEN c FOR SELECT`（FOR が行頭でない＝規則9 不発）・`-- this PROCEDURE …`（PROCEDURE が行頭でない）・`return 'WHILE waiting'`（WHILE が行頭でない）の誤爆を回避。
- **残存境界（§8.4）**: `SELECT type FROM …` のような行頭でない `type` 列名は規則に当たらず安全だが、行頭に手続き型キーワードと同名の識別子が来る病的ケースは medium の既知限界。
- **precedence 注記（review R2・アーキ#3）**: 既存規則1 `:=`（行頭非アンカーで `search`）は最優先。同一行に `:=` が同居する行（例 病的な `IF v := f() THEN`）は append 規則8（IF…THEN→比較）より先に規則1（代入）が確定する＝代入が勝つ。これは v1 不変の先頭一致挙動であり仕様（medium・golden 担保）。
- **Inv-B（review I-2）**: append が既存 sql golden 行の分類を変えないことは**規則の固有安全ではなく §8/§9 の再生成 diff ゼロで担保**する（diff が出たらレビュー承認）。

### 4.2 Perl（`classify_perl`・内部 mask 適用・先頭一致優先・review C-E/I-1 反映）

| 順 | 規則（mask 済み行に適用） | category |
|---|---|---|
| 1 | `^\s*sub\s+\w+` ／ `\bpackage\s+\w+` ／ `\buse\s+constant\b` | 宣言 |
| 2 | `^\s*(?:my\|our\|local\|state)\s+[$@%]` ／ `[$@%]\w+\s*=(?![=~>])` | 代入 |
| 3 | `\b(?:if\|unless\|elsif)\b` ／ `(?:==\|!=\|<=\|>=\|\beq\b\|\bne\b\|\blt\b\|\bgt\b\|\ble\b\|\bge\b\|=~\|!~\|(?<![-=])<(?!=)\|(?<![-=])>(?!=))` | 比較 |
| 4 | `\b(?:for\|foreach\|while\|until)\b` | 分岐 |
| 5 | `\b(?:print\|printf\|say\|warn\|die)\b` | 出力 |
| — | 不一致 | その他 |

- **代入 `(?![=~>])`（review I-1）**: `==`・`=~`・**`=>`（fat comma）**を代入から除外（`( $key => 1 )` を代入と誤判定しない）。
- **比較の裸 `<`/`>`（review C-E）**: `(?<![-=])<(?!=)` 等で `->`（メソッド矢印）・`=>`・`<=`/`>=` を除外（`$obj->method()` を比較と誤判定しない）。
- Perl に return カテゴリは設けない（`return $x` は その他）＝言語間で category 語彙が非対称（review I-9・§4 末尾に注記）。

### 4.3 Groovy（`classify_groovy`・内部 mask 適用・先頭一致優先・review C-F/C-E 反映）

| 順 | 規則（mask 済み行に適用） | category |
|---|---|---|
| 1 | `^\s*(?:class\|interface\|enum\|trait)\s+` ／ **`^\s*(?:[\w.<>,\s]+\s+)?def\s+\w+\s*\(`**（メソッド宣言＝`def name(`） | 宣言 |
| 2 | `^\s*(?:def\|final\|[A-Za-z_]\w*(?:<[^>]*>)?)\s+\w+\s*=(?!=)` ／ `\b\w+\s*=(?!=)` | 代入 |
| 3 | `\b(?:if\|while)\b` ／ `(?:==~\|<=>\|==\|!=\|<=\|>=\|=~\|(?<![-=])<(?!=)\|(?<![-=])>(?!=))` | 比較 |
| 4 | `\b(?:switch\|for\|case)\b` | 分岐 |
| 5 | `\breturn\b` | return |
| 6 | `\b(?:println\|print\|printf)\b\|\blog\.\w+` | 出力 |
| — | 不一致 | その他 |

- **`def x = 1` は代入（review C-F）**: 規則1の def は**メソッド宣言形 `def\s+\w+\s*\(` に限定**するため `def x = 1` は規則1を素通りし規則2（代入）で確定する。これにより設計内自己矛盾（§5.2 で `def`→var）を解消。category=代入・ref_kind=indirect:var は別概念（classify と chase を分離）。
- **比較の generics 除外（review C-E）**: `Map<String,Integer> m`（初期化なし）は規則2（代入・`=` なしなので不発）→規則3でも `<`/`>` を `(?<![-=])…(?!=)` で限定するが generics は語間に空白が無いため誤爆しうる→ 取りこぼし/誤分類は §8.4。`<=>`/`==~` は alternation 前方に置く（review M-1）。

> 規則の最終 precedence・境界は writing-plans/writing-tests で golden により確定する。本書は category 語彙・判定軸・上記の体系的誤りの是正方針を確定する。

---

## 5. chase 抽出・採否・ref_kind（マスター §8.1/§8.3/§9 への差分）

### 5.1 Perl Chaser（`perl_chaser.py`・新規・review C-D/I-2/I-3 反映）

- `mask(line)`: Perl のリテラル・コメントを同字数空白へ。対象＝`'…'`・`"…"`・`q(…)`・`qq(…)`・`#` から行末コメント。**`#` コメントは `$#`/`@#`（最終添字 sigil）を除外**＝`(?<![$@%])#[^\n]*`（review C-D: `$last = $#array;` を破壊しない）。**行単位**（heredoc・POD は対象外＝§8.4）。`q`/`qq` は `()` デリミタのみ対応（`qq{…}`/`q/…/` 等の任意デリミタは §8.4・review I-3）。`MASK_PATTERNS["perl"]` を追加。
- `extract(dialect, line)`（dialect 無視・マスク済み行に適用）:
  - **var**: `^\s*(?:my|our|local|state)\s+[$@%](\w+)\s*=` の捕捉名、および一般代入 `[$@%](\w+)\s*=(?![=~>])` の捕捉名。**sigil（`$`/`@`/`%`）を剥がして bare `\w+`** を追跡シンボルとする（マスター §8.1 字句追跡＝`:var`→var と同方針）。
  - **constant**: `\buse\s+constant\s+(\w+)`。
  - **getter/setter**: なし（§8.4）。
- **取りこぼし（review I-1・§8.4）**: `$h{key} = …`・`$x->{a} = …`（添字/デリファレンス挟み）は代入規則に当たらず取りこぼす。v1 既知境界として記録。

### 5.2 Groovy Chaser ＋ PL/SQL 宣言抽出の是正（review C-C/I-8 反映）

- Groovy `mask(line)`: `'…'`・`"…"`・`//`・`/* */`（行単位）。triple-quoted・slashy string `/…/` は §8.4。`MASK_PATTERNS["groovy"]` を追加。
- Groovy `extract`（マスク済み行に適用）:
  - **var**: `\bdef\s+(\w+)\s*=` ／ 型付き宣言 `[A-Za-z_]\w*(?:<[^>]*>)?\s+(\w+)\s*=(?!=)` の捕捉名、一般代入の末尾識別子。
  - **constant**: `\b(?:static\s+)?final\s+(?:[A-Za-z_]\w*(?:<[^>]*>)?\s+)?(\w+)\s*=`。
  - **getter/setter**: なし（§8.4）。
  - **限定子剥がし（review I-8・§8.4）**: `obj.field = …`・`this.x = …` は末尾識別子 `field`/`x` を抽出し限定子を失う（PL/SQL `rec.field :=` と同クラスの既知境界）。
- **PL/SQL 宣言抽出の是正（review C-C、R2-C1 回帰是正）**: 既存 `ORACLE_ASSIGN_RE = (?<![:&])\b(\w+)\s*:=` は `:=` 直前トークンを取るため、型付き宣言 `c_max CONSTANT NUMBER := 100` / `v_x NUMBER := 1` で**データ型名**（`NUMBER`）を var 抽出してしまう（汎用名爆発の温床）。
  - **R2-C1 の教訓（回帰の死角）**: v2 案の宣言形正規表現 `^\s*(\w+)\s+(?:CONSTANT\s+)?[\w%.\(\),\s]*?:=` は中間部が空マッチ可のため**通常代入 `a := 1; b := 2;` をも宣言形と誤判定**し、抑止規則で第2左辺 `b` を脱落させる（既存 `tests/unit/test_chase.py` の「同一行複数代入は全左辺を抽出」を破壊。golden に複数代入行が無く Inv-B diff ゲートでは検知不能）。
  - **是正方針＝宣言形は「名前と `:=` の間に実型トークンが在る」場合に限定し、抽出は per-`:=` で判定する**:
    - 各 `:=` 出現について直前を見る。`<id> <型トークン> :=`（id と `:=` の間に**先頭が英字の型トークンが1つ以上**ある／任意で `CONSTANT`／任意で `(size)`・`%TYPE`・`%ROWTYPE`）なら**宣言形**＝先頭 id を採る。`<id> :=`（型トークンなし）なら通常代入＝その id を採る。例: `(?<![:&])\b([A-Za-z_]\w*)(?:\s+(?:CONSTANT\s+)?[A-Za-z_][\w%.]*(?:\([^)]*\))?)?\s*:=`（group(1)＝先頭 id・finditer）。
    - **`re.IGNORECASE` 必須（review R3 Important）**: PL/SQL はキーワード大小無視のため、抽出・constant 判定の両正規表現を IGNORECASE で compile する。未指定だと小文字 `c_max constant number := 100` で `constant` 自体が「先頭 id＋型トークン」と解釈され var にリークする（constant 除外対象は `c_max` であって `constant` ではないため篩えない＝diff ゲート死角）。IGNORECASE 付与で大文字ケースと同一挙動（group(1)=`c_max`・constant 除外で空）になることを実走確認済み。
    - 先頭 id は `\w+` でなく **`[A-Za-z_]\w*`**（数字始まりトークンを拾わない＝v1 の `ORACLE_ASSIGN_RE` 識別子クラスと整合）。
    - これにより `a := 1; b := 2;` → `["a","b"]`（**温存**）、`v_x NUMBER := 1` → `v_x`（型名 `NUMBER` を出さない）、`c_max CONSTANT NUMBER := 100` → `c_max`、`emp_rec employees%ROWTYPE := NULL` → `emp_rec`、`v_name VARCHAR2(100) := 'a'` → `v_name`。
    - constant 判定は別途 `\b(\w+)\s+CONSTANT\b` の先頭 id（または上記で CONSTANT を伴った id）を constant とし、var 集合から除外（同名二重登録防止）。
    - 既存 golden/テストは単一の通常 `:=` のみ＝本是正後も結果同値（Inv-B）。**`tests/unit/test_chase.py` の複数代入ケースは保護対象＝§8/§9 の Inv-B/回帰に明示**。
  - **データ型名ストップリスト（review C-3 補完・二重防御）**: `NUMBER`/`VARCHAR2`/`DATE`/`BOOLEAN`/`PLS_INTEGER`/`CHAR`/`CLOB`/`BLOB`/`INTEGER`/`FLOAT` 等の Oracle 組み込み型を `stoplist.LANG_KEYWORDS["sql"]` に追加（既存 `_SQL_KW` への**追加**＝既存採否を緩めないことを Inv-B で確認）。万一型名が抽出経路を抜けても採否で篩う。

### 5.3 採否ポリシー — `stoplist.LANG_KEYWORDS` への新言語追加（review C-G・最重要）

`admit()`（`stoplist.py:65`）は `LANG_KEYWORDS.get(language, frozenset())` で言語別予約語を引く。perl/groovy 未登録だと**空集合**＝§8.3「① 言語キーワードを追跡集合に入れない」が**新言語で一切効かず**、`print`/`class`/`while`/`def`/`return` 等の予約語が sigil 剥がし後に横展開して**偽陽性爆発**（PRD 生命線違反）。よって以下を**必須追加**:

- `LANG_KEYWORDS["perl"]`: `my our local state sub package use require if unless elsif else while until for foreach do print printf say warn die return eq ne lt gt le ge cmp and or not x qw ...`（writing-plans で最終確定）。
- `LANG_KEYWORDS["groovy"]`: `def class interface enum trait if else while switch case for return break continue println print final static import package new this super true false null in as instanceof try catch finally throw ...`（同上）。
- `min_specificity`（既定）・`--stoplist`・決定的切り捨て（§8.3）は言語非依存で不変適用。

### 5.4 ref_kind × 言語マッピング（マスター §9 の表へ追記・本書が正本）

| 言語 | constant | var | getter/setter |
|---|---|---|---|
| SQL(Oracle/PL/SQL) | `CONSTANT` 宣言（先頭識別子） | `:=` 代入の左辺／宣言形の先頭識別子（型名は抽出しない・§5.2） | — |
| Perl | `use constant` | `my`/`our`/`local`/`state`・代入左辺（sigil 除去） | —（§8.4） |
| Groovy | `final`/`static final` | `def`/型付き宣言・代入左辺 | —（§8.4） |

- **constant は `ChaseSymbols.constants` フィールドへ（review I-1）**: `ref_kind=indirect:constant` は `kinds_of`（`_scan.py:51-54`）が constants を優先採用して `state.symbol_kind` に反映する経路で決まる。新 chaser は constant を **`vars` ではなく `constants` タプル**に入れること。
- **`extract_var_symbols`（公開 API・review I-2）**: `chase.extract_var_symbols`（sql/shell のみ分岐）は perl/groovy で空 list を返す（呼出元なし＝この API は使わず `extract_chase_symbols` 一本でよい）。本書はこの非対応を**意図的**として明記する。
- 停止性（マスター §8.1 手順5）不変＝抽出シンボルは有限母集合の字句識別子。sigil 剥がし後 `\w+` も母集合に属する。

---

## 6. snippet（マスター §9 への差分・review I-3/M-1/M-2 反映）

Perl/Groovy は AST 非使用＝sql/shell と同じ決定的ヒューリスティック（`snippet/_heuristic.py`）で切り出す。マスター §9 の上下対称展開＋上限クランプ（既定 12 行/800 文字・両端省略マーカ）は不変。

- `snippet/__init__.py:build_snippet` の `elif language in ("sql","shell")` 分岐に **perl/groovy を独立 elif で追加**（**sql/shell の既存分岐は literal 不変**＝else フォールスルーを共有しない・Inv-B 担保条件）。
- **`_heuristic.stop()` の制御フロー改修（review R2・アーキ Important1）**: 現 `stop()` は `if language=="sql": return …` の後、**shell を末尾の無条件 `return SH_TERMINATOR_RE.search(...)`（else 相当）で受ける**構造。perl/groovy 独立ブランチを足すには、この**末尾 shell return を `if language=="shell"` の明示ガードへ変える**必要がある（perl/groovy を末尾 else に巻き込まない）。これにより shell 判定挙動は literal 不変（Inv-B (d)）。境界語は `patterns/snippet_boundaries.py` に新 regex を追加: perl=`;`/`}`/`sub`、groovy=`;`/`}`/`class`/`def`（大文字小文字無視）。
- **chaser.mask の二重用途（review R2・アーキ Important2）**: `_heuristic` は境界判定の前処理に `chase.mask_literals(language, line)` を行ごと適用する。新 chaser の `mask()` は **classify（§4）と snippet 境界判定（本節）の両方に再利用**される＝両用途を満たすよう設計する（例: Perl の `$#`/`@#` 除外マスクは `_balanced()` のクオート計数にも効く）。writing-plans で mask を片方の用途だけに最適化しないこと。
- PL/SQL は既存 sql 境界語を据え置く（**新 PL/SQL 境界語を sql に追加しない**＝既存 sql snippet golden 不変）。複数行ブロックの snippet は §8.4（上限クランプで有限化）。

---

## 7. §8.4 既知境界（マスター §8.4 への追記）

マスター §8.4 を唯一の正本とし本書は追記する:

- **Perl**: heredoc・POD（`=pod`/`=cut`）・`eval`・シンボリックリファレンス・typeglob・正規表現合成名は追跡不可。**sigil 剥がしによる過剰一致**（`$foo`/`@foo`/`%foo`・hash キー・sub 名が同名 `foo` で合流＝字句追跡の仕様・medium）。`q`/`qq` は `()` デリミタのみ（任意デリミタ `qq{}`/`q//` 未対応）。`$h{k}=`・`$x->{a}=` 代入の取りこぼし。**リスト/分割代入 `my ($a,$b) = @_;`・`my ($self,%args)=@_;` は取りこぼし**（括弧内複数 sigil 非対応・review R2 Important）。
- **複合代入（Perl/Groovy 共通・review R2 Important）**: `+=`・`-=`・`.=`・`||=`・`*=`・`**=` 等の複合代入は classify（代入）でも var 抽出でも**対象外**（`\w+\s*=` が識別子と `=` の隣接を要求し演算子文字で破断する構造的限界）。変数変異の最頻形だが v1 行単位正規表現の既知境界として記録（medium）。
- **Groovy**: 複数行 GString／triple-quoted・slashy `/…/`（内部 `==`/`<` の比較誤爆含む）・closure 動的ディスパッチ・`${}` 補間名・メタプログラミング・型解決依存 auto getter/setter・generics `<…>` の比較誤爆/宣言取りこぼし・`obj.field=` の限定子剥がし・`<<`/`>>` シフト裸式の比較誤分類（代入 RHS 同居時は代入優先で非体系的）。
- **PL/SQL（据え置き＋追記）**: 複数行 DECLARE/BEGIN/END ブロック・動的SQL（EXECUTE IMMEDIATE）・複数行文・`%TYPE`/`%ROWTYPE`。行頭に手続き型キーワードと同名の識別子が来る病的行の誤分類（行頭アンカーで実務上は回避）。simple CASE（`CASE x WHEN`）は既存規則3が `CASE\s+WHEN` 限定のため searched CASE と挙動差（review I-5）。
- **非対応シェバン**: `python`/`awk`/`ruby` 等は解決せず `unsupported_shebang`（§3.2）。python は track A で昇格予定。版番号付き basename は perl/groovy では版剥がしで対応するが、**shell 副方言判定（`shebang_dialect`）は版剥がしをしない**ため `#!/bin/bash5` 等の版番号付き shell シェバンは従来どおり `"other"` 扱い（v1 既存挙動・review R2 Minor）。

---

## 8. 不変条件 Inv-B（受け入れゲート・review I-2 反映で正直化）

> **Inv-B: 本サブプロジェクトは v1 の既存 golden を byte 不変に保つ。** これは**規則の固有安全性ではなく、既存 golden 全件の再生成 diff がゼロであることで担保する外形ゲート**である。

- 触れる v1 経路: (a)`_SQL_RULES` への行頭アンカー append（§4.1）、(b)`sql_chaser` 宣言抽出是正（§5.2）、(c)シェバン一般化（§3.2）、(d)`_heuristic.py`/`build_snippet` への perl/groovy 独立分岐追加（§6・既存分岐 literal 不変）、(e)`stoplist.LANG_KEYWORDS` の sql データ型追加（§5.2）・perl/groovy キー追加（§5.3・既存キー不変＝additive）、(f)`pipeline.py` の `unsupported_shebang` 条件具体化（§3.2・python 等の既存挙動を保つ）。
- (a)〜(f) が既存 java/c/proc/sql/shell の **golden 出力を byte 変えない**ことを再生成 diff ゼロで実証する。diff が出た場合は「意図的変更か誤りか」をレビュー承認対象とし、誤りは除去する（churn を放置しない）。
- **diff ゲートの死角に注意（review R2-C1）**: golden は「ヒット行の TSV」を固定するが、**golden に現れない入力パターンに対する v1 字句追跡能力の退行は diff ゼロでも検知できない**（例: 複数代入 `a:=1;b:=2` 行は golden 不在）。よって Inv-B は golden diff だけでなく **既存 unit テスト（特に `tests/unit/test_chase.py` の複数代入・型付き宣言抽出）を全件 green に保つ**ことを併せてゲートとする。(b) sql_chaser 是正はこの unit 群を破壊しないことが必須条件（§5.2 是正方針はこれを満たす）。
- **既存 unit/integration テストの意図的改訂は Inv-B 違反ではない（review C-1）**: §3.2 のシェバン一般化に伴い、`test_dispatch.py` の perl 期待値（旧 `c`→新 `perl`）・`test_pipeline_dialect.py` の `unsupported_shebang` フィクスチャ（perl→python/awk へ移植）を改訂する。これは golden byte ではなくテスト契約の意図的更新であり、§9 で明示する。
- Inv-B はフェーズ完了ゲート（マスター §15 準拠）。

---

## 9. テスト/golden 計画（マスター §11 への差分）

`.claude/skills/writing-tests.md` 準拠。カバレッジ: 言語×ref_kind 必須網羅、文字コード/多ホップ pairwise 直交。

**必須回帰ケース（名指し）**:

- **Inv-B**: 既存 v1 golden 全件 byte 不変（§8）。
- **既存テスト改訂（review C-1）**: `test_dispatch.py` の `#!/usr/bin/perl`→`perl` 期待・`test_pipeline_dialect.py` の unsupported フィクスチャを python/awk へ移植。
- **採否（review C-G・最重要）**: perl/groovy の予約語（`print`/`class`/`while`/`def`/`return` 等）が**追跡集合に入らない**（`admit`/`partition` の unit）。データ型名（`NUMBER`/`VARCHAR2`）が sql で追跡集合に入らない。
- **PL/SQL**: 手続き型宣言分類（行頭 PROCEDURE/FUNCTION/PACKAGE→宣言）・`IF…THEN`→比較・`WHILE`/`FOR…LOOP`→分岐・`DBMS_OUTPUT.PUT_LINE`→出力・`DBMS_OUTPUT.PUT_LINE('FUNCTION')`→**出力**（誤宣言でない・C-B 回帰）・`OPEN c FOR SELECT`→**分岐でない**（C-B 回帰）・型付き宣言 `v_x NUMBER := 1`→var=`v_x`（**型名 NUMBER でない**・C-C 回帰）・`CONSTANT`→constant・拡張子 `.pkb`/`.pks`→sql。
- **PL/SQL 抽出回帰（review R2-C1・既存 `test_chase.py` 保護）**: `a := 1; b := 2;`→var=`["a","b"]`（複数代入を脱落させない）・`c_max CONSTANT NUMBER := 100`→constant=`c_max` のみ（var に `NUMBER` を出さない・同名二重登録なし）・`x := y`（通常代入）→var=`x`・**小文字 `c_max constant number := 100`→constant=`c_max`（`constant` を var にリークさせない・IGNORECASE 回帰・R3）**。
- **constant→ref_kind 経路（review R2 Imp-2）**: perl `use constant`／groovy `final`／sql `CONSTANT` が `ChaseSymbols.constants` に入り（chaser unit）、`kinds_of`→`symbol_kind`→`_REF_KIND` 経由で `ref_kind=indirect:constant` になる（多ホップ golden または fixedpoint unit で固定）。誤って `vars` に入ると `indirect:var` に化ける退行を検知する。
- **Perl**: direct・indirect:var（`my $x`）・indirect:constant（`use constant`）・sigil 剥がし過剰一致の代表ケース・拡張子なし＋`#!/usr/bin/perl`→perl・`$last = $#array`→マスクで破壊されない（C-D 回帰）・`$obj->method()`→比較でない（C-E 回帰）・`( $k => 1 )`→代入でない（I-1 回帰）・各 category。
- **Groovy**: direct・indirect:var（`def x =`＝代入かつ var 抽出・C-F 回帰）・宣言（`def foo()`）・indirect:constant（`final`）・拡張子なし＋`#!/usr/bin/groovy`→groovy・`Map<String,Integer> m`→比較でない（C-E 回帰）・各 category。
- **一般化シェバン回帰**: 拡張子なし＋`#!/usr/bin/python` は引き続き `unsupported_shebang`（B では昇格しない）／`#!/usr/bin/perl5.36`→perl（版剥がし・I-6）。
- **多ホップ**: perl var→chain・groovy var→chain を各1（新 chaser で §8.1 不動点・chain 正規形を固定）。
- **文字コード直交**: 新言語1ケースを非UTF-8（cp932 または euc-jp・判定値 pin）。

**層**: `tests/unit/`（classify 規則・chaser extract/mask・stoplist・シェバン一般化）／`tests/golden/`（言語×ref_kind 合成ツリー・`{SOURCE_ROOT}` 逆置換比較機構）／`tests/integration/`（perl/groovy/plsql 混在 CLI・`--resume`）／`tests/handcrafted/`（非ゲート）／`tests/perf/`（非ゲート・正規表現のみ＝`_ITEMS_PER_MB` 再測定不要）。

---

## 10. マスター §14/§15 への反映（本書承認後にマスターへ反映）

- §2.3/§14: PL/SQL（sql 統合・正規表現）・Perl・Groovy を「v2 対応済」へ。残り（Kotlin・C#/VB.NET）はユーザースコープ外、TS/JS・Python・JSP・Angular は track A/C 継続。
- §15: 本書を **フェーズ5（v2 正規表現トラック）** として追加（フェーズ4 完了後・着手前提＝フェーズ1〜4 完了済）。完了基準＝§8 Inv-B ＋ §9 必須回帰グリーン。

---

## 11. 決定事項サマリ（レビュー観点の明示）

1. PL/SQL は **既存 `sql`（Oracle 方言）へ統合**（新 language を作らない）。
2. **複数行解析はしない**（§8.4 据え置き）。
3. Perl/Groovy は **新 language 値**・行単位正規表現・confidence=medium。
4. Perl は **sigil 剥がしで bare 識別子を追跡**（過剰一致は §8.4・§8.3 で緩和）。
5. getter/setter は Perl/Groovy とも **不追跡**（§8.4）。
6. シェバン検出を **interpreter→言語 一般化**（perl/groovy 昇格・python 据え置き unsupported・版剥がし対応）。
7. プラグイン構造は **v1 パターン踏襲（案1）**。
8. **Inv-B（v1 golden byte 不変）** は**再生成 diff ゼロのゲート**で担保（規則固有安全に依存しない）。
9. **新依存ゼロ**。
10. **dispatcher 外の言語依存3箇所**（`stoplist.LANG_KEYWORDS`・`pipeline.py` shebang 条件・`build_snippet` 言語分岐）を拡張点に明記（review round1 の最重要収束）。
