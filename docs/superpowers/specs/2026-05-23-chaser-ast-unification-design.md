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

`parse_tree` / `classify_ts` は `host_grammar`（proc→c, jsp→java, angular(_inline)→typescript）と `host_source`（proc→`mask_exec_sql`, jsp→`extract_jsp_java`, angular→`extract_angular_ts`, angular_inline→`extract_inline_angular`）を適用済。`host_source` は **行数（改行位置）を保存**するため lineno 写像は逆マスク後も一致する（track C 不変量・lineno 写像に必要十分なのは行数保存）。jsp/angular の `extract_*` は桁（列位置）も保存するが、**proc の `mask_exec_sql` は EXEC SQL 区間を改行のみ残して各物理行を空文字列に潰す＝桁は非保存**（chase は行単位 lineno のみ依存するため正しさに影響しない）。

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
- `chase.extract_chase_symbols("java"/"c"/"proc"/"jsp", …)`（行ベース）は対象外言語となり空 `ChaseSymbols()` を返す。

**parse 失敗の機序（訂正・レビュー I-2/M-2 反映）**: tree-sitter は不正入力（`@@@@@`・null byte・深いネスト等）でも**例外を投げず**、`ERROR` ノードを含む有効な root を返す（`has_error=True` でも root は有効）。よって `_scan.py` worker の `except Exception: ts_root=None` 経路と、それに連なる `absorb` の行ベースフォールバック（`extract_chase_symbols`）は java/c/jsp/proc では**実質到達不能**。不正入力のファイルは「ERROR tree から binding 型ノードが取れず chase 空」という機序で空になる（行ベースフォールバックが効くからではない）。なお `_seed.py` の `extract_chase_symbols_tree` は `parse_tree` を素で呼ぶ（worker と異なり try ガード無し）が、tree-sitter が raise しないため無害。

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

**name 行ゲート（核心・レビュー C-1 反映）**: `bindings_at_line` は「行に**交差**する」全ノードを返すため、多行 getter/setter の本体行にヒットすると外側 `method_declaration` も交差して**メソッド名を漏らす**（旧 regex は本体行に `getX(` が無く非抽出＝退行）。これを防ぐため:
- **宣言・代入ノード**（`*_declaration` / `assignment_expression` / `resource`）は**ゲートしない**＝交差する全行で束縛名を採る（多行宣言の継続行ヒットで外側束縛を捕捉する §4.3 の目的に必須）。
- **`method_invocation` / `method_declaration`（getter/setter）は name フィールドの行＝ヒット行のときのみ採用**（`name.start_point[0] == lineno-1`）。これにより本体行・多行呼出の深い行での過抽出を排し、旧 regex の「その行に `getX(`/`setX(` がある」セマンティクスと整合する。

この非対称は意図的: 宣言/代入は「束縛の捕捉」（RHS 含め束縛全体のどこでヒットしても束縛名を採るのが多行追跡の狙い）／getter/setter は「命名規約による参照・定義検出」（意味あるヒットは name トークン行）という性質差に基づく。

### 3.3 Java 抽出規則（`java_chaser.py`）

binding 型:

```python
_BINDING = {"local_variable_declaration", "field_declaration", "resource",
            "assignment_expression", "method_invocation", "method_declaration"}
_GETSET_RE = re.compile(r"^(get|set)[A-Z]\w*$")
```

`bindings_at_line(root, lineno, _BINDING)` の各ノードを順に処理:

- `local_variable_declaration` / `field_declaration` / `resource`（try-with-resources のリソース宣言・レビュー I-3 反映で追加・旧 regex は `r` を拾うため非追加は退行）:
  - `modifiers` 子の**名前なしトークン集合**に `static` と `final` の両方を含めば **const**、それ以外は **var**（部分文字列ではなくトークン一致＝アノテーション等の誤検出回避）。`resource` は `modifiers` を持たない＝常に var。
  - 名前は子の `variable_declarator` の `name` フィールド（`identifier`）から（複数宣言子は全件・出現順）。`resource` は **`name` フィールド経由で**取る（実証: 新規宣言 `Reader r = open()` は name=`r`／既存変数参照 `try (existing)` は **name フィールドが None ＝非抽出**。素朴な「直下 identifier 走査」は `existing` を誤抽出するため不可・name フィールド必須）。`resource` に `modifiers` は無く常に var。
- `assignment_expression`: `left` フィールドが `identifier` のときのみ **var**（`field_access` `this.y`・`array_access` 等は非抽出＝AST 改善）。**複合代入** `total += x`（java grammar 上も `assignment_expression`・演算子が子）は left が identifier なら **var として捕捉**する（旧 regex は lookbehind で `+=` を除外・捨てていた＝AST は逆方向に拾う。track A の JS chaser が augmented を捕捉するのと整合・改善方向として固定）。
- `method_invocation` / `method_declaration`: **name 行ゲート（§3.2）下で**、`name` フィールド（`identifier`）が `_GETSET_RE` に一致するとき、先頭が `g`→**getter**、`s`→**setter**。`method_invocation`（呼出側）も対象＝既存 regex セマンティクス保持。

const と判定した名前は var に重複させない（既存 `const_set` 除外と等価）。

### 3.4 C / Pro*C 抽出規則（`c_chaser.py`）

binding 型:

```python
_BINDING = {"declaration", "field_declaration", "preproc_def",
            "preproc_function_def", "assignment_expression"}
```

- `preproc_def`: `name` フィールド → **const**。
- `preproc_function_def`（関数様マクロ `#define MAX(a,b) …`・レビュー I-1 反映で追加・旧 regex `C_DEFINE_RE` は `MAX` を拾うため非追加は退行）: `name` フィールド → **const**。
- `declaration` / `field_declaration`（struct/union メンバ宣言・レビュー I-2 反映で追加・旧 regex `C_CONST_RE` が struct メンバ const を拾うため非追加は退行。C の `field_declaration` は java と異なり `declarator` フィールド構造＝declaration と同じ剥がし規則を適用）:
  - 直下に `type_qualifier` で `const` を含めば **const**、無ければ **var**。
  - 名前は declarator から抽出。`init_declarator`（その `declarator` フィールド）／`pointer_declarator`／`array_declarator` を再帰的に剥がして末尾識別子を採る。末尾識別子は **`identifier`（トップレベル `declaration`）または `field_identifier`（`field_declaration` の struct/union メンバ）の両方を受理**する（実証: トップレベル `const int K;`→`declaration` 直下 `identifier`／struct メンバ `const int K;`→`field_declaration` 直下 `field_identifier`／struct `int *p;`→`pointer_declarator`→`field_identifier`）。**declarator ラッパ（init/pointer/array）が無く `identifier`/`field_identifier` が直接子のケース**（no-init `int x;`・bitfield `int x:3;`・ネスト struct メンバ）も子の全件走査で拾う（`declarator` フィールドのみを必須経路にすると取りこぼす）。複数 declarator（`int a=1, b=2;` / struct の `int a, b;`）は子を走査し全件・出現順。**init 無し宣言**（`int x;`）も declarator から名を採る（var・旧 regex は `=` 必須で空＝改善方向。const 型修飾子付き `const int K;` は const）。`function_declarator`（関数宣言名・関数ポインタ `int (*fp)(void)`）は **非抽出**（旧 regex も非抽出＝退行なし。§6 に明記）。
- `assignment_expression`: `left` が `identifier` のときのみ **var**（複合代入 `+=` 等も java と同様に捕捉）。
- getter/setter は無し（空タプル）。

const と判定した名前は var に重複させない。

### 3.5 proc / jsp の再利用

- `_AST_CHASERS["proc"] = c_chaser`、`_AST_CHASERS["jsp"] = java_chaser`。
- `parse_tree("proc", text)` は `mask_exec_sql` 後を c grammar で解析＝EXEC SQL 区間は空白化され、その中の host 変数 `:x` は非投入（master §8.1 手順1 と整合・現行の「c literal マスクのみ」より厳密）。
- `parse_tree("jsp", text)` は `extract_jsp_java` 後を java grammar で解析。scriptlet の top-level java 文（クラス/メソッド外）は tree-sitter-java が `local_variable_declaration` 等として正しく解析する（実証済）。root は `has_error=True` になりうる（`<%= alias %>` 由来の bare identifier 等）が、**ERROR ノードが混在しても各束縛ノードは正しく構築され抽出に影響しない**（レビュー M-2 反映で文言訂正）。EL `${…}` の式断片（`user.name` 等）は逆マスクで残るが、通常は束縛にならない（var/const とも空）。
- **既知の例外（レビュー I-5）**: EL 行の直下に `<%= 識別子 %>` のような式が隣接すると、error recovery が両断片を1つの `local_variable_declaration`（型＝EL 式 `user.name`／変数＝隣接識別子）として併合し、EL 行に隣接識別子の var が漏れることがある（contrived・`jsp_chain` golden は非該当）。宣言ノードを name 行ゲートしない方針（多行追跡優先）の副作用として許容し §6 に既知限界として明記する。stoplist/min_specificity が汎用名の横展開を抑止する二次防御となる。
- `extract_tree(language, root, lineno)` の `language` 引数は jsp/proc でも渡るが、java/c の抽出規則は `language` 非依存（規則は固定）。

## 4. 不変量（Inv）と golden 方針

### 4.1 既存 golden の予測（multi-node でセマンティクス保存）

| golden | seed/chase | 予測 |
|---|---|---|
| `java_direct` | `static final … STATUS_OK`(const)＋`if(...STATUS_OK)`(比較) | 出力 byte 不変 |
| `c_direct` | `#define CODE`(const) | 出力 byte 不変 |
| `proc_direct` | `char *p = "X"`→p(var)、EXEC SQL 区間外 | **出力 byte 不変**だが**抽出は改善**（旧 regex `C_VAR_RE` は lookbehind で `*p` の `p` を取りこぼし＝旧は p 非抽出、AST は p 捕捉。p は下流非参照のため TSV 出力は不変。レビュー I-4 反映） |
| `indirect_constant` | `static final STATUS_OK`→U.java `x=STATUS_OK` | 出力 byte 不変 |
| `getter_no_expand` | `int vv = a.getName()`→vv(var)＋getName(getter terminal)→T.java×2 | 出力 byte 不変（**multi-node ＋ name 行ゲート必須**。single-node 流用や本体過抽出だと退行） |
| `jsp_chain` | TRACKED→alias 多ホップ（scriptlet 多行 java） | 出力 byte 不変 |
| `parsefail_fallback` | `@@@@@`（ERROR tree・束縛なし） | 出力 byte 不変 |

分類（category）は AST classify が既に担っており本変更は **classify を一切触らない**ため category 列は不変。**confidence 列**は chaser kind 依存（`_finalize.py` で getter/setter→low）だが、getName が getter kind として正しく分類される限り不変。

なお上表は **multi-node `bindings_at_line` ＋ §3.2 name 行ゲートが正しく実装される限り**全ヒット行で抽出 symbol・順序とも byte 不変であることを実証済（レビュー2）。**実コーパス**には §4.2/§4.3 の改善差（proc EXEC SQL 排除・複合代入・ポインタ var・多行束縛・フィールドアクセス左辺非抽出）が出るが、これらは golden では §4.3 で固定する。

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
- `proc_exec_sql_chase`（レビュー2 C-1 反映・必須）: EXEC SQL 内に代入様字句を含む proc
  ```c
  EXEC SQL UPDATE t
    SET col = somevar
    WHERE id = :hostid;
  ```
  で `col`/`id` が **抽出されない**こと（旧 regex は EXEC SQL 非認識で `col`/`id` を偽 var 抽出。AST は `mask_exec_sql` で区間空白化＝改善）を固定する。区間外の C 代入が拾われることも併せて確認。
- 複合代入 `total += x;` で `total` を var 捕捉する java/c ケース（レビュー I-3 反映・改善方向の固定。plan で `java_multiline_chase` 等への相乗りか独立 golden かを判断）。
- C 同型の多行ケースは任意（plan で要否判断）。

（最終的なケース名・件数は plan で確定。`{SOURCE_ROOT}` 正規化・utf-8-sig BOM の既存 golden 規約に従う。）

### 4.4 再生成の運用ガード（レビュー2 提言）

「退行を改善と誤判定して再生成する」事故を防ぐため、golden 再生成は次の手順に紐づける:
1. 実装前に**現行（行ベース）実装での全 golden ＋ 代表実コーパスの TSV をスナップショット**。
2. AST 化後の差分を1行ずつ「改善／退行」分類した**差分票**を作り、spec/code-quality reviewer のレビュー必須項目とする。
3. 差分票のチェックリスト固定項目: `this.y`/`obj.field` 左辺非抽出・EXEC SQL 内代入排除・複合代入捕捉・ポインタ var 捕捉・no-init 宣言 var 捕捉・多行束縛捕捉。各差分がこのいずれかに該当する改善であることを確認し、該当しない差分は退行として chaser を修正。

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
- `test_extract_chase_symbols_tree_非AST言語は空`（レビュー I-1 反映・移行漏れ）: 現状 `extract_chase_symbols_tree("java", "int x = 1;\n", 1)` が空であることを表明するが、java が `_AST_CHASERS` に入ると `x` を var 抽出して **fail する**。負契約の言語を非 AST 言語（例 `groovy`/`sql`）へ差し替える（行ベース言語は依然 tree 抽出が空）。

`test_chase.py` に残すもの: sql/shell/perl/groovy の行ベース規則、`extract_var_symbols`（sql/shell）一式、末尾の既存 AST tree テスト、`test_html_はchase非発火`。

`test_文字列とコメントをマスクし行長を保つ`（`mask_literals("java"/"c")`）の **java 断（内容一致 assert）は削除**（java が `_CHASERS` を抜け `mask_literals("java")` が原行を返すため fail）。c 断は `mask_literals("c")` が原行をそのまま返すため長さ assert は通ってしまうが、マスクされない＝テストの趣旨が無意味化するため**併せて削除**（perl の同種テストは残る）。

### 5.2 dead code 除去

- `patterns/literal_masking.py` の `MASK_SPECS` から **`java`/`c` 断のみ除去**。**`proc` 断は残置**（レビュー C-1: `proc_preprocess.py:30` が `MASK_PATTERNS["proc"]` を**添字アクセス**しており、除去すると import 時 KeyError で全壊。proc 前処理は chase だけでなく classify/snippet 経路でも生存）。`MASK_PATTERNS["java"]`/`["c"]` は `java_chaser.py`/`c_chaser.py` の `mask` のみが参照し AST 置換で消えるため除去安全。`regex_classifier.py` は `MASK_PATTERNS.get(...)` で `.get` アクセスのため java/c 除去後も安全。
- `patterns/symbol_extraction.py` の `JAVA_CONST_RE`/`JAVA_VAR_RE`/`JAVA_GETSET_RE`/`C_DEFINE_RE`/`C_CONST_RE`/`C_VAR_RE` を除去（参照は `java_chaser.py`/`c_chaser.py` のみ＝AST 置換で同時に消える。他参照ゼロをレビューで確認済）。
- `base.py` の `Chaser`/`ASTChaser` プロトコルは双方残す（shell/sql/perl/groovy が `Chaser`、それ以外が `ASTChaser`）。`__init__.py` の型注釈 `_CHASERS: dict[str, Chaser]` / `_AST_CHASERS: dict[str, ASTChaser]` は据え置き（java/c を後者へ移し中身を `extract_tree` 実装にすれば整合）。

## 6. 既知限界（本変更後）

- **getter/setter は命名規約ベース**（`(get\|set)[A-Z]\w*`）。`isXxx`・流暢 setter（`builder.name(x)`）・非規約アクセサは非検出（既存と同等・意図的）。getter/setter は **name 行ゲート**（§3.2）下でのみ採用＝多行呼出の name トークン以外の行では非検出。
- **method_invocation を binding 型に含める**ため、行内の全呼出ノードが `bindings_at_line` に集まる（規約非一致・name 行非一致は破棄）。性能は file 単位1パース＋線形走査で track A と同等。
- **C の関数ポインタ／関数宣言名**（`int (*fp)(void)` の `fp`・`function_declarator`）は **非抽出**（旧 regex も非抽出＝退行なし。"best-effort" ではなく確定的に非抽出）。
- **proc の EXEC SQL 内 host 変数・列名等**は非追跡（`mask_exec_sql` で区間空白化・§8.1 整合）。
- **no-init 宣言**（`int x;`）の var 捕捉・**複合代入**（`total += x`）の var 捕捉は AST で新規に拾う（改善方向・§3.3/§3.4・§4.3 で固定）。
- **JSP の EL 行と隣接式の error recovery 由来漏れ**（§3.5 既知の例外）: EL 行直下に `<%= 識別子 %>` が隣接すると宣言併合で var が漏れうる（contrived・stoplist が二次防御）。
- **多行 Angular 補間・jsp `%>` 文字列内**等、track C 由来の逆マスク既知限界は不変（本変更の範囲外）。
- **不正入力ファイル**（tree-sitter は raise せず ERROR tree を返す）は binding が取れず chase 空（§3.1）。

## 7. 完了基準

1. java/c/jsp/proc が `_AST_CHASERS` 経由で AST chase される（`_CHASERS` から除去）。`bindings_at_line`（multi-node）＋ name 行ゲート（§3.2）を実装。
2. 既存 golden は §4.1 の予測どおり出力 byte 不変、ないし §4.2/§4.4 で改善と判定し再生成＋レビュー承認済（退行ゼロ）。
3. 新規 golden 追加: `java_multiline_chase`（多行追跡）・`proc_exec_sql_chase`（EXEC SQL 内偽抽出排除）・複合代入捕捉（相乗り可）。
4. unit テストを §5.1 のとおり移行（`test_extract_chase_symbols_tree_非AST言語は空` の言語差し替え含む）、§5.2 の dead code 除去（**`MASK_SPECS["proc"]` は残置**）。
5. 全テスト green。master spec **§96 テストベースラインを 381 passed, 5 skipped 起点で再カウント更新**（test_chase.py→test_ast_chaser.py の移設＋新規 golden の純増減を反映）。
6. requirements.lock / pyproject 変更なし（新規 grammar wheel ゼロ＝既存 java/c grammar を流用）。
7. master spec の文言更新（master が source of truth・MEMORY 方針）:
   - **§390 本文を「完了」へ更新し対象に proc を明記**、§14 の後続候補リストから本項を完了側へ移す。
   - **§389 末尾「残る後続候補は §390（chaser AST 化統一）のみ」を更新**（§390 完了により後続候補なしへ）。
   - **§208 track C 既知限界(6)「多行 scriptlet（java_chaser 単行制約・行跨ぎ束縛非追跡）」を更新**（jsp の AST 化＝java grammar で多行 scriptlet の行跨ぎ束縛を追跡可能になり制約解消。`java_multiline_chase` 相当が jsp でも成立）。

## 8. 非対象（YAGNI）

- shell/sql/perl/groovy の AST 化（tree-sitter grammar 採用は master §14 の別候補・前提条件付き）。
- getter/setter 検出の意味論拡張（`is`/fluent 等）。
- classify ロジックの変更（本変更は chase のみ）。
