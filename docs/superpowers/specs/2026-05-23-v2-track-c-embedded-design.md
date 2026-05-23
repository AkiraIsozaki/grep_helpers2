# v2 埋め込みトラック言語追加 設計書（サブプロジェクト C: JSP / Angular）

- 日付: 2026-05-23
- 区分: マスター設計書 `2026-05-16-grep-analyzer-design.md` への差分設計（master を正、本書が触れない事項は master に従う）
- 対象: master §386 が「後続」と記す **track C = 埋め込みトラック（JSP / Angular）**
- 前段: B（正規表現トラック・PL/SQL/Perl/Groovy）=`2026-05-22-v2-regex-languages-design.md`（完了）、A（tree-sitter トラック・TS/TSX/JS/Python）=`2026-05-23-v2-tree-sitter-languages-design.md`（完了）。順序 B → A → **C**（最後）。
- 由来注記: **PRD `docs/product-requirements.md` に JSP/Angular の明示記載は無い**。track C は master §386/§57 が後続トラックとして導入したもので、spec を正とする方針（メモリ: grep_analyzer spec is source of truth）に従いスコープ内とする。

---

## 1. 目的とスコープ

### 1.1 本書が対象とすること
1. **埋め込み言語 2 種を追加**: `jsp`（HTML 内 Java）/ `angular`（HTML テンプレート内 TypeScript 式）。あわせて非 Angular の `.html` を受ける `html` パススルー語彙を導入。
2. **Pro\*C 逆マスク方式**でパース（§3）: 埋め込みコード区間**以外**を行数・長さ保存で空白化し、残った埋め込みコードを既存 tree-sitter host grammar（jsp→java / angular→typescript）へ流す。**新規 grammar wheel 不要**。
3. dispatch（拡張子＋`.html` 内容ヒューリスティック）・classify・chaser・snippet・stoplist・fixedpoint の追加（§5、track A/B の11拡張点テンプレートを写像）。

### 1.2 本書が対象としないこと（master / 後続）
- **Angular inline template**（`.component.ts` 内 `template:` テンプレートリテラル）の式抽出（§8 既知限界・§9 後続候補）。`.ts` 本体は track A で typescript 処理済。
- 既存 java/c chaser の AST 化統一（master §14・§387 の後続候補。本トラックでも jsp は行ベース java_chaser を流用＝据え置き）。
- HTML grammar（tree-sitter-html）採用・injection 方式（§3.3 で不採用理由）。
- JSTL カスタムタグ／カスタム EL 関数の束縛追跡（§8 既知限界）。
- テンプレ参照変数 `#ref`・Angular パイプ名・コンポーネント↔テンプレ間のクロスファイルシンボル解決（§8）。
- 正規表現トラック（PL/SQL/Perl/Groovy）・track A 言語の挙動変更。

### 1.3 確定スコープ判断（ブレインストーミング結果）
- **スコープ分割**: 単一サブプロジェクト C。内部を **Phase C1（jsp ＋ 共通抽出基盤 ＋ html パススルー）→ Phase C2（angular）** の2フェーズに分け、逆マスク基盤を C1 で確立し C2 で再利用する。JSP/Angular を**同一 spec** で扱う（埋め込み抽出の共通基盤が大きいため）。
- **パース方式**: Pro\*C 逆マスク（§3.3 理由）。
- **EL/ミニ式言語**: best-effort 抽出（§3.4）。
- **Angular ディスパッチ**: 外部テンプレートのみ＋`.html` 内容ヒューリスティック。inline template は既知限界（§1.2）。

---

## 2. §4.2 G1 ゲート（track C・自動充足）

- **新規 grammar wheel ゼロ**。jsp は tree-sitter-java、angular は tree-sitter-typescript を host grammar とし、いずれも track A で wheelhouse へ同梱済（`tree-sitter-java==0.23.5`・`tree-sitter-typescript==0.23.2`・aarch64+x86_64）。
- **依存追加なし**＝`requirements.lock` 不変（テスト件数ベースラインのみ track C 完了時点で更新）。pyproject も不変。
- よって master §4.2 G1（オフライン単一トラック・aarch64 wheel 完備）のブロッキング前提は track C では**自動充足**。これは本書のパース方式（§3.3）採用の最大の利点であり、`phase0-gate-result.md` への追補は「track C は新規 wheel 不要・G1 不要」の1行記録で足りる。

---

## 3. アーキテクチャ

### 3.1 フェーズ構成
```
Phase C1  共通抽出基盤 ＋ jsp ＋ html パススルー
          ├ embed_preprocess.py（逆マスク・行数/長さ保存）: extract_jsp_java / jsp_region_span
          ├ host_grammar()/host_source() ヘルパ導入（proc を golden 保護下で移行）
          ├ dispatch（.jsp 系拡張子 ＋ .html 内容ヒューリスティック→html）
          ├ classify/chaser(行ベース java)/snippet(region span)/stoplist(jsp,html)
          └ ゲート: Inv-C 二段（既存 golden ゼロdiff＋全緑）＋ jsp/html golden 追加
Phase C2  angular（C1 の逆マスク基盤上に積む）
          ├ extract_angular_ts（{{}}/[ ]/( )/* の TS 式・正規化）
          ├ dispatch（.html ＋ng マーカ→angular）
          ├ classify/chaser(AST typescript)/snippet/stoplist(angular)
          └ ゲート: Inv-C 維持 ＋ angular golden 追加
```

### 3.2 対象 language 値・拡張子・ホスト写像
| language 値（TSV） | 拡張子 | ホスト grammar | chaser 方式 | 抽出（逆マスク） | snippet |
|---|---|---|---|---|---|
| `jsp` | `.jsp` `.jspf` `.jspx` `.tag` `.tagx` | tree-sitter-**java** | **行ベース** java_chaser（既存 `_CHASERS`） | scriptlet `<% %>`／式 `<%= %>`／宣言 `<%! %>` の Java＋EL `${}`/`#{}`（best-effort） | `jsp_region_span`（原ソース `<%…%>` 行スパン・多行可）→ 無ければ1行 |
| `angular` | `.html` `.htm`（Angular マーカ検出時） | tree-sitter-**typescript** | **AST** typescript_chaser（既存 `_AST_CHASERS`） | `{{ }}`／`[x]=`／`(ev)=`／`[(x)]=`／`*ng…` の TS 式 | ヒット1行（束縛は単行・多行は将来） |
| `html` | `.html` `.htm`（Angular マーカ無し） | なし（パススルー） | なし | 抽出なし | ヒット1行 |

- **language 値は proc に倣い独立**（`jsp`/`angular`/`html`）。内部ホスト写像（jsp→java・angular→typescript）は proc→c と同じく dispatch 辞書群＋`host_grammar`/`host_source` で表現。
- 判定不能フォールバックは既存どおり C（master §5.1）。`.html`/`.htm` は拡張子既知だが最終言語は内容依存（`.c` が EXEC SQL で proc になるのと同型）。

### 3.3 Pro\*C 逆マスク採用理由（パース方式）
- proc は「ホスト=C で全体パースし、埋め込み EXEC SQL を行数保存で空白化」（`proc_preprocess.mask_exec_sql`）。track C はこの**逆**＝「埋め込みコード**以外**を空白化し、残った埋め込みコードを host grammar に流す」。
- **新規 grammar wheel 不要**（§2）。track A の java/typescript classify・snippet・chaser 資産を全面再利用できる。
- 不採用 — **HTML grammar injection**: tree-sitter-html の aarch64/abi3 wheel 取得可否が未検証で新規 G1 ゲートを要し（§4.2 のブロッキング前提を再発生）、injection クエリ実装も追加。オフライン単一トラック前提（master §3/§4）に対し逆マスクが優位。
- 不採用 — **正規表現トラック（track B 型）**: AST chaser/classify の精度（high）と複数行スクリプトレット追跡を失う。

### 3.4 best-effort EL/ミニ式言語
ツールの目的（シンボル使用箇所の洗い出し）上、`${user.code}`・`[value]="user.code"` のような EL/バインディングこそ重要な参照箇所。一方これらは host grammar で綺麗にはパースできない。
- **各言語=単一ホスト grammar** に統一（実装単純化の要）: JSP の EL 内部式は **java** へ（`a.b.c` は java で式解釈可）、Angular の式は **typescript** へ流す。
- **軽正規化**（パース前の文字列前処理）: EL の `prefix:func(` の接頭辞 `prefix:` 除去、Angular パイプ `| name:args` 除去（左辺式のみ残す）、`*ngFor="let X of Y; …"` を `X`(var 束縛)＋`Y`(被参照) へ。
- host grammar の **ERROR 耐性**に依存（トップレベル式・宣言の混在は ERROR ノード化するが node_at_line でヒット行の category/識別子は取れる）。

---

## 4. Phase 詳細: 逆マスク（track C の中核）

**原則**: proc の `_blank_literals`（長さ保存・空白置換・改行保存）と同型。各ファイルから host grammar が解釈できる埋め込みコード**だけ**を原位置に残し他を空白化したバッファを返す。**バッファは classify 専用**（lineno 写像のため行数・桁を保存）。snippet は原ソース、chaser は行ベース（jsp）／AST バッファ（angular）が別途処理（§5）。

### 4.1 `extract_jsp_java(source) -> str`（長さ・行数保存）
残す区間（中身保持・`<%`等マーカは空白化）:
| 区間 | 構文 | java での扱い |
|---|---|---|
| スクリプトレット | `<% stmt %>` | 文（if/代入/宣言…）→ 既存 java category |
| 式 | `<%= expr %>` | 式 → その他 |
| 宣言 | `<%! field/method %>` | フィールド/メソッド宣言 → 宣言 |
| EL（best-effort） | `${ expr }` / `#{ expr }` | 式として java へ。`prefix:` 接頭辞は軽正規化で除去 |

空白化（捨てる）: ディレクティブ `<%@ … %>`、JSP コメント `<%-- … --%>`、HTML/テキスト。
- 実装: `re.sub` で保持区間を検出し、保持区間内は中身を残しマーカ部のみ等長空白へ、保持区間外は改行以外を空白へ（proc `_blank_literals` と同じ長さ保存戦略）。

### 4.2 `extract_angular_ts(source) -> str`（長さ・行数保存）
残す区間（式テキストのみ・属性引用符/二重波括弧は空白化）:
| 区間 | 構文 | 正規化 |
|---|---|---|
| 補間 | `{{ expr }}` | パイプ `\| name:arg` 除去・左辺式のみ |
| プロパティ束縛 | `[prop]="expr"` `[attr.x]=` `[class.x]=` `[style.x]=` | — |
| イベント束縛 | `(event)="stmt"` | 代入文 `x=1` は ts で 代入 |
| 双方向 | `[(ngModel)]="expr"` | — |
| 構造ディレクティブ | `*ngIf="expr"` `*ngFor="let X of Y; …"` `*ngSwitch` | `*ngFor` は `let X of Y` を `X`(var 束縛)＋`Y`(被参照) へ軽正規化 |

空白化: 通常 HTML タグ・テキスト・`#ref`（テンプレ参照変数は v1 非追跡）。

### 4.3 `jsp_region_span(file_text, lineno)`（snippet 用・原ソース）
ヒット行を含む最寄りの `<% … %>`/`<%= … %>`/`<%! … %>` ブロックの原ソース行スパン `[s, e]`（0始まり）を返す。区間外は None（呼出側で1行フォールバック）。proc の `exec_spans`/`proc_exec_span` と同型（リテラル空白化コピー上で区間検出しマーカ衝突を抑止）。

### 4.4 マーカ衝突の既知限界
proc の literal 空白化と同様の理想は「区間判定を文字列リテラル空白化コピー上で行う」だが、JSP は保持区間の**内側**に文字列があるため完全な相互排除は複雑。**v1 は非貪欲マッチ**（`<%.*?%>` 等）とし、Java 文字列内に `%>` が出る稀ケースは §8 既知限界とする（best-effort スコープ）。

---

## 5. パイプライン接続（11拡張点・track A/B テンプレート写像）

**統一ヘルパ導入**（proc のインライン分岐を一般化・proc は golden 保護下で移行）:
```
host_grammar(language)  : jsp→"java", angular→"typescript", proc→"c", 他→language
host_source(language,s) : jsp→extract_jsp_java(s), angular→extract_angular_ts(s),
                          proc→mask_exec_sql(s), 他→s
```
`classify_ts` / `parse_tree` / `snippet` がこれを共用（埋め込み写像を1か所へ集約）。

| # | ファイル | 差分 |
|---|---|---|
| 1 | `dispatch.py` | `_EXT_MAP`: `.jsp/.jspf/.jspx/.tag/.tagx`→`jsp`。`.html/.htm` は内容ヒューリスティック `_ANGULAR_RE`（`{{` `*ng` `[(` `[x]=` `(ev)=` `routerLink` 等）一致→`angular`／非一致→`html`（proc の EXEC SQL ヒューリスティックと同型）。`extension_resolves_language` は `.html/.htm` も True（拡張子既知・最終言語は内容依存） |
| 2 | `classify.py` | routing に `jsp`/`angular`→`classify_ts`、`html`→定数 `("その他", "high")` を追加（additive・signature 不変） |
| 3 | `classifiers/ts_classifier.py` | `_CATEGORY_BY_LANG`: `jsp`→java マップ・`angular`→JS/TS マップ。`host_grammar`/`host_source` で grammar 選択＋逆マスク適用（proc の `key="c"…`/`mask_exec_sql` 分岐を本ヘルパへ一般化） |
| 4 | `chase.py` / chasers | `jsp`→行ベース `_CHASERS["jsp"]=java_chaser`（生行へ適用・マーカはノイズ・best-effort）。`angular`→AST `_AST_CHASERS["angular"]=typescript_chaser`（worker は `parse_tree("angular",text)`＝`host_source` で ts バッファ化後パース・typescript 変種を選択）。`html` は登録せず（chase 入力なし） |
| 5 | `snippet/__init__.py`,`snippet/_ts.py` | `jsp`→`jsp_region_span`（原ソース `<%…%>` 行スパン）→無ければ1行。`angular`→ヒット1行。`html`→1行。**いずれもバッファ上 `ts_span` は使わない**（空白域を指すため） |
| 6 | `stoplist.py:LANG_KEYWORDS` | `jsp`→java 予約語∪{page,import,taglib,c,fn,empty,instanceof…}、`angular`→TS 予約語∪{ngIf,ngFor,let,of,trackBy,async…}、`html`→空 frozenset |
| 7 | `fixedpoint/_scan.py`,`_ingest.py`,`_seed.py` | AST 言語集合へ `angular` を追加（worker パース＋from_root 抽出）。`jsp` は行パス（既存 line 抽出経路）。`found` タプル/`kinds_of`/`ingest_one` 契約は track A のまま流用 |
| 8 | `embed_preprocess.py`（新規） | `extract_jsp_java`/`extract_angular_ts`（逆マスク・長さ/行保存）、`jsp_region_span`、`_ANGULAR_RE`。`proc_preprocess` と同型の長さ保存空白化 |
| 9 | `classifiers/base.py` | 変更なし（既存 `Chaser`/`ASTChaser` を流用） |
| 10 | `model.py`/`pipeline.py` | コード変更なし（言語非依存・新 language 値が透過）。proc の `host_source`/`host_grammar` 移行のみ golden 保護下 |
| 11 | `patterns/literal_masking.py` | 任意（jsp/angular は heuristic snippet 非経由のため必須でない。必要時 java/ts パターン流用） |

**chaser 方式の非対称（重要）**: jsp=行ベース java_chaser（java の AST chaser は master §387 後続未着手のため）、angular=AST typescript_chaser（track A 既存）。両経路とも既存資産で、track A の抽出/投入分離契約（`found` 4-tuple・`kinds_of(cs)`・`ingest_one(state,parent,language,cs,kinds,hop,is_seed)`）にそのまま乗る。

### 5.1 classify category 写像
- `jsp` → `_CATEGORY_JAVAC`（java の node→category）。scriptlet の if→比較・宣言→宣言・代入→代入・return→return・`<%=`式→その他・EL→その他。
- `angular` → JS/TS マップ（track A）。`{{}}`/`[x]=`/`*ngIf`→その他・`(click)="x=1"`→代入。
- `html` → 定数 `("その他", "high")`（決定的・コード無し）。

---

## 6. 既知限界（master §8.4 追加）
- **Angular inline template**（`.component.ts` 内 `template:`）: 抽出しない。`.ts` は track A typescript 処理だがテンプレ文字列内は束縛解析せず。
- **JSTL カスタムタグ束縛** `<c:set var="x">`・カスタム EL 関数: 束縛 chase せず（直接ヒットは捕捉）。`fn:` 接頭辞は正規化のみ。
- **scriptlet 内 Java 文字列リテラル中の `%>`**: 非貪欲マッチが早期終端する稀ケース（§4.4・best-effort）。
- **多行 scriptlet の chaser**: java_chaser は単行（java 本体と同じ制約）。行跨ぎ束縛は非追跡。
- **Angular `#ref`・パイプ名**: テンプレ参照変数・パイプ右辺は非追跡（パイプは左辺式のみ）。`*ngFor` の `as`/`index as i` は部分対応。
- **`.html` ヒューリスティック誤判定**: マーカ無し Angular テンプレ→`html`扱い（抽出なし）／静的 `.html` に `{{` 混在→`angular`扱い（無害・式抽出のみ）。
- **html パススルー**: 全ヒット「その他」・chase なし・1行 snippet（設計どおり）。
- **JSP ディレクティブ** `<%@ taglib/page/include %>`: 空白化（非追跡）。
- import/コンポーネント↔テンプレ間のクロスファイル解決なし（既存 file-scope only 限界に同じ）。

---

## 7. 不変条件 Inv-C
**Inv-C: track C は既存 golden を byte 不変に保つ（新言語 jsp/angular/html golden 追加を除く）。** track A の Inv-A / B の Inv-B と同型の外形ゲートで担保。

- **決定的コアに触れる唯一の変更**: proc のインライン `mask_exec_sql`/grammar-key を `host_source`/`host_grammar` へ一般化する**挙動保存リファクタ**。proc golden ゼロdiff＋既存 unit で実証。
- 他は全 additive（dispatch 辞書キー・classify 分岐・stoplist キー・新モジュール・AST 言語集合への angular 追加）。
- **二段ゲート**: ①既存 golden 全件（java/c/proc/sql/shell/perl/groovy/ts/tsx/js/python）再生成 diff ゼロ ②既存 unit/integration 全緑 ＋ `host_grammar`/`host_source` 写像 smoke。新規 grammar 無しのためノード型 smoke は不要。

| リスク | 緩和 |
|---|---|
| R1: proc 一般化リファクタが proc 挙動変更 | 挙動保存・proc golden ゼロdiff＋既存 unit |
| R2: 逆マスクの行数/長さ不保存→lineno 写像破綻 | 長さ保存空白化（proc `_blank_literals` 同型）・抽出 unit で行数/長さ/位置を表明 |
| R3: best-effort パースの非決定性 | 抽出は復号後テキストの純関数（正規表現・char 単位）。angular AST は track A の `node_at_line` 最小キー＋field-directed（set dedup 禁止）。jsp 行ベースは既存 java_chaser の決定性 |
| R4: `.html` 内容ヒューリスティック誤判定 | §6 既知限界として明記・html パススルーは無害（その他/1行）・golden で境界固定 |
| R5: レガシー JSP 文字コード（SJIS/EUC-JP） | 抽出は復号後 char 単位＝encoding 非依存。snippet は region span（byte オフセット非依存）＝SJIS サロゲート経路を踏まない。文字コード pairwise golden で固定 |

---

## 8. テスト
- **dispatch（単体）**: `.jsp/.jspf/.jspx/.tag/.tagx`→jsp、`.html`(+ng マーカ)→angular、`.html`(マーカ無)→html、`.htm` 同様、`extension_resolves_language` の True。
- **抽出（単体）**: `extract_jsp_java`/`extract_angular_ts` の行数・長さ保存、マーカ/ディレクティブ/コメント空白化、EL接頭辞/パイプ/ngFor 正規化を**位置含めて**表明。`jsp_region_span` の多行ブロック・区間外 None。
- **classify（単体）**: JSP（if→比較・宣言→宣言・代入→代入・return→return・`<%=`→その他・EL→その他）、Angular（`{{}}`/`[x]=`→その他・`(click)="x=1"`→代入）、html→その他。
- **chaser（単体）**: jsp `<% int x = TRACKED; %>`→x（行ベース java）、angular `*ngFor="let item of TRACKED"`→item（AST ts・バッファ経由）、EL `${TRACKED.code}`→束縛なし（正）。
- **snippet（単体）**: jsp 多行 scriptlet→region span、angular→1行、html→1行。direct/indirect 双方で確認。
- **言語×ref_kind golden**:
  - jsp: direct（各 category）＋ indirect 多ホップ（scriptlet `x = TRACKED` → `y = x`）。
  - angular: direct（`{{TRACKED}}`/`[v]="TRACKED"`）＋ テンプレ内多ホップ（`*ngFor="let x of TRACKED"`→`{{x.code}}`）。
  - html: direct ヒット→その他・chase なし。
- **Inv-C 二段ゲート**（§7）＋ **G1 no-new-wheel 表明**（`requirements.lock` 不変）。
- **直交/決定性**: 2回実行 byte 一致（既存機構）／文字コード pairwise（**レガシー JSP の SJIS/EUC-JP ケースを必須**＝抽出は復号後 char 単位で encoding 非依存を表明）。
- **テスト契約デルタ**: `host_grammar`/`host_source` の新規表明テストで proc の写像同値（リファクタ前後一致）を固定。`found` タプル arity・`ingest_one` シグネチャは track A のまま（変更なし）。

---

## 9. master への反映（実装後）
- §2.3 / §14 / §15: track C（JSP/Angular）完了を記録＝**v2 ロードマップ（B→A→C）完遂**。
- §4.2 / §15 フェーズ0: track C は新規 wheel 不要・G1 自動充足を記録（`phase0-gate-result.md` に1行追補）。
- §5.1: `.jsp` 系拡張子＋`.html/.htm` 内容ヒューリスティック（angular/html）を追記。
- §8.4: 本書 §6 の既知限界を追加。
- §14 後続候補: **Angular inline template の式抽出**、既存 java/c chaser の AST 化統一（jsp の行ベース chaser も同時に AST 化可能）を明記。
