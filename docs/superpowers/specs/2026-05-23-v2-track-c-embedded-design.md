# v2 埋め込みトラック言語追加 設計書（サブプロジェクト C: JSP / Angular）

- 日付: 2026-05-23
- 区分: マスター設計書 `2026-05-16-grep-analyzer-design.md` への差分設計（master を正、本書が触れない事項は master に従う）
- 対象: master §386 が「後続」と記す **track C = 埋め込みトラック（JSP / Angular）**
- 前段: B（正規表現トラック・PL/SQL/Perl/Groovy）=`2026-05-22-v2-regex-languages-design.md`（完了）、A（tree-sitter トラック・TS/TSX/JS/Python）=`2026-05-23-v2-tree-sitter-languages-design.md`（完了）。順序 B → A → **C**（最後）。
- 由来注記: **PRD `docs/product-requirements.md` に JSP/Angular の明示記載は無い**。track C は master §386/§57 が後続トラックとして導入したもので、spec を正とする方針（メモリ: grep_analyzer spec is source of truth）に従いスコープ内とする。要件根拠＝**レガシー JSP 資産＋Angular フロントが混在する移行調査対象のシンボル使用箇所洗い出し**（master §57/§386 の「埋め込みトラック」想定）。
- 改訂: 2026-05-23 批判的AIレビュー（3観点・実コード照合＋tree-sitter 実証）反映。§5（parse_tree への host 写像集約）・§4.2（`*ngFor` 正規化を `of`→`=` へ修正）・§4.1（method 宣言の category）・§6（既知限界の補完）・§8（named regression 追加）を改稿。

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
          └ ゲート: Inv-C 二段（既存 golden ゼロdiff＋全緑）＋ angular golden 追加

各フェーズ末で Inv-C 二段ゲート（既存 golden 再生成 diff ゼロ＋全緑）を通す＝C1・C2 とも独立してマージ可能な単位（track A の A0→A1 と同型の「基盤先行・上に積む」構造）。
```

### 3.2 対象 language 値・拡張子・ホスト写像
| language 値（TSV） | 拡張子 | ホスト grammar | chaser 方式 | 抽出（逆マスク） | snippet |
|---|---|---|---|---|---|
| `jsp` | `.jsp` `.jspf` `.jspx` `.tag` `.tagx` | tree-sitter-**java** | **行ベース** java_chaser（`jsp` キーで新規登録＝`_CHASERS["jsp"]=java_chaser`） | scriptlet `<% %>`／式 `<%= %>`／宣言 `<%! %>` の Java＋EL `${}`/`#{}`（best-effort） | `jsp_region_span`（原ソース `<%…%>` 行スパン・多行可）→ 無ければ1行 |
| `angular` | `.html` `.htm`（Angular マーカ検出時） | tree-sitter-**typescript** | **AST** typescript_chaser（既存 `_AST_CHASERS`） | `{{ }}`／`[x]=`／`(ev)=`／`[(x)]=`／`*ng…` の TS 式 | ヒット1行（束縛は単行・多行は将来） |
| `html` | `.html` `.htm`（Angular マーカ無し） | なし（パススルー） | なし | 抽出なし | ヒット1行 |

- **language 値は proc に倣い独立**（`jsp`/`angular`/`html`）。内部ホスト写像（jsp→java・angular→typescript）は proc→c と同じく `host_grammar`/`host_source`（§5）で表現。**grammar 変種（ts/tsx/angular）は parse 時（`_parser`/`_LANGS`）に `host_grammar` で決まる**（chaser の `extract_tree(language,...)` 引数は束縛規則分岐用であって変種選択用ではない＝レビュー C-2 反映）。
- **jsp の snippet は1段**（`jsp_region_span`→無ければ1行）。proc の「`proc_exec_span`→無ければ `ts_span` の2段」とは**非対称**（jsp はバッファ上 `ts_span` を使わない・§5 #5）。
- 判定不能フォールバックは既存どおり C（master §5.1）。`.html`/`.htm` は拡張子既知だが最終言語は内容依存（`.c` が EXEC SQL で proc になるのと同型・§5 #1 で専用分岐）。

### 3.3 Pro\*C 逆マスク採用理由（パース方式）
- proc は「ホスト=C で全体パースし、埋め込み EXEC SQL を行数保存で空白化」（`proc_preprocess.mask_exec_sql`）。track C はこの**逆**＝「埋め込みコード**以外**を空白化し、残った埋め込みコードを host grammar に流す」。
- **新規 grammar wheel 不要**（§2）。track A の java/typescript classify・snippet・chaser 資産を全面再利用できる。
- 不採用 — **HTML grammar injection**: tree-sitter-html の aarch64/abi3 wheel 取得可否が未検証で新規 G1 ゲートを要し（§4.2 のブロッキング前提を再発生）、injection クエリ実装も追加。オフライン単一トラック前提（master §3/§4）に対し逆マスクが優位。
- 不採用 — **正規表現トラック（track B 型）**: AST chaser/classify の精度（high）と複数行スクリプトレット追跡を失う。

### 3.4 best-effort EL/ミニ式言語
ツールの目的（シンボル使用箇所の洗い出し）上、`${user.code}`・`[value]="user.code"` のような EL/バインディングこそ重要な参照箇所。一方これらは host grammar で綺麗にはパースできない。
- **各言語=単一ホスト grammar** に統一（実装単純化の要）: JSP の EL 内部式は **java** へ（`a.b.c` は java で式解釈可）、Angular の式は **typescript** へ流す。
- **軽正規化**（パース前の文字列前処理）:
  - EL の `prefix:func(` の接頭辞 `prefix:` 除去。
  - Angular パイプ `| name:args` 除去（左辺式のみ残す）。
  - **`*ngFor="let X of Y; …"` → `let X = Y`**（` of `→` = ` 置換・最初の `;` 以降を除去・長さ保存）。これにより ts は `lexical_declaration`（declarator name=`X`・value=`Y`）として ERROR 無しで parse し、field-directed 抽出が **`X`（ループ変数＝被追跡束縛）** を得る。**レビュー C-3 反映**: 旧案「`let X of Y` 断片をそのまま流す」は ts が `Y` を declarator・`X` を ERROR に落とし `item` を取りこぼすため誤り（実証済）。`*ngFor="let item of TRACKED"`→`item`（TRACKED から派生する束縛）が §8 期待値。
  - `*ngFor` の `as`/`index as i`/`trackBy:` 別名は **抽出しない**（§6 既知限界・二択確定）。
- host grammar の **ERROR 耐性**に依存（トップレベル式・宣言の混在は ERROR ノード化するが node_at_line でヒット行の category/識別子は取れる。EL/裸式は ERROR を貫通し classify は決定的に「その他」へ落ちる）。

---

## 4. Phase 詳細: 逆マスク（track C の中核）

**原則**: proc の `_blank_literals`（空白置換）と同型。各ファイルから host grammar が解釈できる埋め込みコード**だけ**を原位置に残し他を空白化したバッファを返す。**バッファは classify/AST chaser(angular) 専用**。
- **保証する不変量＝行数（改行位置）保存のみ**（lineno 写像に必須）。char 桁は概ね保存（空白置換）するが **`*ngFor` の `of`→`=` 正規化は行内 char 長を1縮める**（§4.2）。これは無害: (a) 行をまたがない、(b) snippet は原ソース行 index slice を使いバッファ桁に非依存、(c) classify/AST は `node_at_line`/`binding_at_line` の**行スパンが主キー**で byte/桁は同一バッファ内タイブレークのみ（行写像が厳密なら決定的・レビュー M-1/I-A 検証済）。
- **byte 長も非保存**（多バイト文字を1 byte 空白へ置換するため）＝同上理由で無害。
- snippet は原ソース行 index slice（byte 非依存）、chaser は行ベース（jsp）／AST バッファ（angular）が別途処理（§5）。

### 4.1 `extract_jsp_java(source) -> str`（長さ・行数保存）
残す区間（中身保持・`<%`等マーカは空白化）:
| 区間 | 構文 | java での扱い |
|---|---|---|
| スクリプトレット | `<% stmt %>` | 文（if/代入/宣言…）→ 既存 java category |
| 式 | `<%= expr %>` | 式 → その他 |
| 宣言 | `<%! field %>` | フィールド宣言 → 宣言。**メソッド宣言 `<%! T m(){} %>` は `method_declaration`＝`_CATEGORY_JAVAC` 表外→「その他」**（レビュー I-3 反映・category 表は不変＝Inv-C） |
| EL（best-effort） | `${ expr }` / `#{ expr }` | 式として java へ。`prefix:` 接頭辞は軽正規化で除去 |

空白化（捨てる）: ディレクティブ `<%@ … %>`、JSP コメント `<%-- … --%>`、**HTML コメント `<!-- … -->`**（コメント内の `<% %>`/`${}` を誤抽出しないため・レビュー C-imp-2 反映）、JSP 標準アクション `<jsp:useBean>`/`<jsp:setProperty>` 等（§6 既知限界＝非追跡）、HTML/テキスト。
- 実装: `re.sub` で保持区間を検出し、保持区間内は中身を残しマーカ部のみ等長空白へ、保持区間外は改行以外を空白へ（proc `_blank_literals` と同じ char長保存戦略）。

### 4.2 `extract_angular_ts(source) -> str`（長さ・行数保存）
残す区間（式テキストのみ・属性引用符/二重波括弧は空白化）:
| 区間 | 構文 | 正規化 |
|---|---|---|
| 補間 | `{{ expr }}` | パイプ `\| name:arg` 除去・左辺式のみ |
| プロパティ束縛 | `[prop]="expr"` `[attr.x]=` `[class.x]=` `[style.x]=` `[ngClass]=` `[ngStyle]=` | オブジェクトリテラル `{active: x}` のキー `active` は ts が抽出しうる（過抽出・§6 既知限界） |
| イベント束縛 | `(event)="stmt"` | 代入文 `x=1` は ts で 代入。`$event` は stoplist 収録で chase 除外（§5 #6） |
| 双方向 | `[(ngModel)]="expr"` | — |
| 構造ディレクティブ | `*ngIf="expr"` `*ngFor="let X of Y; …"` `*ngSwitch` | **`*ngFor` は `let X of Y` を `let X = Y` へ正規化**（` of `→` = `・`;` 以降除去）→ ts が `X` を束縛として抽出（§3.4・レビュー C-3 反映） |

空白化: 通常 HTML タグ・テキスト・**HTML コメント `<!-- … -->`**（コメント内 `{{}}` の誤抽出回避・レビュー C-imp-2）・`#ref`（テンプレ参照変数は v1 非追跡）。

### 4.3 `jsp_region_span(file_text, lineno)`（snippet 用・原ソース）
ヒット行を含む最寄りの `<% … %>`/`<%= … %>`/`<%! … %>` ブロックの原ソース行スパン `[s, e]`（0始まり）を返す。区間外は None（呼出側で1行フォールバック）。proc の `exec_spans`/`proc_exec_span` の**呼出構造**に倣う（区間 finditer→行番号換算）が、区間検出は §4.4 の非貪欲マッチ（proc のような完全なリテラル空白化前処理は行わない＝§4.4 既知限界）。`extract_jsp_java` の保持区間検出と**同一の正規表現を共有**し、classify バッファと snippet スパンの区間定義を一致させる。

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
- **置き場所**: 新 `embed_preprocess.py` に `host_grammar`/`host_source`/`extract_jsp_java`/`extract_angular_ts`/`jsp_region_span`/`_ANGULAR_RE` を集約（`mask_exec_sql` は `proc_preprocess` から import）。`ts_classifier`/`chase` が import（循環回避＝proc_preprocess に依存しないよう embed→proc の単方向）。
- **適用点は2か所に限定**（レビュー C-1・I-1・C-min-2 反映）:
  1. `classify_ts(language, source, lineno)`: 冒頭で `src = host_source(language, source)`、grammar は `_LANGS[host_grammar(language)]`。現 proc の `key="c"…`/`mask_exec_sql` インライン（`ts_classifier.py:78,129`）を本ヘルパへ一般化。
  2. **`parse_tree(language, source)` 自体を改修**: `_parser(host_grammar(language)).parse(host_source(language, source).encode())`。これで worker（`_scan.py`）・`chase.py`・`ts_span` が `parse_tree(language, raw_text)` を**生 text のまま**呼んでも内部で host 変換される（現状 `parse_tree` は素通しで `_parser("angular")`→KeyError＝C-1 の欠陥を解消）。`_LANGS`/`_parser` に angular キーは**足さない**（`host_grammar` が typescript へ畳む）。
  3. **二重マスク回避＋proc 呼出契約**: `ts_span`（`_ts.py:79-82`）の proc 用インライン `mask_exec_sql`/`lang="c"` 分岐は**除去**し、`ts_span("proc", file_text, …)` は **raw `file_text` を `parse_tree("proc", …)` へ渡す**（マスクは `parse_tree` 内 `host_source` の**1回のみ**＝二重マスク＝R1 を防ぐ）。粒度集合の選択は **java/c/proc 経路のみ** `host_grammar`（`_GRAN_JAVA`/`_GRAN_C`）へ統合し、**`_SETS_BY_LANG`（python/js/ts/tsx）の第2分岐（`_ts.py:84`）は track A のまま不変**（恒等写像のため挙動保存・Inv-C ゼロdiff の根拠・レビュー I-1 反映）。jsp/angular/html は `ts_span` を**通らない**（§5 #5）ため、この粒度改修の実効は proc 経路のみ。
- **行ベース経路（jsp の chaser・stoplist）には host_grammar を効かせない**（レビュー C-imp-1 反映）: `chase.py` の `extract_chase_symbols(language,…)` は `_CHASERS.get(language)` を**language 直引き**、`partition`→`admit` は `LANG_KEYWORDS.get(language)` を直引きするため、jsp は別キー登録（`_CHASERS["jsp"]`・`LANG_KEYWORDS["jsp"]`）が必須。host_grammar は classify/parse_tree(AST)/snippet 経路のみに作用。

| # | ファイル | 差分 |
|---|---|---|
| 1 | `dispatch.py` | `_EXT_MAP`: `.jsp/.jspf/.jspx/.tag/.tagx`→`jsp`。**`.html/.htm` は `_EXT_MAP` に入れない**（入れると `detect_language` line 92 `if lang is not None: return lang` で即 return し内容判定に到達しない＝レビュー I-3）。proc 分岐（line 88）と**同列の専用 if** を追加: `if ext in (".html",".htm"): return "angular" if _ANGULAR_RE.search(content_sample) else "html"`。`extension_resolves_language` に `.html/.htm` を**明示追加**（`_EXT_MAP` 非登録のため）。`_ANGULAR_RE` は **Angular 固有マーカ優先**（`*ng` `[(` `[x]=` `(ev)=` `routerLink` `formControl` `[ngClass]` 等）。`{{` 単独は Vue/Handlebars/Mustache と重複し過検出のため**単独トリガにしない**（レビュー C-min-3） |
| 2 | `classify.py` | routing に `jsp`/`angular`→`classify_ts`、`html`→定数 `("その他", "high")` を追加（additive・signature 不変） |
| 3 | `classifiers/ts_classifier.py` | `_CATEGORY_BY_LANG`: `jsp`→java マップ・`angular`→JS/TS マップ。`classify_ts` と **`parse_tree` 自体**が `host_grammar`/`host_source` 経由（§5 適用点1・2）。`_LANGS`/`_parser` に angular/jsp キーは足さない（host_grammar が java/typescript へ畳む） |
| 4 | `chase.py` / chasers | `jsp`→行ベース `_CHASERS["jsp"]=java_chaser`（**生行へ適用**＝行言語は `line` 直渡し・java_chaser の masking は JSP マーカを空白化しないが `<% T x=…%>` の代入抽出は成立。EL `${}` 内は `=` を伴わず line 経路では非抽出＝§6 既知限界・**plan で `JAVA_VAR_RE` の生 jsp 行 probe を必須**＝レビュー I-2）。`angular`→AST `_AST_CHASERS["angular"]=typescript_chaser`（**`classifiers/__init__.py` に1行**＝#9 と一体・worker は `parse_tree(angular,生text)` が §5 で host 変換）。`html` は登録せず（chase 非発火） |
| 5 | `snippet/__init__.py`,`snippet/_ts.py` | `build_snippet` に `elif language=="jsp": span = jsp_region_span(...)` を追加（None なら line 51 自然フォールバックで1行＝**1段・ts_span 段なし**）。`angular`/`html` は **build_snippet の tree-sitter/ts_span 分岐に足さず素通し1行**（バッファ空白域誤指し回避・レビュー M-1）。`ts_span` の proc インライン mask は §5 で `parse_tree` へ寄せる |
| 6 | `stoplist.py:LANG_KEYWORDS` | `jsp`→java 予約語∪{page,import,taglib,c,fn,empty,instanceof…}、`angular`→TS 予約語∪{ngIf,ngFor,let,of,trackBy,async,**$event**…}、`html`→空 frozenset（未登録でも `LANG_KEYWORDS.get(lang, frozenset())` で等価だが明示） |
| 7 | `classifiers/__init__.py` | **`_AST_CHASERS` に `"angular": typescript_chaser` を1行追加**。これで `_scan.py:45`/`_seed.py:51`/`chase.py:58` の `language in _AST_CHASERS` 判定に**自動波及**＝`_scan.py`/`_ingest.py`/`_seed.py` は**コード変更不要**（レビュー I-1）。`found` 4-tuple/`kinds_of(cs)`/`ingest_one(...)` 契約は track A のまま流用 |
| 8 | `embed_preprocess.py`（新規） | `host_grammar`/`host_source`/`extract_jsp_java`/`extract_angular_ts`/`jsp_region_span`/`_ANGULAR_RE` を集約（§5 置き場所）。`proc_preprocess` と同型の char長保存空白化 |
| 9 | `classifiers/base.py` | 変更なし（既存 `Chaser`/`ASTChaser` を流用） |
| 10 | `model.py`/`pipeline.py` | コード変更なし（言語非依存・新 language 値が透過）。proc の `host_source`/`host_grammar` 移行のみ golden 保護下 |
| 11 | `patterns/literal_masking.py` | 任意（jsp/angular は heuristic snippet 非経由のため必須でない。必要時 java/ts パターン流用） |

**chaser 方式の非対称（重要）**: jsp=行ベース java_chaser（生行直渡し・java の AST chaser は master §387 後続未着手のため）、angular=AST typescript_chaser（buffer parse・track A 既存）。両経路とも既存資産で、track A の抽出/投入分離契約（`found` 4-tuple・`kinds_of(cs)`・`ingest_one(state,parent,language,cs,kinds,hop,is_seed)`）にそのまま乗る。host_grammar は AST/classify/snippet 経路のみ・行経路は別キー（§5 適用点）。

### 5.1 classify category 写像
- `jsp` → `_CATEGORY_JAVAC`（java の node→category）。scriptlet の if→比較・宣言→宣言・代入→代入・return→return・`<%=`式→その他・EL→その他。
- `angular` → JS/TS マップ（track A）。`{{}}`/`[x]=`/`*ngIf`→その他・`(click)="x=1"`→代入。
- `html` → 定数 `("その他", "high")`（決定的・コード無し）。

---

## 6. 既知限界（master §8.4 追加）
- **Angular inline template**（`.component.ts` 内 `template:`）: 抽出しない。`.ts` は track A typescript 処理だがテンプレ文字列内は束縛解析せず（§9 後続候補）。
- **JSP 標準アクション** `<jsp:useBean id="x">`/`<jsp:setProperty>`/`<jsp:include>`: 逆マスクは `<% %>`系/EL のみ残すため**丸ごと空白化＝直接ヒットも消える**（html パススルーと違い jsp では非ヒット化）。束縛追跡せず（レビュー C-imp-2）。
- **JSTL カスタムタグ束縛** `<c:set var="x">`・カスタム EL 関数: 束縛 chase せず。属性引用符内の EL `${…}` は `extract_jsp_java` が残すため直接ヒットは捕捉。`fn:` 接頭辞は正規化のみ。
- **jsp 行ベース chaser の HTML/JSTL 属性偽抽出**: 生行へ java_chaser を当てるため `<c:set var="x" value="${T}"/>` 等で属性名（`var`/`value`）を変数として偽抽出しうる（best-effort・無害だが冗長・レビュー M-3）。
- **scriptlet 内 Java 文字列リテラル中の `%>`**: 非貪欲マッチが早期終端する稀ケース（§4.4・best-effort）。
- **多行 scriptlet の chaser**: java_chaser は単行（java 本体と同じ制約）。行跨ぎ束縛は非追跡。**複数行補間 `{{ a\n.b }}`** も angular は単行前提＝行跨ぎ式は部分抽出。
- **Angular `#ref`・パイプ名・`*ngFor` 別名**: テンプレ参照変数・パイプ右辺・`*ngFor` の `as`/`index as i`/`trackBy:` は**非追跡**（パイプは左辺式のみ・§3.4 二択確定）。
- **Angular オブジェクトリテラルのキー**: `[ngClass]="{active: x}"`/`[ngStyle]` のキー `active` を ts が識別子抽出しうる（過抽出・無害）。`$event` は stoplist で chase 除外。`async` パイプ右辺は除去。
- **HTML コメント `<!-- … -->`**: jsp/angular とも空白化（コメント内 `{{}}`/`<% %>` の誤抽出回避＝JSP コメント `<%-- --%>` と対称・§4.1/§4.2）。
- **`.html` ヒューリスティック誤判定（両方向）**: (a) Angular 固有マーカ無しのテンプレ→`html`扱い（式抽出ゼロ＝取りこぼし・PRD 的に痛い側）／(b) 静的 `.html` に Angular 固有マーカ混在→`angular`扱い（式抽出のみ・category その他・**直接ヒット取りこぼしは起きない**＝automaton は生行走査）。`{{` 単独は angular トリガにしない（§5 #1）。
- **html パススルー**: 全ヒット「その他」・chase なし・1行 snippet（設計どおり）。
- **JSP ディレクティブ** `<%@ taglib/page/include %>`: 空白化（非追跡）。
- import/コンポーネント↔テンプレ間のクロスファイル解決なし（既存 file-scope only 限界に同じ）。

---

## 7. 不変条件 Inv-C
**Inv-C: track C は既存 golden を byte 不変に保つ（新言語 jsp/angular/html golden 追加を除く）。** track A の Inv-A / B の Inv-B と同型の外形ゲートで担保。

- **決定的コアに触れる変更は2系統**（レビュー I-1/I-2 反映・「唯一」ではない）:
  1. **proc 3 callsite の一般化**（`ts_classifier._parser`:78・`ts_classifier.classify_ts`:129・`snippet/_ts.ts_span`:79-82）を `host_grammar`/`host_source` へ集約する**挙動保存リファクタ**。ts_span のインライン `mask_exec_sql` は `parse_tree` へ寄せ二重マスクを除去。
  2. **`parse_tree`/`_parser` への host 写像追加**（angular→typescript・host_source 適用）。既存6 AST 言語は `host_grammar`=恒等・`host_source`=恒等で **1 byte も変わらない**ことを smoke で表明。
- 他は全 additive（dispatch 専用分岐・classify 分岐・stoplist キー・新モジュール・`_AST_CHASERS` への angular 1行・`_CHASERS["jsp"]`）。
- **二段ゲート**: ①既存 golden 全件（java/c/proc/sql/shell/perl/groovy/ts/tsx/js/python）再生成 diff ゼロ ②既存 unit/integration 全緑 ＋ `host_grammar`/`host_source` 写像 smoke（proc/既存言語が恒等であること）。新規 grammar 無しのためノード型 smoke は不要。

| リスク | 緩和 |
|---|---|
| R1: proc 一般化リファクタが proc 挙動変更（特に ts_span 二重マスク） | 挙動保存・ts_span のインライン mask を `parse_tree` へ一本化（二重適用回避）・proc golden ゼロdiff＋proc unit（`test_proc_preprocess`/`proc_exec_snippet`/`proc_direct`）named assert |
| R2: 逆マスクの行数/長さ不保存→lineno 写像破綻 | 長さ保存空白化（proc `_blank_literals` 同型）・抽出 unit で行数/長さ/位置を表明 |
| R3: best-effort パースの非決定性 | 抽出は復号後テキストの純関数（正規表現・char 単位）。angular AST は track A の `node_at_line` 最小キー＋field-directed（set dedup 禁止）。jsp 行ベースは既存 java_chaser の決定性 |
| R4: `.html` 内容ヒューリスティック誤判定 | §6 既知限界として明記・html パススルーは無害（その他/1行）・golden で境界固定 |
| R5: レガシー JSP 文字コード（SJIS/EUC-JP） | 抽出は復号後 char 単位＝encoding 非依存。snippet は region span（byte オフセット非依存）＝SJIS サロゲート経路を踏まない。文字コード pairwise golden で固定 |

---

## 8. テスト
- **dispatch（単体・両方向を golden 固定）**: `.jsp/.jspf/.jspx/.tag/.tagx`→jsp、`.html`(Angular 固有マーカ)→angular、`.html`(マーカ無 or `{{` 単独のみ)→html、`.htm` 同様、`extension_resolves_language` の `.html/.htm` True。**`.html` 誤判定の両方向**（マーカ無 Angular→html／`{{` 単独→html・過検出しないこと）を明示（レビュー C-imp-3）。**補間のみテンプレ（`<p>{{user.code}}</p>`）→html だが automaton 生行走査で `user`/`code` の直接ヒットは生存**（取りこぼすのは indirect chase と category 精度のみ）を1ケース固定。
- **抽出（単体）**: `extract_jsp_java`/`extract_angular_ts` の行数・char長保存、マーカ/ディレクティブ/JSPコメント/**HTMLコメント**/`<jsp:useBean>` 空白化、EL接頭辞/パイプ/**`*ngFor` の `of`→`=` 正規化**を**位置含めて**表明。`jsp_region_span` の多行ブロック・区間外 None。
- **classify（単体）**: JSP（if→比較・**フィールド宣言→宣言・メソッド宣言→その他**・代入→代入・return→return・`<%=`→その他・EL→その他）、Angular（`{{}}`/`[x]=`→その他・`(click)="x=1"`→代入）、html→その他。
- **chaser（単体）**: jsp `<% int x = TRACKED; %>`→x（行ベース java・**生 jsp 行の `JAVA_VAR_RE` probe を含む**＝レビュー I-2）、angular `*ngFor="let item of TRACKED"`→**item**（AST ts・`of`→`=` 正規化後・実 AST で確認）、EL `${TRACKED.code}`→束縛なし（正）、**html→chase 非発火**（`extract_chase_symbols("html",…)`/`…_from_root("html",…)` が空 `ChaseSymbols`）。
- **snippet（単体）**: jsp 多行 scriptlet→region span（1段）、angular→1行、html→1行。direct/indirect 双方で確認。
- **言語×ref_kind golden**:
  - jsp: direct（各 category）＋ indirect 多ホップ（scriptlet `x = TRACKED` → `y = x`）。
  - angular: direct（`{{TRACKED}}`/`[v]="TRACKED"`）＋ テンプレ内多ホップ（`*ngFor="let x of TRACKED"`→`{{x.code}}`）。
  - html: direct ヒット→その他・chase なし。
- **Inv-C 二段ゲート**（§7）: **既存 golden 全件ゼロdiff を named assert**（特に proc golden ＋ proc unit）＋全緑＋`host_grammar`/`host_source` 恒等 smoke。**G1 no-new-wheel 表明**（`requirements.lock` 不変）。
- **直交/決定性**: 2回実行 byte 一致（既存機構）／文字コード pairwise（**レガシー JSP の SJIS/EUC-JP ケースを必須**＝抽出は復号後 char 単位で encoding 非依存・snippet は行 index slice で byte 非依存を表明）。
- **テスト契約デルタ**: `host_grammar`/`host_source` の新規表明テストで proc/既存言語の写像同値（リファクタ前後一致＝恒等）を固定。`parse_tree` が angular で host 変換後 typescript parse することを smoke。`found` タプル arity・`ingest_one` シグネチャは track A のまま（変更なし）。

---

## 9. master への反映（実装後）
- §2.3 / §14 / §15: track C（JSP/Angular）完了を記録＝**v2 ロードマップ（B→A→C）完遂**。
- §4.2 / §15 フェーズ0: track C は新規 wheel 不要・G1 自動充足を記録（`phase0-gate-result.md` に1行追補）。
- §5.1: `.jsp` 系拡張子＋`.html/.htm` 内容ヒューリスティック（angular/html）を追記。
- §8.4: 本書 §6 の既知限界を追加。
- §14 後続候補: **Angular inline template の式抽出**、既存 java/c chaser の AST 化統一（jsp の行ベース chaser も同時に AST 化可能）を明記。
