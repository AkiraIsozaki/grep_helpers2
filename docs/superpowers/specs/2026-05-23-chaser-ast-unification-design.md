# 差分設計書: java/c/jsp/proc chaser の AST 統一（master §390）

- 日付: 2026-05-23
- 位置づけ: master spec `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md` §390 の後続候補を確定設計化。本書は master に従属する差分設計書。
- 前提: track A（TS/TSX/JS/Python AST chaser・`binding_at_line`）と track C（JSP/Angular/HTML 逆マスク・`host_grammar`/`host_source`）が完了済み。
- ユーザー決定（2026-05-23）:
  - 対象範囲＝**java/c/jsp/proc すべて**（c と proc は AST chaser を共有）。
  - Inv 方針＝**改善差異は再生成を許容**（AST がより正確になる箇所は golden を意図的再生成＋レビュー。退行は不可）。

## 1. 目的と背景

現状は **AST classify（high）を使いながら chaser は行ベース正規表現**というハイブリッド。java/c chaser（jsp は java_chaser 流用・proc は c_chaser 流用）を track A の field-directed AST 抽出方式へ統一し、classify と chase の解析基盤を一本化する。

AST 化の本質的利得:
- 文字列・コメント内の代入様字句の偽抽出を排除（regex の literal マスクに依存しない）。
- 多行宣言（行跨ぎ `String alias =\n  TRACKED;` 等）を追跡可能（行ベース単行制約の解消・master §208 jsp 既知限界(6)の一部緩和）。
- 修飾子・宣言子の構文的判定（`static final` 検出、`char *p` のポインタ宣言子、複数宣言子）を AST フィールドで厳密化。

## 2. 既存アーキテクチャ（確認）

chase には2経路ある（`classifiers/__init__.py` の登録で分岐）:

- **行ベース chaser** `_CHASERS`（java/c/proc/shell/sql/perl/groovy/jsp）: マスク後の1行に regex を適用。`chase.extract_chase_symbols(language, dialect, line)` 経由。`_scan.py` worker は `cs=None` を返し、`_ingest.absorb_results` が `extract_chase_symbols` で行から再抽出する。`_seed.py` は seed 行1行を `extract_chase_symbols` で抽出。
- **AST chaser** `_AST_CHASERS`（python/javascript/typescript/tsx/angular/angular_inline）: ファイルを1度 `parse_tree(language, text)` し、対象行を含む最小スパン束縛ノードを `binding_at_line` で取り、name:/left: フィールドのみ抽出。`_scan.py` worker が hit 行ごとに `extract_chase_symbols_from_root` で `cs` を事前計算し `found` に載せる。`_seed.py` は `extract_chase_symbols_tree`。

`parse_tree` / `classify_ts` は `host_grammar`（proc→c, jsp→java, angular(_inline)→typescript）と `host_source`（proc→`mask_exec_sql`, jsp→`extract_jsp_java`, angular→`extract_angular_ts`, angular_inline→`extract_inline_angular`）を適用済。`host_source` は**行数・桁を保存**するため lineno 写像は逆マスク後も一致する（track C 不変量）。

## 3. 変更方針

### 3.1 レジストリ移動

`java/c/proc/jsp` を `_CHASERS` から除去し `_AST_CHASERS` に登録する:

```python
_CHASERS = {  # 行ベース（残存）
    "shell": shell_chaser, "sql": sql_chaser, "perl": perl_chaser, "groovy": groovy_chaser,
}
_AST_CHASERS = {
    "python": python_chaser, "javascript": javascript_chaser,
    "typescript": typescript_chaser, "tsx": typescript_chaser,
    "angular": typescript_chaser, "angular_inline": typescript_chaser,
    "java": java_chaser, "c": c_chaser, "proc": c_chaser, "jsp": java_chaser,
}
```

`java_chaser.py` / `c_chaser.py` は**ファイル名を踏襲のまま中身を AST 実装に置換**（python_chaser.py 等と同じ無印 AST 命名規約）。`Chaser` プロトコル（`extract`/`mask`）から `ASTChaser` プロトコル（`extract_tree`）へ切替。

これにより:
- `_scan.py` の汎用 AST 分岐（`if language in _AST_CHASERS: parse_tree(language, text)`）が java/c/jsp/proc を自動的に拾う。typescript 専用の inline-template 2-root 特別処理（`language == "typescript"` ガード）は ts 限定のまま不変。
- `_seed.py` の `if lang in _AST_CHASERS:` 分岐が `extract_chase_symbols_tree` 経路へ振る。
- `chase.extract_chase_symbols("java"/"c"/"proc"/"jsp", …)`（行ベース）は対象外言語となり空 `ChaseSymbols()` を返す。この経路は parse 失敗時の `absorb` フォールバックでのみ到達しうるが、その場合は空＝chase なし（track A と同じ挙動）。

### 3.2 multi-node コレクタ（核心）

`ts_classifier.py` に `binding_at_line` と並べて新設:

```python
def bindings_at_line(root, lineno, binding_types):
    """対象行に交差し binding_types に属する全ノードを決定的順で返す（list）。

    binding_at_line（最小スパン単一ノード）と異なり、行内に複数の束縛・
    呼出が同居する場合（例 `int count = svc.getName(); obj.setValue(count);`）
    を regex の「行内全マッチ」と等価に拾うため複数件を返す。
    順序は (start_byte, end_byte, type) 昇順で安定（出力 tuple の決定性）。
    """
    target = lineno - 1
    out = []
    cursor = [root]
    while cursor:
        node = cursor.pop()
        if node.start_point[0] <= target <= node.end_point[0]:
            if node.type in binding_types:
                out.append(node)
            cursor.extend(node.children)
    out.sort(key=lambda n: (n.start_byte, n.end_byte, n.type))
    return out
```

入れ子ノード（`field_declaration ⊃ method_invocation`）は両方収集される。各ハンドラはそのノード型に応じたフィールドのみ読むため二重抽出は起きない（外側＝宣言名、内側＝getter 名）。

### 3.3 Java 抽出規則（`java_chaser.py`）

binding 型:

```python
_BINDING = {"local_variable_declaration", "field_declaration",
            "assignment_expression", "method_invocation", "method_declaration"}
_GETSET_RE = re.compile(r"^(get|set)[A-Z]\w*$")
```

`bindings_at_line(root, lineno, _BINDING)` の各ノードを順に処理:

- `local_variable_declaration` / `field_declaration`:
  - `modifiers` 子の**名前なしトークン集合**に `static` と `final` の両方を含めば **const**、それ以外は **var**（部分文字列ではなくトークン一致＝アノテーション等の誤検出回避）。
  - 名前は子の `variable_declarator` の `name` フィールド（`identifier`）から（複数宣言子は全件・出現順）。
- `assignment_expression`: `left` フィールドが `identifier` のときのみ **var**（`field_access` `this.y` 等は非抽出＝AST 改善）。
- `method_invocation` / `method_declaration`: `name` フィールド（`identifier`）が `_GETSET_RE` に一致するとき、先頭が `g`→**getter**、`s`→**setter**。`method_invocation`（呼出側）も対象＝既存 regex セマンティクス保持。

const と判定した名前は var に重複させない（既存 `const_set` 除外と等価）。

### 3.4 C / Pro*C 抽出規則（`c_chaser.py`）

binding 型:

```python
_BINDING = {"declaration", "preproc_def", "assignment_expression"}
```

- `preproc_def`: `name` フィールド → **const**。
- `declaration`:
  - 直下に `type_qualifier` で `const` を含めば **const**、無ければ **var**。
  - 名前は declarator から抽出。`init_declarator`（その `declarator` フィールド）／裸 `identifier`／`pointer_declarator`／`array_declarator` を再帰的に剥がして末尾 `identifier` を採る。複数 declarator（`int a=1, b=2;`）は全件・出現順。`function_declarator`（関数宣言名）は **非抽出**。
- `assignment_expression`: `left` が `identifier` のときのみ **var**。
- getter/setter は無し（空タプル）。

const と判定した名前は var に重複させない。

### 3.5 proc / jsp の再利用

- `_AST_CHASERS["proc"] = c_chaser`、`_AST_CHASERS["jsp"] = java_chaser`。
- `parse_tree("proc", text)` は `mask_exec_sql` 後を c grammar で解析＝EXEC SQL 区間は空白化され、その中の host 変数 `:x` は非投入（master §8.1 手順1 と整合・現行の「c literal マスクのみ」より厳密）。
- `parse_tree("jsp", text)` は `extract_jsp_java` 後を java grammar で解析。scriptlet の top-level java 文（クラス/メソッド外）は tree-sitter-java が **ERROR なしで** `local_variable_declaration` 等として解析する（実証済）。EL `${…}` は逆マスクで式断片が残るが束縛にならない（var/const とも空）。
- `extract_tree(language, root, lineno)` の `language` 引数は jsp/proc でも渡るが、java/c の抽出規則は `language` 非依存（規則は固定）。

## 4. 不変量（Inv）と golden 方針

### 4.1 既存 golden の予測（multi-node でセマンティクス保存）

| golden | seed/chase | 予測 |
|---|---|---|
| `java_direct` | `static final … STATUS_OK`(const)＋`if(...STATUS_OK)`(比較) | 不変 |
| `c_direct` | `#define CODE`(const) | 不変 |
| `proc_direct` | `char *p = "X"`→p(var)、EXEC SQL 区間外 | 不変 |
| `indirect_constant` | `static final STATUS_OK`→U.java `x=STATUS_OK` | 不変 |
| `getter_no_expand` | `int vv = a.getName()`→vv(var)＋getName(getter terminal)→T.java×2 | 不変（**multi-node 必須**） |
| `jsp_chain` | TRACKED→alias 多ホップ（scriptlet 多行 java） | 不変 |
| `parsefail_fallback` | `@@@@@`（ERROR tree・束縛なし） | 不変 |

分類（category）は AST classify が既に担っており本変更は **classify を一切触らない**ため category 列は不変。

### 4.2 差異が出た場合の扱い

実装中に既存 golden の byte 差異が出たら、その差異が「**改善**（文字列内偽抽出排除・フィールドアクセス左辺の非抽出・多行束縛の捕捉等）」か「**退行**（取りこぼし・誤分類）」かを判定する:
- 改善 → golden を再生成し、差分を spec reviewer / code-quality reviewer のレビューで承認。
- 退行 → chaser を修正（再生成しない）。

### 4.3 新規 golden（AST 能力の固定）

AST 化で新たに正しくなる挙動を回帰固定する新規ケースを追加。**真に行ベースと差が出る**もの＝「束縛名と `=` が別行にあり、ヒットが `=` を含まない継続行に落ちる」ケースを選ぶ（行ベースは hit 行単独に regex を当てるため `=` 行以外で取りこぼす。文字列内偽抽出の排除は行ベースも literal マスクするため差にならない＝不採用）:

- `java_multiline_chase`: 多行宣言
  ```java
  String alias =
      TRACKED;
  ```
  で `TRACKED`（const、別ファイル定義）を追跡 → 継続行 `TRACKED;`（2行目・`=` 無し）でヒットした際、AST は外側 `local_variable_declaration`（1–2行）へ climb して `alias`(var) を捕捉し多ホップ継続。行ベースでは2行目に `=` が無く `alias` を取りこぼす。
- C 同型の多行ケースを任意で追加可（plan で要否判断）。

（最終的なケース名・件数は plan で確定。`{SOURCE_ROOT}` 正規化・utf-8-sig BOM の既存 golden 規約に従う。）

## 5. テスト移行と dead code 除去

### 5.1 unit テスト移行（`test_chase.py` → `test_ast_chaser.py`）

`test_chase.py` の以下を AST 版へ移設（`extract_chase_symbols_tree` / `parse_tree`+`extract_tree` 経由）。java/c/jsp/proc が `_CHASERS` を抜けるため行ベース API では空になる:

- `test_文字列内の代入様字句は追跡シンボルにしない`（java）→ AST
- `test_Java定数はstaticかつfinalのみ…` → AST
- `test_Javaのgetterとsetterとvarを…`（multi-node 必須ケース）→ AST
- `test_C定義とconst定数を抽出しProCホスト変数…` → AST
- `test_ref_kind言語表の禁止セルは空を返す` の **proc 部分** → AST（sql/shell 部分は行ベースのまま残す）
- `test_jsp_行ベースchaserが代入左辺を抽出` → AST（テスト名も改称）
- `test_jsp_ELは束縛なし` → AST

`test_chase.py` に残すもの: sql/shell/perl/groovy の行ベース規則、`extract_var_symbols`（sql/shell）一式、末尾の既存 AST tree テスト、`test_html_はchase非発火`。

`test_文字列とコメントをマスクし行長を保つ`（`mask_literals("java"/"c")`）は java/c が mask_literals を使わなくなるため **java/c 断を削除**（perl の同種テストは残る）。

### 5.2 dead code 除去

- `patterns/literal_masking.py` の `MASK_SPECS` から `java`/`c`/`proc` 断を除去（mask_literals 利用は sql/shell/perl/groovy のみ＝`snippet/_heuristic.py` 経由）。
- `patterns/symbol_extraction.py` の `JAVA_CONST_RE`/`JAVA_VAR_RE`/`JAVA_GETSET_RE`/`C_DEFINE_RE`/`C_CONST_RE`/`C_VAR_RE` を除去（他に参照なしを確認のうえ）。
- `base.py` の `Chaser`/`ASTChaser` プロトコルは双方残す（shell/sql/perl/groovy が `Chaser`、それ以外が `ASTChaser`）。

## 6. 既知限界（本変更後）

- **getter/setter は命名規約ベース**（`(get\|set)[A-Z]\w*`）。`isXxx`・流暢 setter（`builder.name(x)`）・非規約アクセサは非検出（既存と同等・意図的）。
- **method_invocation を binding 型に含める**ため、行内の全呼出ノードが `bindings_at_line` に集まる（規約非一致は破棄）。性能は file 単位1パース＋線形走査で track A と同等。
- **C の関数ポインタ・複雑な declarator**（`int (*fp)(void)`）は末尾 identifier 抽出が best-effort。
- **proc の EXEC SQL 内 host 変数**は非追跡（仕様・§8.1 整合）。
- **多行 Angular 補間・jsp `%>` 文字列内**等、track C 由来の逆マスク既知限界は不変（本変更の範囲外）。
- **parse 失敗時**（極稀・tree-sitter は基本 error-tolerant）は当該ファイルの chase が空（track A と同じ）。

## 7. 完了基準

1. java/c/jsp/proc が `_AST_CHASERS` 経由で AST chase される（`_CHASERS` から除去）。
2. 既存 golden は §4.1 の予測どおり byte 不変、ないし §4.2 で改善と判定し再生成＋レビュー承認済（退行ゼロ）。
3. 新規 golden（多行 java 追跡・C 文字列ノイズ排除）追加。
4. unit テストを §5.1 のとおり移行、§5.2 の dead code 除去。
5. 全テスト green（件数は実装後に master のテストベースライン §96 を更新）。
6. requirements.lock / pyproject 変更なし（新規 grammar wheel ゼロ＝既存 java/c grammar を流用）。

## 8. 非対象（YAGNI）

- shell/sql/perl/groovy の AST 化（tree-sitter grammar 採用は master §14 の別候補・前提条件付き）。
- getter/setter 検出の意味論拡張（`is`/fluent 等）。
- classify ロジックの変更（本変更は chase のみ）。
