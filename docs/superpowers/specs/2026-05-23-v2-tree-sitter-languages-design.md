# v2 tree-sitter トラック言語追加 設計書（サブプロジェクト A）

- 日付: 2026-05-23
- 区分: マスター設計書 `2026-05-16-grep-analyzer-design.md` への差分設計（master を正、本書が触れない事項は master に従う）
- 対象: PRD `docs/product-requirements.md` v2+ 確定スコープのうち **A: tree-sitter トラック = TypeScript / TSX / JavaScript / Python**
- 前段: B（正規表現トラック・PL/SQL/Perl/Groovy）= `2026-05-22-v2-regex-languages-design.md`（完了）。順序 B → A → C。

---

## 1. 目的とスコープ

### 1.1 本書が対象とすること
1. tree-sitter ランタイム＋全 grammar を **0.21.3 → 0.23.x** へ移行（Python の aarch64 wheel が 0.21 系に無いため不可避。§4.2 G1 参照）。
2. 新言語 **typescript / tsx / javascript / python** を §5.2 プラグイン規約で追加。
   - classify（category 判定）= tree-sitter AST（java/c と同列・confidence=high）。
   - chaser（indirect シンボル抽出）= **AST 化＝該当行を含む束縛導入ノードの部分木から抽出（複数行可）= 方向X**。
3. dispatch（拡張子/シェバン）・stoplist・snippet・fixedpoint 抽出経路の追加。

### 1.2 本書が対象としないこと（master / 後続）
- 既存 java/c の chaser の AST 化統一（本サブプロジェクトでは行ベース据え置き＝golden 安定。§9 後続として明記）。
- 正規表現トラック（PL/SQL/Perl/Groovy）および既存 java/c の chaser の複数行化（単一行据え置き）。
- track C（JSP / Angular 埋め込み・本トラックに依存）。
- 型解決に依存する getter/setter 呼出側追跡（PRD レッドライン・§7）。
- tree-sitter Oracle/PL-SQL grammar 採用（master §14）。

### 1.3 確定スコープ判断（ブレインストーミング結果）
- **スコープ分割**: 単一サブプロジェクト A。内部を Phase A0（移行）→ Phase A1（3言語追加）の2フェーズに分け、A0 に golden ゼロdiff ゲート（G-A0）を置く。
- **chaser 方向**: 方向X（tree-sitter トラックのみ AST chaser 化）。理由は §3.3。

---

## 2. §4.2 G1 ゲート（track A 再ベースライン・経験的実証済）

開発環境（x86_64 / cp312）で `pip download --only-binary=:all: --platform manylinux_2_17_<arch> --platform manylinux2014_<arch> --python-version 312 --implementation cp --abi abi3 --abi cp312` により wheel 取得可否を実証（2026-05-23）。

| 候補ライン | runtime | java | c | python | javascript | typescript | 判定 |
|---|---|---|---|---|---|---|---|
| 現行 0.21.x | 0.21.3 ✅ | ✅ | ✅ | **0.21.0 は x86_64 のみ・aarch64 wheel 無し ❌** | ✅ | ✅ | **不可** |
| **0.23.x（採用）** | 0.23.2 ✅ | 0.23.5 ✅ | 0.23.4 ✅ | 0.23.6 ✅ | 0.23.1 ✅ | 0.23.2 ✅ | **全6点 aarch64+x86_64 完備** |
| 0.25.x | 0.25.0 ✅ | ❌ | 0.24.1 ✅ | 0.25.0 ✅ | 0.25.0 ✅ | ❌(0.23.2止) | 不可 |

- **採用版ピン**: `tree-sitter==0.23.2`, `tree-sitter-java==0.23.5`, `tree-sitter-c==0.23.4`, `tree-sitter-python==0.23.6`, `tree-sitter-javascript==0.23.1`, `tree-sitter-typescript==0.23.2`。grammar wheel は全て `cp38-abi3` で 0.23 系 ABI に整合（py-tree-sitter 0.23.2 と同居実証済）。
- ABI混在不可（grammar は runtime と同一 ABI ライン必須）のため、runtime と全 grammar を 0.23.x へ束で移行する。
- requirements.lock を `--hash` 付きで再生成し、wheelhouse へ aarch64+x86_64 の 6×2＝12 wheel（既存 java/c は版更新）を同梱。pytest 等テスト/ビルド依存は不変。
- **このゲートは充足済み**＝writing-plans 着手可（master §4.2 / §15 フェーズ0 相当）。

---

## 3. アーキテクチャ

### 3.1 フェーズ構成
```
Phase A0  ランタイム移行 0.21.3 → 0.23.x（機能変更なし）
          ├ pyproject / requirements.lock / wheelhouse を §2 採用版へ更新
          ├ ts_classifier.py の 0.23 API 適合（§4.1）
          └ ゲート G-A0: 既存 golden 全件 再生成 diff = ゼロ
Phase A1  typescript / tsx / javascript / python 追加（B の11拡張点 ＋ 方向X AST chaser）
```

### 3.2 役割分担
| 経路 | 実装 | confidence |
|---|---|---|
| classify（category） | tree-sitter AST・親ノード climb（`classify_ts` を新言語へ拡張・§5） | high（java/c と同列） |
| snippet（表示範囲） | AST ノードスパン（`snippet/_ts.py` を新言語へ拡張・§7） | — |
| chaser（indirect 抽出） | **AST 化＝束縛導入ノード部分木から抽出（複数行可）・§6** | constant/var=指定 ref_kind、getter/setter=terminal 非拡張 |

正規表現トラック（PL/SQL/Perl/Groovy）と既存 java/c の chaser は単一行据え置き。AST chaser は新4 language 値（typescript/tsx/javascript/python）専用。

### 3.3 方向X 採用理由
- tree-sitter 言語では classify/snippet は既に複数行（AST スパン）。残る単一行制約は chaser のみ。
- chaser を AST 化すれば、複数行に割れた宣言・Python `@property`/`@x.setter`（`decorated_definition` 単一ノード）を**壊れやすいステートフル正規表現でなく決定的な AST 構造から**抽出できる。
- 正規表現トラックの複数行化は依然リスク大のため対象外（限界費用が高く、決定性担保が困難）。

### 3.4 対象 language 値と拡張子
| language 値 | 拡張子 | grammar（変種） | shebang |
|---|---|---|---|
| `typescript` | `.ts` | tree-sitter-typescript `language_typescript()` | — |
| `tsx` | `.tsx` | tree-sitter-typescript `language_tsx()` | — |
| `javascript` | `.js` `.mjs` `.cjs` `.jsx` | tree-sitter-javascript `language()`（JSX 内包） | `node` |
| `python` | `.py` | tree-sitter-python `language()` | `python`（`_SHEBANG_LANG` 準備済キーを有効化） |

- JSX は js grammar が内包。TSX のみ別変種が必要なため `tsx` を独立 language 値とする。
- 判定不能フォールバックは既存どおり C（master §5.1）。

---

## 4. Phase A0: ランタイム移行

### 4.1 0.23 API 適合（`classifiers/ts_classifier.py`）
0.21 → 0.23 の差分は2箇所に局在（ノード走査 API `start_point`/`children`/`parent`/`type`/`start_byte`/`end_byte` は不変）。実測（0.23.2）で下記が成立することを確認済み：
- `Language(ptr, "name")`（2引数）→ **`Language(capsule)`（1引数）**。`tree_sitter_<lang>.language()` は capsule を返す。
- `Parser()` ＋ `p.set_language(lang)` → **`Parser(lang)`**（コンストラクタ）。
  - 該当行: 現 `_JAVA = Language(tree_sitter_java.language(), "java")` / `_C = Language(..., "c")`（line 15-16）、`_parser` の `Parser()`＋`set_language`（line 37-38）。

### 4.2 grammar ロード
`ts_classifier.py` に typescript/tsx/javascript/python の `Language` を追加し、`_parser(language)` を language→Parser のマップ化（typescript は `language_typescript()`、tsx は `language_tsx()`）。

### 4.3 ゲート G-A0（移行の正しさ＝外形ゲート）
`tree-sitter` 版更新は java/c/proc の classify+snippet にのみ波及。**既存 golden 全件（java/c/proc/sql/shell/perl/groovy）を再生成し diff = ゼロ**を必須とする。
- 実測（§5.3）で 0.23 の java/c ノード型は現行 `_CATEGORY_BY_NODE`（`field_declaration`/`local_variable_declaration`/`if_statement`/`switch_expression`/`assignment_expression`/`return_statement`）および C（`preproc_def`/`declaration`/`case_statement` 等）と一致 → diff ゼロ見込み。
- 万一 diff（ノード型名 rename 等）が出た場合のみ、`_CATEGORY_BY_NODE` / `snippet/_ts.py` の `_GRAN_JAVA`/`_GRAN_C`/`_STMT`/`_BLOCK` を差分吸収して再ゼロ化する（機能変更は加えない）。

---

## 5. Phase A1: classify（category 判定）

`classify.py:classify_hit` の `language in ("java","c","proc")` 分岐に `typescript/tsx/javascript/python` を追加し `classify_ts(language, file_text, lineno)` へ委譲（signature 不変・additive）。`classify_ts` 内で言語別 `_CATEGORY_BY_NODE` を引く。

### 5.1 category マップ（実測ノード型・既存 `比較/分岐/宣言/代入/return/その他` 分類に準拠）
| category | Python | JavaScript | TypeScript 追加（tsx は TS 共用） |
|---|---|---|---|
| 比較 | `if_statement` | `if_statement` | （JS と同） |
| 分岐 | `match_statement` | `switch_statement` | |
| 宣言 | `import_statement` | `lexical_declaration` / `variable_declaration` / `field_definition` | `enum_declaration` / `interface_declaration` / `type_alias_declaration` / `public_field_definition` |
| 代入 | `assignment` | `assignment_expression` | |
| return | `return_statement` | `return_statement` | |
| その他 | for/while/def/class/jsx 等 | for/while/function/class/jsx 等 | |

- climb は java/c と同一（`node_at_line`→最初に一致する category ノードの値）。一致なしは「その他」。
- Python は構文上 宣言/代入 を区別不可のため `assignment`→代入 に統一（§8 既知限界）。

---

## 6. Phase A1: chaser（indirect 抽出・AST 化＝方向X）

### 6.1 抽出/投入の分離（fixedpoint 統合）
現状 `ingest_one`（`fixedpoint/_ingest.py`）は単一物理行に `extract_chase_symbols(lang,dialect,line)`＋`kinds_of(line)` を適用。これを **「抽出（行 or 文サブツリー → `ChaseSymbols`＋kinds）」と「投入（→ ChaseState）」に分離**する。投入ロジック（partition・introducers・edge・terminal 非拡張）は不変。

| 言語クラス | 抽出入力 | 実装 |
|---|---|---|
| 行ベース（java/c/sql/shell/perl/groovy） | 1物理行 | 既存 `extract_chase_symbols`（**byte 挙動不変**） |
| ASTベース（typescript/tsx/javascript/python） | (file text, lineno) | 新 `extract_chase_symbols_tree(lang, text, lineno)` |

### 6.2 AST 抽出をどこで行うか（方式A 採用）
- **方式A（採用）**: scan worker `_scan_file`（`fixedpoint/_scan.py`）が AST 言語ファイルを 1 回 parse（既に text 保持）し、found 各 occurrence の `ChaseSymbols`＋kinds を worker で計算し found タプルへ同梱。seed（`_seed.py`）は既に seed ファイルを main で読むため同関数を main で呼ぶ。→ **「親に bytes 非常駐」の streaming 設計を維持**・並列のまま・file 単位 1 パース。
- `found` タプル `(symbol, lineno, line)` → `(symbol, lineno, line, chase_symbols, kinds)`。行言語は新フィールド None 充填＝既存 ingest 経路を byte 不変に通す。`scan_hop` の集約・ソートキー `(lineno, symbol)` は位置参照のため不変。
- 不採用: 方式B（ingest 側で再read＋parse＝並列性喪失・I/O重複）、方式C（worker が text を親へ返す＝bytes 非常駐設計を破る）。

### 6.3 束縛導入ノード選択（決定的）
`node_at_line`（既存・`(行スパン, start_byte, end_byte, 型)` 最小キーで一意）で該当行の最小葉を取り、最寄りの**束縛導入ノード**へ climb。その部分木を preorder ソース順に走査し束縛名を抽出（決定的）。複数行宣言・`@property`+`def` も同一サブツリー内に収まる。

### 6.4 束縛ノードと抽出規則（実測トークンで確認済）
| 言語 | 束縛ノード | 規則 |
|---|---|---|
| Python | `assignment` | LHS 識別子。名が `^[A-Z_][A-Z0-9_]+$`（全大文字・2文字以上）→**constant**、他→**var**。`pattern_list`（a,b=…）→各 var |
| | `decorated_definition` | decorator が `(identifier)` で `property` →**getter**／`(attribute … attribute: setter)` →**setter**（名=内側 `function_definition` の name） |
| JavaScript | `lexical_declaration` | 先頭匿名トークン `const`→**constant**／`let`→**var**。`variable_declarator` の `name:`（identifier、分割代入 `object_pattern`/`array_pattern` は各 `shorthand_property_identifier_pattern`/identifier） |
| | `variable_declaration`（var） | →**var** |
| | `assignment_expression` | `left:` が identifier →**var**（java 同様の再代入追跡） |
| | `field_definition` | `property_identifier`/`private_property_identifier` →**var** |
| | `method_definition` | 先頭匿名トークン `get`→**getter**／`set`→**setter**（名=`property_identifier`）。トークン無は通常メソッド→抽出せず |
| TypeScript 追加 | `public_field_definition` | 先頭匿名トークン `readonly`→**constant**／他→**var**（`accessibility_modifier` は無視・名=`property_identifier`） |
| | `enum_declaration` | `enum_body` の `property_identifier` 群→**constant** |
| | （`interface_declaration`/`type_alias_declaration`） | 型のみ＝**抽出せず** |

- 型注釈は `type:` フィールドに分離され名側に混入しない（generics の型識別子も抽出されない）。
- AST 抽出のためマスク不要。AST 言語の chaser モジュールは行版 `mask()`/`extract()` を実装しない（`mask_literals` は heuristic snippet 専用＝AST 言語は §7 の AST スパンを使用）。
- getter/setter は terminal（非拡張）＝既存 `scan_term`/`getter_setter_no_expand` 経路（master §8.3 PRD レッドライン）。

### 6.5 stoplist（`stoplist.py:LANG_KEYWORDS`）
`typescript`/`tsx`/`javascript`/`python` の予約語 frozenset を追加（§8.3 keyword 篩を新言語で有効化＝偽陽性抑止）。B の perl/groovy 追加と同型・additive（既存キー不変）。

---

## 7. Phase A1: snippet（`snippet/_ts.py` 拡張）

§9 の二段選択（`node_at_line`→粒度ノードへ climb）を流用し、`_GRAN_JAVA`/`_GRAN_C` に倣う per-language 粒度集合を追加。既存の行・文字数セーフティ上限はそのまま適用。
- 初期粒度集合（plan 時に代表例で最終検証）:
  - Python: `if_statement`/`while_statement`/`for_statement`/`match_statement`/`return_statement`/`expression_statement`/`decorated_definition`/`import_statement`
  - JS/TS: `lexical_declaration`/`variable_declaration`/`if_statement`/`while_statement`/`for_statement`/`switch_statement`/`return_statement`/`expression_statement`/`field_definition`/`public_field_definition`/`method_definition`
- `build_snippet`（`snippet/__init__.py`）の tree-sitter 分岐へ新 language 値を追加（java/c/proc と同経路）。

---

## 8. 既知限界（master §8.4 追加）
- Python: 宣言/代入 を構文上区別不可（`assignment`→一律 代入）。constant 判定は **ALL_CAPS 命名規約ヒューリスティック**（`typing.Final[]` 型注釈・`enum.Enum` 継承は見ない）。
- TS/JS: 型解決に依存する getter/setter 呼出側追跡は不可（構文的アクセサ**定義**のみ抽出）。
- 動的プロパティ・computed member（`obj[expr]`）・reflection・動的クラス名は追跡不可。
- import されたシンボルはファイルスコープのみ（モジュール解決なし）。
- TSX/JSX: コンポーネント属性等は category その他。
- 同一行に複数文がある場合、`node_at_line` の最小キーで決定的に1ノードを選ぶ（ヒット列に依存しない・master §9 既存方針と同様）。

---

## 9. 不変条件 Inv-A
**Inv-A: トラックAは既存 golden を byte 不変に保つ（新言語 golden 追加を除く）。** B の Inv-B と同型の外形ゲートで担保する。

- **Phase A0**: ゲート G-A0（§4.3）＝既存 golden 全件 再生成 diff ゼロ。
- **Phase A1**:
  - classify/dispatch/stoplist/snippet の追加は additive（既存分岐・キー・literal 不変）。
  - `found` タプル拡張は行言語で None 充填＝既存経路 byte 不変。
  - **抽出/投入分離リファクタ（§6.1）は行言語の挙動を完全保存**し、golden ゼロdiff＋既存 fixedpoint ユニットで実証する（決定的コアに触れる唯一の変更）。
- 後続（本サブプロジェクト外）: 既存 java/c の chaser を AST 化して2系統を統一（その際は java/c golden を意図的再生成＋レビュー）。

| リスク | 緩和 |
|---|---|
| R1: 0.23 で java/c ノード型 drift | G-A0 ゼロdiff ゲート（実測一致）／差分はノード型集合で吸収 |
| R2: 抽出/投入分離が決定的コアの挙動変更 | 挙動保存リファクタ・golden ゼロdiff＋既存ユニット・行言語呼出経路 byte 同一 |
| R3: AST chaser 非決定性 | `node_at_line` 最小キー＋preorder ソース順・worker isolation 維持（per-file 純関数） |
| R4: worker 内パースの perf | hop 毎の既読ファイルに parse 増分のみ（正しさ無関係） |
| R5: ABI/wheel | §2 G1 実証済・lock 再生成（hash付）・多アーキ wheelhouse |
| R6: getter/setter 非拡張（PRD レッドライン） | terminal・`scan_term`/`getter_setter_no_expand` 経路で非拡張 |

---

## 10. テスト
- **言語×ref_kind golden**（各言語 direct〔各 category〕＋ indirect チェーン）
  - Python: indirect:var（小文字）/constant（ALL_CAPS）/getter（@property）/setter（@x.setter）＋複数行宣言
  - JS: const→constant / let→var / get・set→getter・setter / 分割代入 / 複数行宣言 / field
  - TS: readonly→constant / enum members→constant / public field→var ／**generics の型識別子を誤抽出しないこと**
  - TSX: direct ＋ 1 チェーン
- **G-A0 ゲート**: 既存 golden 全件 byte 不変（再生成 diff ゼロ）
- **単体**: dispatch（拡張子/シェバン）, stoplist（新キー）, classify（各言語 category）, **AST chaser tree抽出（各束縛ノード）**, snippet span, 抽出/投入分離後の fixedpoint
- **直交/決定性**: 文字コードは既存 pairwise 方針／2回実行 byte 一致（既存機構）／0.23 API smoke（Language/Parser ロード）

---

## 11. 拡張点一覧（B の11項目テンプレートを track A へ写像）
| # | ファイル | 差分 |
|---|---|---|
| 1 | `pyproject.toml` / `requirements.lock` / `wheelhouse/` | tree-sitter 0.23.x 6点へ更新＋python/js/typescript grammar wheel 追加（aarch64+x86_64・hash付） |
| 2 | `classifiers/ts_classifier.py` | 0.23 API 適合（§4.1）＋ typescript/tsx/javascript/python の Language ロードと `_CATEGORY_BY_NODE`（§5.1） |
| 3 | `classify.py:classify_hit` | `language in (...)`→`classify_ts` 分岐へ4値追加（additive・signature 不変） |
| 4 | `dispatch.py` | 拡張子マップ（§3.4）＋シェバン `node`/`python`（§3.4） |
| 5 | `classifiers/{python,javascript,typescript}_chaser.py`（新規） | AST 抽出 `extract_chase_symbols_tree` 実装（tsx は typescript_chaser 共用）。`_CHASERS` には AST 言語として登録（行版 extract/mask は持たない） |
| 6 | `fixedpoint/_ingest.py` / `_seed.py` / `_scan.py` | 抽出/投入分離（§6.1）・方式A の worker 内 AST 抽出（§6.2）・found タプル拡張 |
| 7 | `chase.py` | AST 言語向け `extract_chase_symbols_tree` dispatcher 追加（行言語は既存経路） |
| 8 | `snippet/_ts.py` / `snippet/__init__.py` | per-language 粒度集合追加＋`build_snippet` 分岐へ4値追加（§7） |
| 9 | `stoplist.py:LANG_KEYWORDS` | typescript/tsx/javascript/python の予約語 frozenset 追加（§6.5） |
| 10 | `model.py` | コード変更なし（言語非依存）。ref_kind×言語は本書 §6.4 を正本 |
| 11 | `pipeline.py` | 追加変更なし（`unsupported_shebang` は B で具体化済・python/node は解決言語に昇格） |

---

## 12. master への反映（実装後）
- §2.3 / §14 / §15: track A（TS/TSX/JS/Python）完了を記録。残り track C（JSP/Angular）。
- §4.2 / §15 フェーズ0: track A の G1 再ベースライン（0.23.x 採用）を記録（正本は本書 §2、`phase0-gate-result.md` に追補）。
- §8.4: 本書 §8 の既知限界を追加。
- §14: 「既存 java/c chaser の AST 化統一」を後続候補として明記。
