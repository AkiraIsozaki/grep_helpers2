# v2 tree-sitter トラック言語追加 設計書（サブプロジェクト A）

- 日付: 2026-05-23
- 区分: マスター設計書 `2026-05-16-grep-analyzer-design.md` への差分設計（master を正、本書が触れない事項は master に従う）
- 対象: PRD `docs/product-requirements.md` v2+ 確定スコープのうち **A: tree-sitter トラック = TypeScript / TSX / JavaScript / Python**
- 前段: B（正規表現トラック・PL/SQL/Perl/Groovy）= `2026-05-22-v2-regex-languages-design.md`（完了）。順序 B → A → C。
- 改訂: 2026-05-23 批判的AIレビュー（3観点）反映。§6（chaser/fixedpoint 統合）を field-directed 抽出＋抽出/投入契約の精密化で全面改稿。

---

## 1. 目的とスコープ

### 1.1 本書が対象とすること
1. tree-sitter ランタイム＋全 grammar を **0.21.3 → 0.23.x** へ移行（Python の aarch64 wheel が 0.21 系に無いため不可避。§2 G1 参照）。
2. 新言語 **typescript / tsx / javascript / python** を §5.2 プラグイン規約で追加。
   - classify（category 判定）= tree-sitter AST（java/c と同列・confidence=high）。
   - chaser（indirect シンボル抽出）= **AST 化＝該当行を含む束縛導入ノードの `name:`/`left:` フィールドから field-directed 抽出（複数行可）= 方向X**。
3. dispatch（拡張子/シェバン）・stoplist・snippet・fixedpoint 抽出経路の追加。

### 1.2 本書が対象としないこと（master / 後続）
- 既存 java/c の chaser の AST 化統一（本サブプロジェクトでは行ベース据え置き＝golden 安定。§12 後続として明記）。
- 正規表現トラック（PL/SQL/Perl/Groovy）および既存 java/c の chaser の複数行化（単一行据え置き）。
- track C（JSP / Angular 埋め込み・本トラックに依存）。
- 型解決に依存する getter/setter 呼出側追跡（PRD レッドライン・§8）。
- tree-sitter Oracle/PL-SQL grammar 採用（master §14）。
- walrus `:=`・属性/添字代入・動的属性などの追跡（§8 既知限界）。

### 1.3 確定スコープ判断（ブレインストーミング結果）
- **スコープ分割**: 単一サブプロジェクト A。内部を Phase A0（移行）→ Phase A1（3言語追加）の2フェーズに分け、**A0 は独立してマージ可能な単位**とする（A0 を commit・golden 再ベースライン・全テスト緑にした上で A1 を積む。§3.1）。
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
- **このゲートは充足済み**＝writing-plans 着手可（master §4.2 / §15 フェーズ0 相当）。正本は本書 §2、`phase0-gate-result.md` に追補。

---

## 3. アーキテクチャ

### 3.1 フェーズ構成（A0 は独立マージ可能単位）
```
Phase A0  ランタイム移行 0.21.3 → 0.23.x（機能変更なし・独立してマージ／緑化）
          ├ pyproject / requirements.lock / wheelhouse を §2 採用版へ更新
          ├ ts_classifier.py の 0.23 API 適合（§4.1）
          └ ゲート G-A0（§4.3）: 既存 golden 全件 再生成 diff = ゼロ ＋ 既存ユニット/結合 全緑
                                  ＋ ノード型存在 smoke（§4.3）
Phase A1  typescript / tsx / javascript / python 追加（A0 緑の 0.23 基盤上に積む）
          （B の11拡張点テンプレート ＋ 方向X AST chaser）
```

### 3.2 役割分担
| 経路 | 実装 | confidence |
|---|---|---|
| classify（category） | tree-sitter AST・親ノード climb（`classify_ts` を新言語へ拡張・§5） | high（java/c と同列） |
| snippet（表示範囲） | AST ノードスパン（`snippet/_ts.py` を新言語へ拡張・§7） | — |
| chaser（indirect 抽出） | **AST 化＝束縛導入ノードの `name:`/`left:` フィールドから field-directed 抽出（複数行可）・§6** | constant/var=指定 ref_kind、getter/setter=terminal 非拡張 |

正規表現トラック（PL/SQL/Perl/Groovy）と既存 java/c の chaser は単一行据え置き。AST chaser は新4 language 値（typescript/tsx/javascript/python）専用。

### 3.3 方向X 採用理由
- tree-sitter 言語では classify/snippet は既に複数行（AST スパン）。残る単一行制約は chaser のみ。
- chaser を AST 化すれば、複数行に割れた宣言・Python `@property`/`@x.setter`（`decorated_definition` 単一ノード）を**壊れやすいステートフル正規表現でなく決定的な AST 構造から**抽出できる。
- 正規表現トラックの複数行化は依然リスク大のため対象外。

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
0.21 → 0.23 の差分は2箇所に局在。実測（0.23.2）で下記が成立することを確認済み：
- `Language(ptr, "name")`（2引数）→ **`Language(capsule)`（1引数）**。`tree_sitter_<lang>.language()` は capsule を返す。
- `Parser()` ＋ `p.set_language(lang)` → **`Parser(lang)`**（コンストラクタ）。
  - 該当行: 現 `_JAVA = Language(tree_sitter_java.language(), "java")` / `_C`（line 15-16）、`_parser` の `Parser()`＋`set_language`（line 37-38）。
- **不変であることを smoke で明示確認する 0.23 ノード/ツリー API**: `node.type` / `node.children` / `node.parent` / `node.start_point` / `node.end_point` / `node.start_byte` / `node.end_byte` / `node.has_error` / `node.is_missing` / `Tree.root_node`。`snippet/_ts.py:_has_error`（line 50 付近）が `has_error`/`is_missing`/`type=="ERROR"` に依存し、SJIS サロゲート対応の byte オフセット計算も `start_byte`/`end_byte`（UTF-8 バイト）に依存するため、これらは A0 の API 適合確認に**明示的に含める**。

### 4.2 grammar ロード
`ts_classifier.py` に typescript/tsx/javascript/python の `Language` を追加し、`_parser(language)` を language→Parser のマップ化（typescript は `language_typescript()`、tsx は `language_tsx()`）。`_parser`/`parse_tree` は `snippet/_ts.py` も import するため、両者が新言語を解決できること。

### 4.3 ゲート G-A0（移行の正しさ＝外形ゲート・二段＋proactive smoke）
`tree-sitter` 版更新は java/c/proc の classify+snippet にのみ波及。下記**3点すべて**を満たすことを必須とする（Inv-B の二段ゲートに倣い、golden の死角を proactive smoke で塞ぐ）。
1. **既存 golden 全件（java/c/proc/sql/shell/perl/groovy）を再生成し diff = ゼロ**。
2. **既存ユニット/結合テスト 全緑**（golden が固定するのは「存在する行」のみ＝死角があるため）。
3. **ノード型存在 smoke**: `_CATEGORY_BY_NODE`・`snippet/_ts.py` の `_GRAN_JAVA`/`_GRAN_C`/`_STMT`/`_BLOCK`/`_PAREN_ONLY` の**全キー**が 0.23 grammar に存在することを表明テストで確認（rename 検出。golden に現れない `switch_*`/`preproc_def`/`case_statement`/`try_*`/`do_statement`/`while_statement`/`for_statement` 等の死角を塞ぐ）。
- 実測（§5.3 probe）で 0.23 の java/c ノード型は現行集合と一致 → diff ゼロ見込み。万一 diff（rename 等）が出た場合のみ、当該ノード型集合を差分吸収して再ゼロ化する（機能変更は加えない）。

---

## 5. Phase A1: classify（category 判定）

`classify.py:classify_hit` の `language in ("java","c","proc")` 分岐に `typescript/tsx/javascript/python` を追加し `classify_ts(language, file_text, lineno)` へ委譲（signature 不変・additive）。`classify_ts` 内で言語別 `_CATEGORY_BY_NODE` を引く。climb は java/c と同一（`node_at_line`→最初に一致する category ノードの値、無ければ「その他」）。

### 5.1 category マップ（実測ノード型・既存 `比較/分岐/宣言/代入/return/その他` 分類に準拠）
| category | Python | JavaScript | TypeScript 追加（tsx は TS 共用） |
|---|---|---|---|
| 比較 | `if_statement` | `if_statement` | （JS と同） |
| 分岐 | `match_statement` | `switch_statement` | |
| 宣言 | `import_statement` / `import_from_statement` | `lexical_declaration` / `variable_declaration` / `field_definition` / `import_statement` | `enum_declaration` / `interface_declaration` / `type_alias_declaration` / `public_field_definition` |
| 代入 | `assignment` / `augmented_assignment` | `assignment_expression` / `augmented_assignment_expression` | |
| return | `return_statement` | `return_statement` | |
| その他 | for/while/with/def/class/jsx 等 | for/while/function/class/jsx 等 | |

- レビュー反映: `import_from_statement`（Python `from x import y`）、`augmented_assignment(_expression)`（`x += 1`）を追加。JS/TS も `import_statement` を 宣言 に含め Python との非対称を解消。
- `elif`/`else` は `if_statement` 子（`elif_clause`/`else_clause`）→ climb で `if_statement`=比較（実測確認）。`export const …` は `export_statement`→`lexical_declaration`=宣言（実測確認）。
- Python は構文上 宣言/代入 を区別不可のため `assignment`→代入 に統一（§8 既知限界）。

---

## 6. Phase A1: chaser（indirect 抽出・AST 化＝方向X）

### 6.1 抽出と投入の分離（fixedpoint 統合の中核・契約改訂）
**問題（レビュー C1）**: 現 `ingest_one`（`fixedpoint/_ingest.py`）は hop≥2・seed の各回で**単一物理 `line`** に `extract_chase_symbols(language,dialect,line)`＋`kinds_of(...)` を適用して*再抽出*する。AST 言語は `_CHASERS` に登録しない（§6.6）ため、この行ベース再抽出は空を返し、**連鎖が hop1 で途絶／kind が既定 "var" に化け／getter/setter terminal が発火しない**。`found` への同梱だけでは in-engine 再抽出点に届かない。

**解決**: `ingest_one` を「抽出（行 or AST → `ChaseSymbols`）」から分離し、**事前計算済みの `ChaseSymbols` と `kinds` を引数で受け取る**契約へ改訂する。投入ロジック（partition・introducers・edge・terminal 非拡張・`is_seed` 自己包含）は不変。

```
新契約:
  ingest_one(state, parent, chase_symbols: ChaseSymbols, kinds: dict[str,str], hop, is_seed=False)
    └ 内部で extract_chase_symbols / kinds_of を呼ばない（抽出は呼出側責務）

  kinds_of(chase_symbols: ChaseSymbols) -> dict[str,str]   # ← line 引数から ChaseSymbols 引数へ変更（言語非依存・既存バケット優先順 constant>var>getter>setter を維持）
```

| 言語クラス | 抽出（呼出側で実施） |
|---|---|
| 行ベース（java/c/sql/shell/perl/groovy） | `cs = extract_chase_symbols(lang,dialect,line)`（既存関数・**結果 byte 不変**）→ `kinds_of(cs)` |
| ASTベース（typescript/tsx/javascript/python） | `cs = extract_chase_symbols_tree(lang, text, lineno)`（§6.3）→ `kinds_of(cs)` |

- 行言語は ingest 内で従来 2 回呼んでいた抽出（line 35 と `kinds_of` 内）が**呼出側 1 回**へ集約されるが、同一 `ChaseSymbols` から同一 `kinds` を導くため**出力 byte 不変**（Inv-A）。
- AST 由来の `kinds` は同じ `kinds_of(cs)` から導かれ `ingest_one`→`state.symbol_kind.setdefault(...)` に正しく載る（→ `_finalize` の `_REF_KIND` が constant/getter/setter を正しく出力。レビュー C2(a) 解消）。

### 6.2 全3呼出点の改修（方式A: worker 内 AST 抽出）
1. **seed**（`fixedpoint/_seed.py`）: seed ファイルを main で読む既存経路を使い、AST 言語は `cs = extract_chase_symbols_tree(lang, text, s.lineno)`、行言語は `cs = extract_chase_symbols(lang, dialect, seed_line)`。**ファイル欠落/未読（`sp.is_file()` False）時は `cs = ChaseSymbols()`（空）**＝現 `seed_line=""` 相当。`kinds = kinds_of(cs)`、`ingest_one(occ, cs, kinds, hop=1, is_seed=True)`（`is_seed` 自己包含は投入側で従来どおり）。
2. **scan worker**（`fixedpoint/_scan.py:_scan_file`）: AST 言語ファイルを **1 回 parse**（既に text 保持）し、found 各 occurrence について `cs = extract_chase_symbols_tree(lang, text, lineno)` を**worker で計算**して found タプルへ同梱。→ **「親に bytes 非常駐」の streaming 設計を維持**・並列のまま・file 単位 1 パース。tuple へ載るのは `ChaseSymbols`（frozen dataclass of tuples＝pickle 安全）と primitives のみ＝tree-sitter オブジェクトは越境させない（`spawn` 安全）。
3. **absorb_results**（`fixedpoint/_ingest.py`）: found を**新タプル arity で unpack** し、AST 言語は同梱 `cs` を使用、行言語は `cs = extract_chase_symbols(lang,dialect,line)`（`line` から計算）。`kinds = kinds_of(cs)`、`ingest_one(child, cs, kinds, hop+1)`。

```
found タプル: (symbol, lineno, line)  →  (symbol, lineno, line, chase_symbols)
  chase_symbols: AST 言語は ChaseSymbols、行言語は None（absorb 側で line から計算）
  kinds は越境させず downstream で kinds_of(cs) により導出（I2 解消・kinds_of 経路一本化）
```
- `scan_hop` の集約・ソートキー `(lineno, symbol)`（位置参照）は不変。`chase_symbols` は `(relpath, lineno)` の純関数のため、chunk 重複時の同 `(lineno,symbol)` でも値が同一＝決定性は sort 安定性に依存しない（§9 R3）。
- 不採用: 方式B（ingest 側で再read＋parse＝並列性喪失・I/O重複）、方式C（worker が text/Tree を親へ返す＝bytes 非常駐設計を破る・unpicklable）。

### 6.3 束縛導入ノードの選択と field-directed 抽出（決定的）
`node_at_line`（既存・`(行スパン, start_byte, end_byte, 型)` 最小キーで一意）で該当行の最小葉を取り、`.parent` で**最寄りの束縛導入ノード**（§6.5 の集合）へ climb。
- **終端条件（レビュー I3）**: climb が束縛ノードに当たらず root（`module`/`program`）へ達したら **空 `ChaseSymbols` を返す**。利用箇所（use-site）の大多数はこの空経路＝行ベースで「`=` の無い行は何も抽出しない」のと同義で正しい。
- **field-directed 抽出（レビュー Critical・必須）**: 束縛ノードの**部分木を無差別 preorder 走査してはならない**（RHS の値・型識別子・プロパティキーを誤抽出する）。**`name:`/`left:` 等の束縛名フィールドのサブツリーのみ**を読み、`right:`/`value:`/`type:` は読まない。抽出順は当該フィールド部分木のソース順（決定的・**set による重複除去は禁止＝順序保持の tuple**）。

実証された誤抽出（無差別走査の場合・修正対象）:
- TS `const m: Map<string,number> = x` → `m` だけ正。無差別だと `Map`(type_identifier)・`x`(RHS) を誤抽出。
- JS `const {a: x} = o` → `x` だけ正。無差別だと キー `a`・RHS `o` を誤抽出。
- PY `a, b = f()` → `a,b` だけ正。無差別だと `f`(RHS) を誤抽出。

### 6.4 ALL_CAPS 定数ヒューリスティック（Python のみ）
Python は const キーワードを持たないため、`assignment`/`augmented_assignment` の LHS 識別子名が `^[A-Z_][A-Z0-9_]+$`（2文字以上の全大文字＋下線/数字）に一致 →**constant**、他→**var**。`_X`/`__ALL__` も一致（private/dunder も定数扱い・許容）、単一文字 `T`/`E`/`I` は不一致＝var（型変数・ループ変数の誤定数化回避）。constant は必ず `ChaseSymbols.constants` タプルへ入れる（`_REF_KIND` 駆動・B の I1 教訓）。JS/TS は const/readonly キーワードが正＝大小無関係（ALL_CAPS 不使用）。

### 6.5 束縛ノードと field-directed 抽出規則（実測ノード型・全網羅）
| 言語 | 束縛ノード | 読むフィールド | 規則 |
|---|---|---|---|
| **Python** | `assignment` / `augmented_assignment` | `left:` のみ | `identifier`→§6.4。`pattern_list`/`tuple_pattern`/`list_pattern`→各 `identifier`=var、`list_splat_pattern`(`*r`)→内 identifier=var。`attribute`(`self.x`)/`subscript`(`d[k]`)→**抽出せず**（束縛でなく変更・§8）。chained `a=b=1` は `right:` が `assignment` のとき限りそれを辿り `left:` を追加 |
| | `decorated_definition` | decorator＋内 def 名 | decorator が `(decorator (identifier))` で **テキスト=="property"** →**getter**、`(decorator (attribute object:(identifier) attribute:(identifier)))` で **attribute テキスト=="setter"** →**setter**（名=内 `function_definition` の `name:`）。`@staticmethod`/`@functools.cached_property` 等はテキスト不一致＝抽出せず |
| **JavaScript** | `lexical_declaration` | 各 `variable_declarator.name:` | 先頭匿名トークン `const`→**constant**／`let`→**var**（大小無関係）。`name:` が `identifier`→名。分割代入 `object_pattern`/`array_pattern`→`shorthand_property_identifier_pattern`=名、`pair_pattern`→`value:` のみ（`key:` 除外）、`object_assignment_pattern`→`left:`（`right:` 既定値除外）、`rest_pattern`→内 identifier、ネスト pattern は再帰 |
| | `variable_declaration`（var） | 同上 | →**var** |
| | `assignment_expression` / `augmented_assignment_expression` | `left:` | `identifier`→**var**。`member_expression`/`subscript_expression`→**抽出せず** |
| | `field_definition` | `property:` | `property_identifier`/`private_property_identifier`→**var**。`computed_property_name`→抽出せず |
| | `method_definition` | 先頭匿名トークン＋`name:` | `get`→**getter**／`set`→**setter**（名=`property_identifier`）。get/set 無＝通常メソッド→抽出せず。`computed_property_name`→抽出せず |
| **TypeScript 追加** | `public_field_definition` | 子トークン走査＋`name:` | 子に `readonly` トークンあり→**constant**／無→**var**（`accessibility_modifier` は named 子＝field-directed で自然に除外・名=`property_identifier`） |
| | `enum_declaration` | `enum_body` の各メンバ `name:` | 素メンバ `property_identifier` と `enum_assignment.name:`（`A=1` 形）の `property_identifier`→**constant** |
| | （`interface_declaration`/`type_alias_declaration`） | — | 束縛ノードに**含めない**（型のみ。メンバ名 `property_signature` 等を chase しない） |

- 型注釈は `type:` フィールド＝field-directed で読まないため generics 型識別子は混入しない（§6.3 実証）。
- 同一宣言の複数 declarator（`const a=trackedSym, b=2`）は宣言ノードへ climb し全 declarator 名を抽出＝**行ベース挙動と同等**（兄弟 declarator の軽微な過抽出は既存と同程度・許容）。

### 6.6 ASTChaser プロトコルとレジストリ（レビュー I1/I2）
`classifiers/base.py` に既存 `Chaser`（`extract(dialect,line)`/`mask(line)`）と別に `ASTChaser` Protocol を定義する：
```
class ASTChaser(Protocol):
    def extract_tree(self, text: str, lineno: int) -> ChaseSymbols: ...
```
- AST 言語の chaser は `extract_tree` のみ公開（`kinds` は返さない＝§6.1 の `kinds_of(cs)` で導出・所有権を一本化）。行版 `extract`/`mask` は持たない。
- **別レジストリ `_AST_CHASERS: dict[str, ASTChaser]`** に登録（typescript/tsx/javascript/python。tsx は typescript_chaser を共用）。行版 `_CHASERS` には登録しない。
- `chase.py` に `extract_chase_symbols_tree(language, text, lineno) -> ChaseSymbols`（`_AST_CHASERS` 参照）を追加。行言語は既存 `_CHASERS` 経路。
- `mask_literals`（`chase.py`）は `_CHASERS.get(AST言語)`→None→原行返却＝heuristic snippet 専用経路で安全（AST 言語は §7 の AST スパンを使い heuristic を通らない）。`extract_var_symbols`（sql/shell 専用）は AST 言語へ**意図的に非拡張**（既存どおり `[]`）。

### 6.7 stoplist（`stoplist.py:LANG_KEYWORDS`）
`typescript`/`tsx`/`javascript`/`python` の予約語 frozenset を追加（§8.3 keyword 篩を新言語で有効化＝偽陽性抑止）。B の perl/groovy 追加と同型・additive（既存キー不変）。

---

## 7. Phase A1: snippet（`snippet/_ts.py` 拡張）

§9 の二段選択（`node_at_line`→粒度ノードへ climb）を流用し、`_GRAN_JAVA`/`_GRAN_C` に倣う per-language 粒度集合と `_BLOCK` を追加。`build_snippet`（`snippet/__init__.py`）の **tree-sitter 分岐へ新4 language 値を追加**し、**direct（`pipeline.py`）と indirect（`fixedpoint/_finalize.py`）の両呼出点**で AST スパンが使われること（レビュー C2(b)・両経路で同一構文の snippet が一致）。
- 初期粒度集合（plan 時に代表例で最終検証）:
  - Python `_GRAN`: `if_statement`/`while_statement`/`for_statement`/`match_statement`/`return_statement`/`expression_statement`/`import_statement`/`import_from_statement`。`_BLOCK` に **`module`** と `block` を含める（climb 終端）。def/class/decorated ヘッダ行ヒットは束縛/粒度に当たらず 1 行フォールバック＝許容。
  - JS/TS `_GRAN`: `lexical_declaration`/`variable_declaration`/`if_statement`/`while_statement`/`for_statement`/`switch_statement`/`return_statement`/`expression_statement`/`field_definition`/`public_field_definition`/`method_definition`。`_BLOCK` に `program`/`statement_block`/`class_body`/`function_declaration`/`method_definition`/`arrow_function`。
- 既存の行・文字数セーフティ上限はそのまま適用。AST 言語は heuristic_span 分岐へ**入れない**（`_heuristic.stop()` の shell フォールスルー誤適用回避・B §6 の教訓）。

---

## 8. 既知限界（master §8.4 追加）
- Python: 宣言/代入 を構文上区別不可（`assignment`→一律 代入）。constant 判定は **ALL_CAPS 命名規約ヒューリスティック**（`typing.Final[]`・`enum.Enum` 継承は見ない）。`_X`/`__ALL__` は定数扱い、単一文字大文字は var。
- Python: 属性代入 `self.x =`／添字代入 `d[k] =`／walrus `n := …`（`named_expression`）は束縛として抽出しない。`@staticmethod`/`@cached_property` 等は getter/setter にしない。
- TS/JS: 型解決に依存する getter/setter 呼出側追跡は不可（構文的アクセサ**定義**のみ抽出）。computed member `obj[expr]`・`computed_property_name`・reflection・動的クラス名は追跡不可。
- import されたシンボルはファイルスコープのみ（モジュール解決なし）。
- TSX/JSX: コンポーネント属性等は category その他。
- 同一行に複数文がある場合、`node_at_line` 最小キーで決定的に1ノードを選ぶ（ヒット列に依存しない・master §9 既存方針）。
- 同一宣言の兄弟 declarator は全抽出（行ベースと同程度の過抽出）。

---

## 9. 不変条件 Inv-A
**Inv-A: トラックAは既存 golden を byte 不変に保つ（新言語 golden 追加を除く）。** B の Inv-B と同型の外形ゲートで担保する。

- **Phase A0**: ゲート G-A0（§4.3）＝既存 golden 全件 再生成 diff ゼロ ＋ 既存ユニット/結合 全緑 ＋ ノード型存在 smoke。
- **Phase A1**:
  - classify/dispatch/stoplist/snippet の追加は additive（既存分岐・キー・literal 不変）。
  - `found` タプル拡張は行言語で `chase_symbols=None`＝absorb 側で従来どおり `line` から計算＝既存経路 byte 不変。
  - **抽出/投入分離リファクタ（§6.1）は行言語の挙動を完全保存**: 行言語の `ChaseSymbols`／`kinds`／`symbol_kind`／`introducers`／edge／sort は同値。golden ゼロdiff＋既存 fixedpoint ユニットで実証（決定的コアに触れる唯一の変更）。
  - kind 伝播: AST 由来 `kinds` が `ingest_one`→`state.symbol_kind` に正しく載り、`_finalize._REF_KIND` が constant/var/getter/setter を正出力（C2(a)）。
  - snippet: `build_snippet` の AST 分岐は direct/indirect 両経路で適用（C2(b)）。

| リスク | 緩和 |
|---|---|
| R1: 0.23 で java/c ノード型 drift | G-A0 三点ゲート（golden ゼロdiff＋全緑＋ノード型存在 smoke）／差分はノード型集合で吸収 |
| R2: 抽出/投入分離が決定的コアの挙動変更 | 挙動保存リファクタ・行言語呼出経路 byte 同一・golden ゼロdiff＋既存ユニット |
| R3: AST chaser 非決定性 | `node_at_line` 最小キー＋field-directed のソース順 tuple（set dedup 禁止）。`chase_symbols` は `(relpath,lineno)` の純関数＝chunk 重複・sort 安定性に非依存。parse は (grammar版, bytes) の純関数で worker 間状態非共有（fork 継承の module 級 Language＋呼出毎 Parser・tree-sitter オブジェクト非越境＝spawn 安全） |
| R4: worker 内パースの perf | hop 毎の既読ファイルに parse 増分のみ（正しさ無関係）。`_ITEMS_PER_MB`/`compute_nchunks` は symbol 数基準で parse コストは file 単位＝不変 |
| R5: ABI/wheel | §2 G1 実証済・lock 再生成（hash付）・多アーキ wheelhouse |
| R6: getter/setter 非拡張（PRD レッドライン） | terminal・`scan_term`/`getter_setter_no_expand` 経路で非拡張 |

後続（本サブプロジェクト外・§12）: 既存 java/c の chaser を AST 化して2系統を統一（その際は java/c golden を意図的再生成＋レビュー）。

---

## 10. テスト
- **言語×ref_kind golden**（各言語 direct〔各 category〕＋ indirect **多ホップ**チェーン。direct/indirect 双方で snippet を確認）
  - Python: indirect:var（小文字）/constant（ALL_CAPS）/getter（@property）/setter（@x.setter）＋複数行宣言＋多ホップ連鎖
  - JS: const→constant / let→var / get・set→getter・setter / 分割代入（pair/default/rest）/ 複数行宣言 / field
  - TS: readonly→constant / enum members→constant / public field→var ／**generics の型識別子を誤抽出しないこと**／interface・type を chase しないこと
  - TSX: direct ＋ 1 チェーン
- **多ホップ回帰**（レビュー C1 直撃）: AST 言語で hop2 以降も連鎖が伸び、`ref_kind` が constant/getter/setter を正しく出すことを golden で固定。
- **G-A0 三点ゲート**（§4.3）。
- **単体**: dispatch（拡張子/シェバン）, stoplist（新キー）, classify（各言語 category・`import_from`/`augmented_assignment` 含む）, **AST chaser tree抽出（各束縛ノード・field-directed の型/RHS/キー非抽出を明示）**, snippet span（direct/indirect）, 抽出/投入分離後の fixedpoint。
- **テスト契約デルタ**（レビュー I5・B に倣い明示）: `found` タプル arity 変更と `ingest_one`/`kinds_of` シグネチャ変更を直接叩く既存 fixedpoint ユニットを改修。`_scan_file`/`scan_hop`/`ingest_one` を構築・呼出するテストの arity を更新（unpack arity の表明テストで silent break を検出）。
- **直交/決定性**: 文字コードは既存 pairwise 方針／2回実行 byte 一致（既存機構）／0.23 API smoke（Language/Parser ロード＋§4.1 のノード/ツリー API）。

---

## 11. 拡張点一覧（B の11項目テンプレートを track A へ写像・レビュー反映で補完）
| # | ファイル | 差分 |
|---|---|---|
| 1 | `pyproject.toml` / `requirements.lock` / `wheelhouse/` | tree-sitter 0.23.x 6点へ更新＋python/js/typescript grammar wheel 追加（aarch64+x86_64・hash付） |
| 2 | `classifiers/ts_classifier.py` | 0.23 API 適合（§4.1）＋ typescript/tsx/javascript/python の Language ロード・`_parser` マップ化・`_CATEGORY_BY_NODE`（§5.1） |
| 3 | `classify.py:classify_hit` | `language in (...)`→`classify_ts` 分岐へ4値追加（additive・signature 不変） |
| 4 | `dispatch.py` | 拡張子マップ（§3.4）＋シェバン `node`/`python`（§3.4） |
| 5 | `classifiers/base.py` | `ASTChaser` Protocol 定義（§6.6） |
| 6 | `classifiers/{python,javascript,typescript}_chaser.py`（新規） | `extract_tree(text, lineno)→ChaseSymbols` 実装（field-directed・§6.3/§6.5。tsx は typescript_chaser 共用）。**別レジストリ `_AST_CHASERS` に登録（行版 `_CHASERS` には登録しない）** |
| 7 | `chase.py` | `_AST_CHASERS` 参照の `extract_chase_symbols_tree(language, text, lineno)` 追加。`kinds_of` を **`(chase_symbols)→dict` へシグネチャ変更**（§6.1）。行言語は既存経路、`extract_var_symbols` は AST 非拡張 |
| 8 | `fixedpoint/_ingest.py` / `_seed.py` / `_scan.py` | 抽出/投入分離（§6.1）・新 `ingest_one` 契約・全3呼出点改修（§6.2）・方式A worker AST 抽出・`found` タプル拡張・absorb unpack arity |
| 9 | `snippet/_ts.py` / `snippet/__init__.py` | per-language 粒度/`_BLOCK` 集合追加＋`build_snippet` tree-sitter 分岐へ4値追加（§7・direct/indirect 両経路） |
| 10 | `stoplist.py:LANG_KEYWORDS` | typescript/tsx/javascript/python の予約語 frozenset 追加（§6.7） |
| 11 | `model.py` / `pipeline.py` | コード変更なし（言語非依存／`unsupported_shebang` は B で具体化済・python/node は解決言語に昇格）。ref_kind×言語は本書 §6.5 を正本 |

---

## 12. master への反映（実装後）
- §2.3 / §14 / §15: track A（TS/TSX/JS/Python）完了を記録。残り track C（JSP/Angular）。
- §4.2 / §15 フェーズ0: track A の G1 再ベースライン（0.23.x 採用）を記録（正本は本書 §2、`phase0-gate-result.md` に追補）。
- §8.4: 本書 §8 の既知限界を追加。
- §14: 「既存 java/c chaser の AST 化統一」を後続候補として明記。
