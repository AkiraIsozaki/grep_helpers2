# grep_analyzer 設計書 (Design Spec)

- 作成日: 2026-05-16
- 改訂:
  - v1: ブレインストーミング初版
  - v2: AIレビュー反映（Solaris前提）
  - v3: 稼働先をモダンLinux・オフラインへ転換。tree-sitter主軸
  - v4: 2回目AIレビュー反映。Python3.12はターゲット既存（wheelhouseのみ）
  - v5: 3回目AIレビュー反映。停止性論証の修正／ストップリスト循環の解消（v1は静的のみ）／chain正規形／Pro\*C行番号保存／来歴グラフのメモリ／版ピン表現の是正／原子的TSV書込／実装フェーズ分割の追加／PRD版参照の版非依存化
  - v6: 4回目AIレビュー反映。型解決依存getter/setterは不動点投入しない静的規則（汎用getter爆発を構造的に抑止）／chain経路集合の有限化規則（単純パス・循環打切）／停止性前提文の厳密化／encoding正本一元化／part分割境界の決定性。これにより §15 全フェーズの writing-plans 着手ブロッカーを解消
  - v7: ユーザー補足反映（Phase 1 完了後）。SQL方言を Oracle に確定（Pro\*C 埋め込みSQLと一貫）。Shell に C系シェル方言（csh/tcsh）を追加（§2.3 の1言語内方言・TSV `language` 語彙は "shell" 不変）。§5.1 にシェバン検出を追加し拡張子なしスクリプトも決定的に判別。§7/§8.1 を Oracle方言・bourne/cshell 二方言に精密化。§12 に「Oracle確定で tree-sitter SQL の却下理由は弱まるが、Oracle/PL-SQL の公式オフライン prebuilt wheel が無く §3/§4 単一トラック前提が採否を決めるため v1 非採用」の再評価を明記、§14 に条件付き将来候補として記録。§15 にフェーズ1.5（決定的コアの方言精密化）を追加（Phase 2 不動点エンジンとは別計画）
  - v8: ユーザー補足反映（Phase 3 完了後）。出力可読性の3改訂。**v8 は完了済み資産への意図的・破壊的スキーマ変更であり、Phase3 完了記録の Inv-1（既定経路 byte 完全不変）を再ベースライン化する**（v7 時点の Inv-1 byte 証跡は凍結し、v8 後に新ベースラインで再確立。§11/§15 参照）。(1) §9 `file` 列を `Path(--source-root).resolve()`（起動時1回確定の絶対パス）＋正規化相対パス連結へ（`chain` の relpath 表現は不変）。golden 比較ハーネス（`tests/golden/test_golden.py`）に resolve 済 source-root プレフィクスを `{SOURCE_ROOT}` へ逆正規化する前処理を追加し、`expected/*.tsv` の `file` 列を `{SOURCE_ROOT}/<relpath>` 形式へ全件移行する（オフライン再現はこの機構で維持。機構は §11 が正本）。(2) §9 決定性ソートキーを `(ref_kind_rank, chain_group, file, lineno, …)` へ改訂し direct ブロック→indirect ブロック（indirect は chain＝値の流れごとに集約）。**Phase1 純 direct golden は順序不変。indirect 行を含む 6 件（chain_multipath / getter_no_expand / indirect_constant / indirect_var_shell / oracle_direct / shell_direct）は再生成対象（うち chain 集約で行順が変わるもの／A:file絶対化・B:snippet多行化で byte のみ変わるものを含む。3要因別の正確な内訳は再生成 diff を正本にレビュー承認＝§15 フェーズ4 が正本）**。(3) §9 `snippet` を1行から構文単位・複数行へ（java/c=tree-sitter 最小意味ノード、Pro\*C=EXEC区間は原ソース正規表現スパン／区間外は C と同経路、sql/shell=決定的ヒューリスティック）。物理行は §9 サニタイズ後 ASCII リテラル ` \n ` 連結で1セル＝生改行ゼロ維持（全 codec で round-trip 保証＝output_writer/tsv/resume/manifest の決定性機構は不変）。ヒット行中心の上下対称縮約＋上限（既定 12 行/800 文字）両端省略マーカ。§5.1/§7 に snippet ライフタイム、§8.2/§8.4 に snippet 境界・perf 再測定、§9 サニタイズ拡張、§11 に回帰ケース＋golden 比較機構、§14 に opt-in RFC4180 を追記
  - **v9（現行・v8 批判的AIレビュー収束反映）: 3観点並列レビューの Critical/Important を反映。golden 比較機構の normative 規定（§11）／`file` 解決規則の一意化と §8.2 用語整合（§8.2/§9）／Pro\*C EXEC区間 snippet 専用規則（§7/§9）／tree-sitter 構文別ノード対応表＋同一行複数 statement・複数行式・parse 失敗フォールバックの一意化（§9）／上限縮約の擬似コード（§9）／sql/shell ヒューリスティックの走査方向・mask 整合・大小無視の確定（§9）／全順序性の論証と残余全列タイブレーク（§9）／サニタイズ対象集合拡張と区切り衝突エスケープ（§9）／diagnostics は relpath 維持の層分離（§10.3）／part 分割は行数基準で不変・`_ITEMS_PER_MB`/perf 再測定（§9/§8.2）／Inv-1 再ベースラインと既存 expected 全件再生成を §11/§15 へ明記。**反復2 追加収束**: `_node_at_line` は最小葉トークンを返す実体に合わせ「段1=最小内包ノード→段2=`.parent` 上昇で粒度表構文へ昇格」を §9 に明記（Crit-2）／Pro\*C EXEC 区間検出を**リテラル空白化コピー上**で行い文字列内 `;` 誤切断を回避（§7・§8.4 境界・Crit-1）／Java `try_with_resources_statement`・C `case_statement` ノード規則の一本化（§9）／`chase.mask_literals` は行単位・heredoc 非対応の実体を明記し過大評価を撤回（§9/§8.4）／golden 比較は manifest encoding で読戻し＋resume 系は `is_complete` も assert（§11）／`{SOURCE_ROOT}` 逆置換は `SR+"/"` 先頭1回のみ（§11）／Inv-1 凍結証跡を「数値」でなく `phase0-gate-result.md` 該当節の行番号参照へ訂正（§15・C-2'）／フェーズ4 着手循環の解消＝golden 固定は writing-plans 成果物（§15・I-3'）／symlink golden は `--follow-symlinks` 前提を明記（§11）**
- ステータス: ドラフト（v9＝v8 批判的AIレビュー収束反映済・ユーザー再レビュー待ち）。v8/v9 は Phase3 完了後の意図的破壊的スキーマ変更（Inv-1 再ベースライン）
- 位置づけ: `docs/product-requirements.md`（PRD）を受けた確定設計。本書が実装計画 (writing-plans) の入力。**§4.2 ゲートG1 と §15 フェーズ0 は writing-plans 着手前のブロッキング前提**。

---

## 1. 目的と網羅性の約束

Java / C / Pro\*C / SQL / Shell（v1）が混在する大規模レガシーシステムで、特定の文言（文字列値・コード値）を転用・削除する開発者が「その値が今どこでどのように使われているか」を把握できるようにする。grepで拾えない**定数経由・getter/setter経由・変数経由の間接参照**まで追跡し、**使われ方を自動分類**、**横にひと目でわかる要約**付きTSVを出力し、数万行規模の手作業確認を不要にする。

### 網羅性の約束

tree-sitter は正確な構文木を与えるが**型解決・名前解決は行わない**。よって絶対的なゼロ見落としは構造上保証しない。

> 追跡ポリシー（§8）の範囲で**到達可能な間接参照を不動点まで最大限追跡**し、grep単独より網羅性を大幅に向上させる。原理的に追跡不能なクラスと横展開を抑止したシンボルは**§8.4 を正本として diagnostics に必ず明示**し、レビュアーが見落としを認識できる状態にする。

PRD と本書は相互に「設計書（最新版）を正とする」と明記済み（PRD は版非依存参照に修正済み）。齟齬時は本書を正とする。

---

## 2. 確定した制約・前提

### 2.1 実行環境（確定）

| 項目 | 内容 |
|---|---|
| 稼働先 | **モダンLinux・オフライン** |
| ネットワーク | オフライン（依存は wheelhouse 同梱で持ち込む） |
| Python | **3.12 がターゲットに既存**（同梱不要）。開発＝稼働ともに 3.12 |
| ネイティブ依存 | 可（manylinux prebuilt wheel を利用） |
| 配備 | wheelhouse のみ持ち込み → `pip install --no-index`（§4） |
| **要確定欄（実装前ゲート G1）** | **ターゲットの CPUアーキ＝____ / libc＝glibc(≧__) または musl ／ Python ABIタグ＝cp312**。wheel 入手可否を決める（§4） |

### 2.2 設計方針

- Python 3.12 標準ライブラリ ＋ prebuilt 外部依存（tree-sitter＋言語grammar、文字コード判定、`pyahocorasick`、任意 ripgrep）を **vendored wheelhouse**（完全バージョンピン）で同梱。
- **tree-sitter を構文解析の主軸**（§7）。**soot 不採用**（§12）。
- 60GB走査はネイティブ高速手段（§8.2）。本ツールはネットワーク不使用。

### 2.3 v1 スコープ

- 対象言語: **Java / C / Pro\*C / SQL（= Oracle 方言・Pro\*C 埋め込みSQLと一貫） / Shell**。残りは **v2+** で言語別プラグイン経由追加。
- **Shell は1言語**だが内部に2方言 — **bourne 系**（sh/ksh/bash）と **C系**（csh/tcsh）。方言は分類規則・追跡抽出の選択にのみ用い、TSV `language` 列は "shell" 固定（§5.1/§7/§9）。

---

## 3. アーキテクチャ（単一トラック・条件付き）

単一の成果物（本体＋wheelhouse）。**ただし「全必須依存が対象環境向け prebuilt wheel で揃う」場合に限り単一トラック成立**。揃わない依存があれば §4.2 のフォールバック経路（限定的 sdist ビルド or 代替）が発生する。

---

## 4. オフラインLinux配備と前提検証ゲート

Python 3.12 はターゲットに既存（§2.1）。配備は wheelhouse 持ち込みのみ。

### 4.1 同梱依存（完全バージョンピン。`requirements.lock` で版/ハッシュ固定）

| 依存 | 用途 | 区分 |
|---|---|---|
| `tree-sitter`（Pythonバインディング） | 構文解析ランタイム | 必須 |
| `tree-sitter-java` / `tree-sitter-c`（grammar） | Java / C(Pro\*C基盤) 解析 | 必須 |
| `pyahocorasick`（ネイティブ） | 多シンボル同時走査 | 必須 |
| `chardet`（文字コード判定） | エンコーディング検出 | 必須 |
| `ripgrep` バイナリ（対象アーキ用） | 1次粗フィルタ高速化（任意） | 任意 |

- **py-tree-sitter は 0.x 系であり、破壊的変更はマイナー境界（0.21 等）で発生**する。よって「メジャー版固定」ではなく **`==` による完全版ピン**とし、**grammar も同一系列でピン**、`requirements.lock` に版＋ハッシュを固定する。ロードは **`tree_sitter_<lang>.language()` 経路に確定**（0.21+ API）。バインド版と grammar ABI の整合はスモークで検証（§11）。

### 4.2 前提検証ゲート G1（writing-plans 着手前のブロッキング前提）

1. ターゲットの **CPUアーキ・libc（glibc版 or musl）・cp312** を確定し §2.1 要確定欄を埋める。
2. 開発環境で `pip download --no-deps --platform <対象> --python-version 3.12 --only-binary=:all:` 等により、**全必須依存（tree-sitter本体／java／c grammar／pyahocorasick／chardet）と推移依存の cp312・対象プラットフォーム wheel が取得可能**であることを実証。
3. 取得不能な依存があれば、その依存に限り (a) sdist ビルド用ツールチェーン同梱（単一トラック前提が部分失効・§3）、または (b) 代替実装、を実装計画で意思決定。

→ ゲート未充足のまま writing-plans を確定しない（§15 フェーズ0）。

---

## 5. 本体アーキテクチャ

### 5.1 パイプライン

```
Ingest → Seed化 → 言語ディスパッチ → 分類器(tree-sitter主軸) → 不動点・ターゲットスキャン・エンジン → TSV出力(+診断)
```

- **Ingest**: `input/*.grep` を文字コード判定の上で読込・行パース（§6）。
- **Seed化**: `{keyword, source_path, lineno, raw_line, language, match_span}`。
- **言語ディスパッチ（決定的規則・優先順位順）**:
  1. `--lang-map EXT=LANG` 上書き（拡張子キー）。値 `shell` のときの方言は下記「Shell 方言の確定」に従う。
  2. 拡張子マップ: `.java`→Java、`.sql`→SQL(Oracle)、`.pc`→Pro\*C、`.c`/`.h`→C、`.sh`/`.ksh`/`.bash`→Shell(bourne)、**`.csh`/`.tcsh`→Shell(cshell)**。
  3. **シェバン検出（拡張子が未知または無い場合）**: 第1物理行（先頭の BOM・空白を除去後）が `^#!` のとき interpreter の basename を解析。`#!/usr/bin/env X` は X を interpreter とみなす。`sh`/`bash`/`ksh`/`dash` 系→Shell(bourne)、`csh`/`tcsh`→Shell(cshell)。**シェル以外（`perl`/`python` 等＝§14 将来言語）は Shell に分類せず** `unsupported_shebang` を diagnostics（§10.3）に記録し 5 へ。
  4. 内容ヒューリスティック: `.c`/`.h`/`.pc`/未知 で `EXEC SQL` を含むものは Pro\*C。
  5. 判定不能は diagnostics 記録のうえ **C にフォールバック**。
- **Shell 方言の確定（決定的・言語が Shell に確定した全経路で適用）**: 言語が Shell（上記 1〜3 のどれで確定したかを問わず）になったら、方言を次順で決める。① 第1物理行がシェル系シェバン（`csh`/`tcsh` または `sh`/`bash`/`ksh`/`dash`）ならその方言（拡張子由来の方言より**シェバン優先**。例 `.sh` ＋ `#!/bin/csh` → cshell）。② シェバンが無ければ拡張子（`.csh`/`.tcsh`→cshell、`.sh`/`.ksh`/`.bash`→bourne）。③ どちらも無ければ **bourne 既定**。**重要（言語判定と方言判定は独立）**: 上記手順3のシェバン検出は「言語判定のため、拡張子が未知/無のときだけ」走るが、本「方言の確定」①のシェバン照合は「言語が Shell の全ケース」で走る（`.sh`/`.ksh` 等の既知シェル拡張子でも第1物理行のシェバンを必ず確認して方言を決める）。判定はファイル名と第1物理行のみに依存し走査順非依存（§9 決定性）。
- **分類器**: §7。**走査エンジン**: §8。**TSV出力**: §9（診断は §10.3）。

### 5.2 言語別プラグイン・インタフェース（v2+ 追加点）

各言語モジュールが実装: `classify(node_or_line, ctx)` / `extract_chase_symbols(seed_or_hit)`（ヒットからも再抽出可＝不動点拡張）/ `tracking_policy`（§8.3）。

---

## 6. 入力契約

- `input/<keyword>.grep`（複数可。ファイル名 stem = キーワード）。
- 1行 = `grep -rn` 相当 `path:lineno:content`。`^(?P<path>.*?):(?P<lineno>\d+):(?P<content>.*)$` で**最左の `:<数字>:` 境界**採用（非貪欲）。
- 不一致行は捨てず diagnostics（§10.3）へ。
- CLI `--source-root <60GBツリー>` を tool が走査。`.grep` 自体も文字コード判定対象（§10.1）。

---

## 7. 分類器（tree-sitter主軸）

`confidence` は**ヒット（行）単位**（同一ファイル内で混在し得る）:

- `high` = tree-sitter AST により**構文位置が確定**（意味的同一性は保証しない）。
- `medium` = 正規表現分類。
- `low` = 型解決を要する間接（getter/setter 等）で人間確認前提。

言語別:

- **Java**: tree-sitter-java（Java 8〜17+）。判定軸: 宣言/比較(if・equals)/代入/メソッド引数/return/switch・switch式/アノテーション/文字列連結・text block/ログ・出力。
- **C**: tree-sitter-c。`#define`/初期化/比較/関数引数/`switch case`/文字列。
- **Pro\*C（前処理方式・行番号保存を確定）**: `EXEC SQL ... ;`／`... END-EXEC`／`EXEC ORACLE ...` 区間を**構文中立なプレースホルダ・トークンに置換**して tree-sitter-c の構文を温存。**置換は行数・物理行境界を保存する**（複数行 EXEC SQL は同じ行数ぶんの中立トークン列＋改行で置換。桁ズレは許容するが**行番号は原ソースと不変**）。置換区間内は正規表現で**ホスト変数 `:var`／指示子変数 `:var:ind`／ホスト構造体 `:rec.field`／SQLリテラル**を抽出し同一行へマージ（confidence=medium）。`EXEC SQL INCLUDE`／マクロ展開前ソース／`VARCHAR`擬似型は v1スコープ外＝§8.4 に列挙。
- **SQL（= Oracle 方言・正規表現・confidence=medium。§12 で tree-sitter 非採用を確定）**: Oracle に特化した行正規表現。`:=`＝PL/SQL 代入、`||` 連結／`DECODE(...)`／`CASE WHEN`＝分岐、`WHERE …` の比較演算子＝比較、`INSERT … VALUES`／`UPDATE … SET`＝代入。バインド変数 `:var`／置換変数 `&var` を分類のため認識（追跡投入はしない＝§8.1/§8.4）。**複数行 PL/SQL ブロック（`DECLARE/BEGIN/END`）の構文解析はしない**（§12 の SQL 非パース方針を維持）。Pro\*C 埋め込み SQL と同一の Oracle 方言。
- **Shell（正規表現・confidence=medium・2方言。§5.1 で確定した方言で規則集合を切替）**:
  - **bourne 系**（sh/ksh/bash）: `^\s*\w+=`＝代入、`[ … ]`／`[[ … ]]`＝比較、`case … in`＝分岐、コマンド引数。
  - **C系**（csh/tcsh）: `^\s*set\s+\w+\s*=`／`^\s*setenv\s+\w+`／`^\s*@\s+\w+\s*=`＝代入、`if\s*\(…\)`／`while\s*\(…\)`（`==`/`!=`/`=~`）＝比較、`switch\s*\(…\)` … `case …:` … `breaksw`＝分岐。

`category` は**二層**: 共通上位（比較/代入/引数/宣言/出力/分岐）＋言語固有サブ。サブ語彙の確定は §15 フェーズで段階導入（§9/§11 の churn 回避）。

**snippet との §7 連携（v8／v9 訂正）**: 分類で用いた tree-sitter AST（java/c）はそのまま §9「snippet 切り出し規則」のノード選択に再利用する。**Pro\*C の重要訂正（v9）**: 本 §7 のマスクは EXEC 区間を「同じ行数ぶんの空行」へ潰す実装であり（`proc_preprocess.mask_exec_sql`＝改行のみ保存、トークン文字は残さない＝行番号保存の正本）、**マスク後 AST には EXEC 区間に対応するノードが存在しない**。したがって §9 の「ノード写像」は Pro\*C の EXEC 区間ヒットには適用不能。Pro\*C snippet は次の決定的規則とする: ① ヒット行が EXEC 区間に含まれるなら、**AST を経由せず当該 EXEC 区間の原ソース物理行スパン全体**を選択範囲とする（中立化前の原ソース行テキストを採用。空行化テキストは出さない）、② 区間外のヒットは C と同じ tree-sitter-c ノード規則（§9）。**EXEC 区間境界の判定（v9 訂正・Crit 対応）**: `mask_exec_sql` の `_EXEC_RE`（非貪欲 `.*?(?:;|END-EXEC)`）を**生ソースに適用すると文字列リテラル内の `;`（例 `VALUES (';', :y);`）で区間が途中切断され snippet が不正になる**。よって snippet 用の EXEC 区間検出は、**Pro\*C のリテラル・コメントを先に空白化したコピー**（`chase._MASK_SPECS["proc"]` のパターンを `re.DOTALL` で source 全体に適用）に対して `_EXEC_RE` 相当を走らせて区間 [start,end] を決め、**そのスパンを原ソース行へ写して原ソース行テキストを採用**する（行番号・物理行は §7 行番号保存と一貫）。なお行番号保存（`mask_exec_sql` 本体）はリテラル内 `;` でも改行数が保たれるため不変＝本訂正は snippet 区間検出のみに作用。残る病的構文（マスク不能なマクロ合成等）は §8.4 の既知境界（過小/過大を仕様化）。これにより必須回帰「Pro\*C `EXEC SQL` ＋行番号保存」「(v8) Pro\*C snippet」が実装可能。sql/shell は AST 非使用のため §9 の決定的ヒューリスティックで切り出す（限界は §8.4 を正本）。

**snippet のライフタイム（v9・§5.1 連携）**: snippet は **分類ステージで** AST（java/c）・原ソース行（Pro\*C は §7 マスク時に保持する原ソース行配列、sql/shell は当該ファイルの物理行配列）から確定し、確定済み文字列のみ `Hit.snippet` に格納する。TSV 出力ステージへ AST は渡さない（AST を出力まで保持しない＝§8.2 メモリ対象を増やさない）。§5.1 パイプライン上は「分類器」ステージ内の最終副産物。

---

## 8. 不動点・ターゲットスキャン・エンジン（網羅性優先・偽陽性は抑止）

ユーザー決定: **網羅性優先・性能犠牲許容**。ただし**偽陽性ノイズは許容しない**（PRDの目視削減目的を守る）。

### 8.1 アルゴリズムと停止性

1. seed/既存ヒットから各言語モジュールが追跡シンボルを抽出（定数識別子、連鎖代入先、getter/setter名、SQL/Shell変数代入）。SQL(Oracle) は同一ファイル内 PL/SQL `var := 式` の左辺、Shell(bourne) は `var=` の左辺、Shell(cshell) は `set var =`／`setenv VAR`／`@ var =` の左辺を `indirect:var` 追跡シンボルとする。Oracle のバインド変数 `:var`／置換変数 `&var` は外部・ホスト境界のため追跡投入しない（Pro\*C ホスト変数と同様＝§8.4）。
2. **シンボル採否ポリシー（§8.3）適用後**に採用シンボルを `pyahocorasick` オートマトンへ。
3. ソースツリーをストリーミング走査（`multiprocessing` ファイル並列、任意 `ripgrep` 1次粗フィルタ）。
4. 新規シンボルが出れば追加し**不動点（新規が枯れる）まで反復**。多ホップ定数・連鎖代入も追う。
5. **停止性（正当性の根拠）**: 追跡シンボルは**すべてソースツリー上に字句出現する識別子**である（実行時合成名は §8.4 で除外）。`extract_chase_symbols` は**原ソースの字句**に対して抽出する（Pro\*C は §7 の置換前ソース基準。中立プレースホルダ・トークンは追跡対象にしない／Pro\*C/Oracle のホスト変数 `:var`・バインド/置換変数は**手順1 のとおり追跡投入しない**＝外部・ホスト境界・§8.4。仮に将来投入する場合も停止性は `:` を剥がした原識別子の有限性で担保される＝本規定は投入是非ではなく停止性の字句形のみを述べる）。ソースツリーは有限なので**追跡シンボルの母集合は有限**。`extract_chase_symbols` による採用集合は反復で縮小しない（**単調増加**）。有限母集合＋単調増加 → **高々 |母集合| ステップで飽和し不動点に到達**。`--max-depth`・集合サイズ上限は正当性の根拠ではなく**安全弁**（暴走時の打ち切り）。
6. 暴走防止: シンボル循環検出、シンボリックリンク・ループ検出（§8.2）、`--max-depth` 到達は diagnostics 明示で打ち切り。
7. 各間接ヒットを分類し、起点seedへの**来歴**を記録（来歴の集約は §8.2）。

### 8.2 性能・資源設計

- ネイティブ Aho-Corasick（`pyahocorasick`）＋任意 `ripgrep` 1次フィルタ＋`multiprocessing`。
- **差分走査の正確な効果（誠実化）**: 新規シンボルは前パスで未ヒットの任意ファイルに出現しうるため**新規シンボル分は全ツリー走査が必要**。ファイル→該当行ローカリゼーション保持で省けるのは「**確定済みシンボルの再ヒット再走査**」のみ。「段数≠走査回数」はこの限定的効果を指す。
- **来歴グラフのメモリ（ワーカ横断集約）**: 来歴は本質的にグローバル有向グラフ。ファイル並列ワーカは担当ファイルのみ見るため、ワーカは `(発見元シンボル, 発見シンボル, file, lineno)` のエッジ断片のみ返し、**集約フェーズで来歴グラフを合成**。来歴グラフのメモリは Aho-Corasick 常駐とは別物として `--memory-limit` の対象に含め、上限超過時はディスクスピル。
- degrade 優先順位: `--memory-limit` 超過時は **(優先1) §8.3 の決定的シンボル切り捨て**（再走査を増やさず決定性維持）→ (優先2) 来歴グラフのスピル → **(最終手段) オートマトン分割（=複数パス再走査）**。最大走査パス数の上限を実装計画で明示。
- ファイルサイズ上限＋バイナリ判定 skip、include/exclude glob（**生成コード既定除外**・除外は diagnostics 記録）。
- **シンボリックリンク既定で辿らない**（`--follow-symlinks` 任意）。inode/実パス正規化で同一実体の二重走査を排除。**重複時の代表選択は relpath 辞書順で決定的**（v9 用語整合: 実装 `walk.py` は走査候補を `sorted()` 後に走り最初の relpath を代表とする＝relpath 辞書順。v8 以前の「正規化パス辞書順」表現を実装に合わせ relpath 辞書順へ統一）。リンクループは検出して打ち切り。
- **`file` 列の path 解決（v9・§9 連携）**: §9 `file` は `Path(--source-root).resolve()`（symlink 解決済の絶対 source-root を**起動時1回**確定）＋走査時の論理 relpath（symlink 温存）の `/` 連結＝**source-root のみ resolve した擬似絶対パス（厳密 realpath ではない）**。代表 relpath 選択は本節のとおり relpath 辞書順。`chain` と diagnostics（§10.3）の path は relpath 維持（§9）。symlink 重複排除 golden（§11 名指し）の `file` 期待値は「`{SOURCE_ROOT}/<代表relpath>`」。
- **進捗ログ**: 標準エラーへ定期進捗（処理済みファイル数/バイト、現ホップ、シンボル集合サイズ、ETA）。`--progress` で粒度調整。
- **snippet 多行化の資源影響（v9）**: snippet 複数行化は1セル内 ` \n ` 連結で **TSV レコード数を変えない**ため §9 規模対策の part 分割境界（行数基準）は不変。ただし1レコード最大バイトが増えるため `budget._ITEMS_PER_MB` 較正値・`tests/perf` ベースラインは v8/v9 後に再測定し新ベースライン化する（絶対SLAではないため非ゲート＝§11）。

### 8.3 シンボル採否ポリシー（偽陽性抑止・v1は静的のみ）

不動点追跡へ投入する前にシンボルを篩い、汎用名の横展開爆発を防ぐ。**v1 のストップリストは事前フル走査を要しない静的ソースのみ**で構成（「プロジェクト頻出トップN」の動的算出は事前60GB走査が必要で §8.2 の性能前提と循環し非決定的になるため v1スコープ外＝§14）:

- **型解決依存シンボルの非投入規則（汎用getter爆発の構造的抑止・PRD生命線）**: `extract_chase_symbols` が **getter/setter（メソッド名）として抽出したシンボル**は、tree-sitter が型解決をしない以上、呼び出し元オブジェクトの型同定が不能で `getName`/`getValue` 等が60GBで爆発する。よってこれらは**不動点追跡集合へ投入しない**（横展開しない）。**多ホップ追跡の対象は constant / var 経由のみ**。getter/setter は §8.4 のとおり direct 一致のみ `ref_kind=indirect:getter|setter` / `confidence=low` で報告し、横展開しなかった旨を §8.4 正本として diagnostics に記録。動的トップN無しでも汎用getter爆発を構造的に止める。
- **静的ストップリスト**: ① 言語キーワード／予約語、② 最小長しきい値未満の識別子（`--min-specificity`）、③ ユーザ提供 `--stoplist` ファイル（静的）。これらに該当するシンボルは**追跡集合に入れず、direct一致のみ報告して横展開しない**。
- 集合サイズ上限超過時の切り捨ては**決定的**: シンボルを `(発見ホップ数, 識別子長, 文字列辞書順)` で安定ソートし上限内を採用。
- 横展開を抑止・切り捨てたシンボルは**§8.4 を正本として全件 diagnostics に列挙**。

### 8.4 既知の取りこぼし・抑止の正本（diagnostics に必ず明示）

本節を**唯一の正本**とし、§1/§8.3/§10.3 はここを参照する（重複記述を排除）:

- **型解決を要する getter/setter**: `obj.getX()` の `obj` 型同定不可。同名メソッド全件 `confidence=low`、意味的同一性は人間判断。
- **リフレクション / 動的呼び出し**。
- **実行時の文字列連結・整形で生成される名前**。
- **Pro\*C の `EXEC SQL INCLUDE`・マクロ展開前ソース・`VARCHAR`擬似型**。
- **正規表現方式言語（SQL/Shell）の限界**: 動的生成SQL・heredoc・`eval`・複数行マクロは構文追跡不可。
- **Oracle 固有の追跡境界**: バインド変数 `:var`／置換変数 `&var`／動的SQL（`EXECUTE IMMEDIATE`・文字列連結で組み立てる SQL）・複数行 PL/SQL ブロック内の連鎖は構文追跡不可（§7/§8.1）。**トリガ相関名 `:new`/`:old` および修飾代入 `rec.field := …` の左辺は v1 既知境界**: §8.1 抽出は限定子を剥がした末尾識別子（例 `:new.col := 1`→`col`）を決定的に採るが、相関名・レコードフィールドの意味的同一性は保証しない。汎用名の横展開は Phase 2 の §8.3 静的ストップリストで抑止する前提（v1 はこの挙動を仕様として固定＝誤検出ではない）。
- **C系シェル（csh/tcsh）の限界**: `eval`／`source`／`alias`／バッククォート合成経由は追跡不可。`.cshrc`/`.login` 等の設定ドットファイル（拡張子なし＋典型シェバンなし）は v1 スコープ外。
- **非シェルのシェバン**: `perl`/`python` 等（§14 将来言語）は Shell に分類せず `unsupported_shebang` として記録（§5.1）。
- **生成コード**（既定除外。除外した旨を記録）。
- **§8.3 で横展開を抑止／集合上限で切り捨てたシンボル**（全件列挙）。
- **snippet 切り出しの境界（v8・§9「snippet 切り出し規則」を正本参照）**: sql/shell は AST 非使用ヒューリスティックのため、動的生成SQL・heredoc・`eval`・複数行マクロでは構文単位を正しく囲えず過大／過小になり得る（誤検出ではなく v1 仕様）。上限クランプ（既定 12 行／800 文字）超過で省略が生じた場合は snippet 内に決定的マーカ `…(+K行省略)` を残し取りこぼしを隠さない。**Pro\*C EXEC 区間 snippet（v9）**: §7 のとおりリテラル・コメント空白化コピー上で区間検出するが、マスク不能な構文（プリプロセッサ合成・`_MASK_SPECS["proc"]` で覆えない特殊リテラル）では区間が過小/過大になり得る＝本境界として記録（決定的・誤検出ではない）。
- **非UTF-8 `--output-encoding` での非エンコード文字（v9・既知の既存境界）**: `--output-encoding cp932` 等で、出力 codec で表現できない文字がいずれかのセルに含まれると `output_writer._part_bytes`（`errors="replace"`）で `?` 置換され、`resume.is_complete` の sha 照合（manifest 側は utf-8 正規化 `_canonical_data_blob`／resume 側は **part を出力 codec で復号後 `_blob_from_data_rows` で utf-8 正規化**して sha 比較＝復号は出力 codec・sha 正規化は常に utf-8 固定）が不一致となり当該 keyword は `--resume` 完了不能になる（**v8 以前から存在する境界**）。v9 は snippet 行連結区切りを ASCII リテラル ` \n ` に確定し**全 codec で round-trip 保証**することで、複数行 snippet 化がこの境界を構造的に拡大しないようにする（区切り起因の resume 破壊はゼロ）。原ソース由来の非エンコード文字に対する完全な対処は v1 スコープ外＝本境界として記録（回帰は §11「cp932×複数行snippet×--resume 完了」で区切り起因ゼロを固定）。

diagnostics 出力規約は §10.3。

---

## 9. TSV 出力スキーマ

`output/<keyword>.tsv`。タブ区切り、フィールド内タブ/改行サニタイズ。既定 **UTF-8 with BOM**（Excel互換）。**非UTF-8出力（`--output-encoding cp932` 等）時は BOM を付与しない**。

| 列 | 内容 |
|---|---|
| `keyword` | 調査対象の文言 |
| `language` | 判定言語（Shell は方言不問で "shell" 固定。bourne/cshell は分類・追跡の内部属性＝§5.1/§7） |
| `file` | **`SR + "/" + <正規化relpath>`・`/`区切り固定**（v8／v9 一意化）。`SR` ＝ `Path(--source-root).resolve()` を**プロセス起動時に1回**確定した絶対パス文字列（`--source-root` が相対指定でも resolve で cwd 非依存に絶対化し全行で固定。symlink は SR のみ解決＝§8.2「擬似絶対パス」）。`<relpath>` は §8.2 の代表 relpath（symlink 温存・relpath 辞書順代表）。`chain`・diagnostics の path は relpath 維持（変更しない＝来歴ID簡潔化・層分離）。golden は **§11 の比較機構**（`test_golden.py` が `SR` を `{SOURCE_ROOT}` へ前方一致逆置換）で決定性・オフライン再現を維持 |
| `lineno` | 行番号（Pro\*C も原ソース基準・§7 行番号保存） |
| `ref_kind` | `direct` / `indirect:constant` / `indirect:getter` / `indirect:setter` / `indirect:var` |
| `category` | 共通上位カテゴリ（§7） |
| `category_sub` | 言語固有サブ（§15 で段階導入。**golden 初版は空固定**で churn 回避） |
| `usage_summary` | ★ひと目要約 |
| `via_symbol` | 経由シンボル（direct は空） |
| `chain` | 来歴の正規形（下記） |
| `snippet` | ★該当箇所の**構文単位・複数行**（v8。下記「snippet 切り出し規則」）。物理行は下記「サニタイズ規約」適用後 **ASCII リテラル ` \n `（空白＋バックスラッシュ n＋空白の3文字）** で連結し1セルに収める＝**フィールド内に生改行を持たない**（全 codec round-trip ＝タブ区切り・原子書込・`--resume`・manifest の決定性機構は不変）。`lineno` はヒット行を指す（snippet 開始行ではない／chain 末尾ホップの lineno と一致） |
| `encoding` | 判定文字コード（置換時の「要確認」規約は §10.1 を正本とする） |
| `confidence` | `high`/`medium`/`low`（ヒット単位） |

**サニタイズ規約（v9・全セル共通・決定性必須）**: 各セル文字列は連結・出力前に次を順に適用する。① `tsv._sanitize` を拡張し **`\t` `\r` `\n` `\v`(U+000B) `\f`(U+000C) `U+0085`(NEL) `U+2028`(LS) `U+2029`(PS) を半角空白1個へ置換**（Excel・TSVビューアでの行/改ページ分割を防ぎ「1セル」目的を担保。`split("\n")`/`data_sha256` の決定性コアは `\n`→空白で従来どおり不変）。② snippet 連結時、**ソース物理行テキスト中に区切り列 ` \n `（U+0020 U+005C U+006E U+0020）と同一の3文字並びが出現した場合**、その出現の `\`(U+005C) を `\\`(U+005C U+005C) へ決定的にエスケープしてから ` \n ` で連結する（区切りと本文の曖昧化を防ぐ・逆変換は将来 §14 のみ必要なので v1 はエスケープのみ規定）。③ ①②は `tsv.py:_sanitize`／`output_writer._data_line` の改修を伴う＝v8/v9 は当該コアの**対象集合拡張という改修**を含む（「決定性アルゴリズムは不変・対象文字集合のみ拡張」と正確に理解する）。回帰は §11。

**chain 正規形（決定性のため必須）**: 各ホップを `symbol@<relpath>:<lineno>` とし ` -> ` で連結（起点→経由→ヒット）。**経路集合の生成・有限化規則**: chain は来歴グラフ上の**単純パス**（同一エッジ・同一シンボルを二度通らない）に限り列挙する。**「同一シンボル」の定義（明確化）**: 不動点に投入された**追跡識別子（chase の constant/var・terminal の getter/setter）**を指す。起点 keyword（本 §9 `keyword` 列＝**調査対象の文言**であり追跡識別子ではない）は循環判定の対象外とし、keyword の文言が最初の追跡識別子と同名の場合（例: keyword が変数名で `CODE@def -> CODE@use`）も単純パスとして許容する（PRD 主目的＝当該シンボルの利用箇所列挙を満たすため。§8.1 手順1 の「seed/既存ヒットから追跡シンボルを抽出」と整合）。循環は最初の再訪エッジで打ち切り §8.4 正本として diagnostics 記録。`--max-depth` 超過パスも打ち切り。これにより経路集合は**有限かつ決定的**。**同一ヒット（同一ヒット行＝同一 `file`:`lineno`。snippet 複数行化後も重複粒度はヒット行単位）へ異なる単純パスで到達した場合は経路ごとに別行**（この場合の行重複を許容し、§9 決定性ソートで安定化。重複許容を本スキーマの仕様とする）。

**snippet 切り出し規則（v8・決定性必須）**: ヒット行を含む「処理がひと目で分かる最小単位」を決定的に切り出す。判定は対象ファイルの物理行のみに依存し走査順非依存（§9 決定性・golden 前提）。

「選択範囲（物理行 [start, end]）」を言語別に**一意決定**してから「上限と切り詰め」を適用する。`hit = lineno`（ヒット行・1始まり物理行番号）。

- **java / c（tree-sitter・分類と同一 AST。Pro\*C は §7 の専用規則を先に適用し、EXEC 区間外のみ本規則）**: ヒット行に対応する選択ノードを**2段で**一意に決める（v9 訂正: 実装 `ts_classifier._node_at_line` は対象行を**内包**するノードを子へ降りながら `(行スパン, start_byte, end_byte, node.type)` 最小で選ぶため、戻り値は statement ではなく**最小の葉トークン**＝`identifier` 等。よって「同一タイブレークで最左 statement が選ばれる」とは書けない。`classify_ts` が `.parent` を遡って文レベルへ昇る挙動と一貫させる）:
  - **段1（最小ノード）**: `_node_at_line(root, hit)`＝`hit-1`(0始まり) を `start_point[0] ≤ t ≤ end_point[0]` で**内包**するノードのうち上記タイブレーク最小（実装と同一・部分オーバーラップは扱わない）。
  - **段2（構文ノードへ昇格）**: 段1ノードから `.parent` を上昇し、**下記「粒度」表の構文種別に最初に一致した祖先**を選択ノードとする。`block`/`compound_statement`/メソッド・関数本体/`program`/`translation_unit` に達しても未一致なら、その手前で最後に通過した statement 系ノード（表「単純文」該当）を採用。**昇格経路に statement 系も粒度表構文も一つも無い場合はフォールバック (3)＝`hit` 1物理行のみ**（決定性は必ず閉じる）。**同一物理行に複数 statement が同居する場合の粒度（v9 訂正・実体明記）**: 実装 `_node_at_line(root, lineno)` は**列引数を持たず**、行内タイブレーク最小＝`start_byte` 最小＝**行頭側の葉**を返す。よって `a();b();c();` で grep ヒットが `b()`/`c()` 上でも段1 は常に行頭 `a` を返し、段2 は **ヒット列に関わらず行頭の statement**（`a();`）を選ぶ（決定的）。これは **v1 既知の粒度＝§8.4 境界**（「ヒットした文」ではなく「ヒット行の行頭 statement」になる）。ヒット列単位の精密化は §14 将来候補。
  - **粒度（上位優先・構文別の具体ノードへ落とす。括弧範囲＝対応する `(`/`)` トークンの物理行スパン）**:

    | 構文 | Java ノード | C ノード | 選択範囲 |
    |---|---|---|---|
    | 単純文 | `*_statement` / `local_variable_declaration` / `field_declaration` / `return_statement` 等 | `declaration` / `expression_statement` / `return_statement` 等 | 当該 statement ノードの物理行スパン（複数行式はそのまま全行） |
    | if / while | `if_statement`/`while_statement` の `condition`(`parenthesized_expression`) | 同左 `parenthesized_expression` | `(`〜対応する `)` の物理行スパンのみ（**本体ブロック非包含**） |
    | for | `for_statement` | `for_statement` | `for` キーワード直後の `(`〜対応する `)` の物理行スパン（init/cond/update を含む。header ノードが無い言語のための括弧トークン範囲規則） |
    | switch | `switch_expression`/`switch_statement` の `parenthesized_expression` | `switch_statement` の `parenthesized_expression` | `(`〜`)` の物理行スパン |
    | case 節 | `switch_block_statement_group` ノード | `case_statement` ノード | **当該ノードのスパンをそのまま採用**（ノード規則に一本化＝冗長プローズ削除）。C `case_statement` は通常「当該ラベル〜次ラベル直前まで」を1ノードに含むが、**本体を持たないラベル（共有ラベルの先頭 `case 1: case 2: …` の `case 1:` 等）はそのラベル行のみ**＝v1 既知粒度・§8.4（ヒットしたラベルの `case_statement` ノードを採用） |
    | try | `try_statement` / `try_with_resources_statement` | （C は該当なし） | `try` キーワード行〜`block` 直前（`try_with_resources_statement` の `resource_specification` を含む。両ノード型を判定し、どちらでもなければ「単純文」へ落ちない） |
    | 宣言の修飾子/アノテーション | `modifiers`/`annotation` を宣言ノードに含む | `storage_class_specifier` 等を declaration に含む | 宣言ノードに内包（別途広げない） |

  - **フォールバック順（決定的・§10.3 部分パース継続と接続）**: (1) 上記でノードが取れる → そのスパン。(2) parse 失敗・`_node_at_line` が `None`・選択ノードが `ERROR`/`MISSING` を含む → **sql/shell と同じヒューリスティック**（下記）を当該行に適用。(3) それも不能 → **`hit` 1物理行のみ**。
- **Pro\*C**: §7「snippet との §7 連携」を正本とする（EXEC 区間ヒット＝原ソース `_EXEC_RE` スパン全体／区間外＝上記 c 規則）。
- **sql / shell（AST 非使用・決定的ヒューリスティック）**: 判定対象は既存 `chase.mask_literals(language, line)` を**各物理行に行ごと適用**したコメント・文字列マスク後の行（句境界・括弧・クオートの誤爆防止／既存資産を流用し二重実装しない）。**重要（実体明記・v9）**: `chase.mask_literals` は**行単位関数で heredoc 規則を持たない**（shell マスクは二重/単一引用とコメントのみ）。よって **heredoc は本ヒューリスティックではマスクされず**、heredoc を跨ぐ範囲は構文単位を正しく囲えない（過大/過小）＝§8.4 の既知境界に委ね、上限クランプで有限化する（heredoc 対応の複数行マスク化は v1 非対象）。境界キーワードは**大文字小文字無視**（`re.IGNORECASE`）。走査は **(1) 上方向、(2) 下方向の順**に `hit` から1行ずつ、各方向独立に次の停止条件まで拡張する: 行末 `\` 継続が無く、括弧 `() [] {}` がバランスし、クオート/heredoc が閉じ、かつ — SQL は文末 `;` か直近の句境界キーワード（`WHERE`/`SET`/`VALUES`/`SELECT`/`FROM`/`GROUP BY`/`ORDER BY`/`HAVING`）、shell は `;`/`fi`/`done`/`esac`/`breaksw`/関数本体 `}` — に達したら当該方向を停止（その境界行は含む）。各方向の最大拡張は後述の行数上限に従属（境界未検出でも上限で必ず停止＝有限）。クオート/heredoc が最後まで閉じない場合は上限クランプに委ねる（§8.4 を正本）。
- **上限と切り詰め（決定的・擬似コード）**: 行数上限 **既定 12 行**、文字数上限 **既定 800 文字**（最終 ` \n ` 連結後・サニタイズ後・省略マーカ込みの文字列長で測定）。上限は v1 spec 固定（CLI 可変は §14）。

  ```
  span=[s,e]（選択範囲）, hit∈[s,e]
  out=[hit]                       # ヒット行は必ず含む
  if measure(out) > CHAR_MAX:     # ヒット行単独で文字数超過
      out[0] = truncate_codepoints(hit_text, CHAR_MAX_for_1line) ; mark_inline=True
  上 = hit-1（≥s まで）, 下 = hit+1（≤e まで）
  loop:
      # 行数上限を文字数上限より先に評価
      if len(out) >= LINE_MAX: break
      progressed=False
      if 上 >= s:                  # 上を1行 仮追加
          if len(out)+1 <= LINE_MAX and measure([line(上)]+out+pending_markers) <= CHAR_MAX:
              out.prepend(line(上)); 上-=1; progressed=True
          else: 上枯渇扱い
      if len(out) >= LINE_MAX: break
      if 下 <= e:                  # 下を1行 仮追加（上と同条件）
          if len(out)+1 <= LINE_MAX and measure(out+[line(下)]+pending_markers) <= CHAR_MAX:
              out.append(line(下)); 下+=1; progressed=True
          else: 下枯渇扱い
      if not progressed: break     # 両側とも上限/範囲端で確定
  # 省略があれば決定的マーカ（行数にカウントせず／文字数測定には含む）
  if s..(out先頭-1) に未採用行 → 先頭に "…(+K上行省略)"（K=上省略物理行数）
  if (out末尾+1)..e に未採用行 → 末尾に "…(+K下行省略)"
  ```

  - 「上を先に1行→下を1行」の交互・上限超過行は**入れずに確定**（仮追加し測定し超過なら戻す）。「対称」は両側に範囲がある間の挙動であり、片側が範囲端/枯渇したら反対側のみ継続する（語の明確化）。
  - マーカ厳密書式: `…(+<K>行省略)`（`…`＝U+2026、`<K>`＝10進・ゼロ埋め無し）。マーカは ` \n ` 連結に含めず**先頭/末尾セルに直接前置/後置**し、**行数 LINE_MAX にはカウントしない／文字数 CHAR_MAX 測定には含める**。`truncate_codepoints` は Unicode コードポイント先頭から数え、末尾に `…`(U+2026) を付す決定的切詰（バイト単位ではない）。
  - 行頭インデントは**保持**（タブは前述サニタイズで空白1個化＝桁崩れ許容）。選択範囲内の**空行も1物理行として行数・縮約に計上**する。

**ref_kind × 言語マッピング:**

| 言語 | constant | var | getter/setter |
|---|---|---|---|
| Java | `static final` 定数 | 非finalフィールド/ローカル | `indirect:getter`/`indirect:setter` |
| C/Pro\*C | `#define`・`const` | 非const変数 | — |
| SQL(Oracle) | — | 同一ファイル PL/SQL `:=` 代入=`indirect:var`（バインド/置換変数は対象外＝§8.4） | — |
| Shell(bourne) | `readonly` 等 | `var=` 代入=`indirect:var` | — |
| Shell(cshell) | — （確実な定数階層なし） | `set`／`setenv`／`@` 代入=`indirect:var` | — |

**決定性（golden前提・必須）**: 出力は安定ソートで**全順序**に並べる。キー順（v8 改訂・v9 で全順序性を論証）`(ref_kind_rank, chain_group, file, lineno, ref_kind, via_symbol, category, category_sub, confidence, usage_summary, snippet, language, encoding)`。`ref_kind_rank`＝`direct`→0 / `indirect:*`→1（**direct ブロックを先に**）。`chain_group`＝`direct` のとき空文字 `""`（全 direct が同値となり file/lineno へ落ちる）／`indirect:*` のとき `chain` 文字列（**値の流れ＝chain ごとに塊**）。`lineno` は数値順。`multiprocessing` 完了順・走査順に依存しない。
- **全順序性の論証（v9・実装非依存）**: chain 文字列はホップ系列 `symbol@relpath:lineno -> …` の単射表現。**異なる chain は `chain_group` 文字列が異なるためソートキー先頭（`ref_kind_rank, chain_group`）で順序が確定する**（同一 `file:lineno` に複数 chain の行が来ても chain_group で決定的に分離＝`chain_multipath` の B.java:1 3行は相異なる chain_group でこれにより整列。3経路が万一完全同一 chain となる病的入力のみ後述「完全同値は重複許容」に帰着＝矛盾なし）。同一 `chain_group`（＝同一 chain）は (起点〜ヒットの relpath/lineno 系列) を一意に含意するため通常 `file,lineno` も一意。さらに provenance は単純パス chain を集合化し同一 chain の重複行を生成しない（§8.1/chase 正本）。残余で完全同値となる行は仕様上の重複許容行であり、末尾に `language, encoding` を加えた本キーで一意な全順序を与える（旧 v7「全列を含む全順序」表現を「弁別に必要な列による全順序＋完全同値は重複許容」と正確化）。
- **Phase 影響（v9・正直化）**: Phase1 純 direct golden は `ref_kind_rank=0`・`chain_group=""` 一定で実質 `(file, lineno, …)` に縮退し**行順不変**（ただし `file` 絶対化・snippet 多行化により**バイトは変わる**＝Inv-1 再ベースライン対象。順序不変≠byte不変）。**indirect 行を含む 6 件（chain_multipath / getter_no_expand / indirect_constant / indirect_var_shell / oracle_direct / shell_direct）は再生成対象**（chain 集約で**行順が変わるもの**と、行順は不変だが `file` 絶対化・snippet 多行化で **byte のみ変わるもの**を含む。命名が `_direct` でも fixedpoint 経由で indirect 行を持つため対象。正確な内訳は再生成 diff を正本にレビュー承認＝§15 フェーズ4）。`model.py:sort_key` の本キー差替は writing-plans フェーズ4 タスク（§15）。

**規模対策**: 1キーワードが Excel 上限（約104万行）超見込みなら `<keyword>.partNN.tsv` 分割＋diagnostics警告。**分割は全順序安定ソート後の順次チャンク**で行う（境界は決定的。golden が割れない）。**snippet 複数行化は1セル内 ` \n ` 連結で TSV レコード数を変えないため part 分割境界（行数基準＝`opts.max_rows_per_part`）は不変**（v9。1レコード最大バイト増の perf/メモリ影響と `_ITEMS_PER_MB` 再測定は §8.2 を正本）。

---

## 10. 横断事項

### 10.1 文字コード

- バージョン固定 `chardet` で検出 → 決定的フォールバック鎖。**判定は当該ファイル全バイトを対象に1回**（チャンク境界依存を排除）。対象は §8.2 ファイルサイズ上限内。
- **decodeで絶対に落とさない**。置換発生時 `encoding` 列＋diagnostics に「要確認」。
- 入力 `.grep` と走査対象ソース両方に適用。→ PRDメモ「文字コード判定」を解決。

### 10.2 性能

§8.2。

### 10.3 エラー処理・診断・中断/再開

- 壊れたgrep行 / 読めないファイル / decode失敗 / tree-sitter部分パース失敗（部分木で継続）/ `--source-root` 不在 / 権限拒否 / max-depth到達 / 生成コード除外 / §8.4 の各クラス → **diagnostics へ集約**（非致命）。
- **diagnosticsスキーマ**: 先頭に**カテゴリ別件数サマリ**、続いて詳細。詳細上限超過時は**カテゴリ別集約＋代表サンプル**に縮約（上限は設定可能）。
- **path 表現の層分離（v9）**: diagnostics の path は §6 のとおり **relpath を維持**（絶対化は §9 `file` 列に限定。`chain` も relpath）。`file` 絶対化は TSV `file` 単独の局所変更で diagnostics path には波及しない（ただし TSV/診断問わず **snippet 多行化を含む既存期待値は再生成対象**＝§15 で「`file` 絶対化が触れる範囲」と「snippet 多行化が触れる範囲」を分けて Inv-1 を再ベースライン）。
- **TSV 原子性**: 各キーワードTSVは**一時ファイルへ書き出し→`fsync`→`rename`**で原子的に確定。`--resume` は**rename済みのみを完了**とみなす（部分書き込みファイルを完了と誤認しない）。
- **中断/再開**: v1は**キーワード単位 resume 必須**（`--resume` で完了キーワードはスキップ）。**キーワード内チェックポイントは v1スコープ外＝受容リスク**（§14）。
- 終了コードで「致命」と「警告のみ」を区別。

### 10.4 CLI

```
grep_analyzer --input ./input --output ./output --source-root <tree> \
  [--jobs N] [--include GLOB] [--exclude GLOB] [--lang-map EXT=LANG,...] \
  [--max-depth N] [--memory-limit MB] [--min-specificity X] [--stoplist FILE] \
  [--encoding-fallback cp932,euc-jp,latin-1] [--output-encoding cp932] \
  [--use-ripgrep] [--follow-symlinks] [--resume] [--progress LEVEL]
```

- **文字コード解決順は常に「① chardet 検出を最初に試行 → ② フォールバック候補鎖」**。`--encoding-fallback` は**②の候補鎖のみを置換**（検出ステップは常に最初に実行され、CLIでは無効化しない）。未指定時は §10.1 既定鎖。
- `input/` に複数 `<keyword>.grep` 可。出力はキーワード毎TSV ＋ 全体 diagnostics 1ファイル。

---

## 11. テスト方針（リポジトリ規約準拠）

`.claude/skills/writing-tests.md` 準拠（古典学派 + TDD、日本語テスト名、層の縄張り）。

- `tests/unit/`: 分類器（tree-sitterクエリ）・追跡シンボル抽出・シンボル採否（静的ストップリスト）・grep行パース・文字コードフォールバック・**不動点停止性（有限母集合で飽和）**・Pro\*C行番号保存・chain正規形。
- `tests/integration/`: CLI契約・複数keyword・エラー経路・`--resume`原子性・オプション相互作用（in-process 既定）。
- `tests/golden/`: 合成小規模代表ツリーで TSV 完全一致。**golden 比較機構（v9・normative・本節が正本。Inv-1 再ベースライン手順は §15 フェーズ4 を参照）**: `tests/golden/test_golden.py` は (a) **当該ケースの manifest `encoding`** で生成物を読み戻し（現状の `utf-8-sig` 固定読みを廃し manifest 依拠へ。cp932 等ケース対応）、(b) `SR = Path(source_root).resolve()` として **`SR + "/"` を先頭1回だけ `{SOURCE_ROOT}/` へ逆置換**（`str.replace(SR+"/", "{SOURCE_ROOT}/", 1)` 相当＝relpath 中に偶発する `SR` 文字列の誤置換と末尾区切り曖昧を排除）、(c) `expected/*.tsv` と完全一致比較、(d) **`--resume` 系ケースは併せて `resume.is_complete()==True` を assert**。`expected/*.tsv` の `file` 列は `{SOURCE_ROOT}/<relpath>` 形式で保存（v8/v9 で既存 expected を本形式へ全件移行）。これによりクローン場所非依存・オフライン再現を維持する。**カバレッジ原則**: 言語×ref_kind は必須網羅、文字コード/多ホップは pairwise 直交。**必須回帰ケースを名指し**: 汎用名の横展開抑止、決定性タイブレーク（chain複数経路の別行）、Pro\*C `EXEC SQL` 内ホスト変数＋行番号保存、symlink重複排除、文字コード混在（**期待文字コード判定値を pin**）、**Oracle 方言（`:=` 代入・`DECODE`/`CASE WHEN`）**、**C系シェル（`set var =`・拡張子なし＋`#!/bin/csh` でのシェバン判別）**、**拡張子なし bourne（`#!/bin/sh` でのシェバン判別）**、**非シェルシェバンの `unsupported_shebang` 診断**、**（v8/v9）`file` 列＝`{SOURCE_ROOT}/<relpath>`（上記比較機構で安定）**、**（v8/v9）symlink 重複排除時の `file` 列＝代表 relpath（§8.2 relpath 辞書順。本ケースは既定で symlink を `symlink_skipped` 除外するため `--follow-symlinks` 有効で実行＝dedup を実際に発火させる）**、**（v8）direct→indirect の chain 集約ソート（Phase1 純 direct は順序不変を回帰固定／indirect 6件は再生成後の chain 隣接を固定）**、**（v8/v9）複数行 snippet（複数行 if 条件部のみ／複数条件 WHERE／長大 switch・case 節／同一行複数 statement は行頭 statement 選択（列非依存・§8.4 既知粒度）／複数行式）**、**（v8）snippet 上限クランプの両端 `…(+K行省略)` マーカ・ヒット行単独超過の文字切詰（決定的）**、**（v9）Pro\*C `EXEC SQL` 区間ヒットの snippet＝原ソース `_EXEC_RE` スパン（空行非出力）**、**（v9）parse 失敗/ERROR 時の snippet フォールバック決定性**、**（v9）サニタイズ拡張（U+000B/000C/0085/2028/2029 を空白化）と区切り ` \n ` 衝突エスケープ（出力側＋`--resume` 往復で `_rows_from_part_text` 経路の行数・sha 一致も固定）**、**（v9）cp932×複数行snippet×`--resume` が完了する（区切り起因 sha 不一致ゼロ・`is_complete()==True` を assert）**。`category_sub` は初版**空固定**。
- `tests/handcrafted/`: 分類精度ダッシュボード（非ゲート）。
- `tests/test_smoke.py`: `import` ＋ `--help` exit 0 ＋ **tree-sitter バインド/grammar ABI 整合確認**。
- `tests/perf/`: 独自マーカ `@pytest.mark.perf`。handcrafted 同様**ダッシュボード（非ゲート・CI停止しない）**。§8.2 参照基準を回帰検知ベースラインとして記録（絶対SLAではない）。**（v9）snippet 多行化で1レコード最大バイトが増えるため `budget._ITEMS_PER_MB` 較正値・perf ベースラインは v8/v9 後に一度だけ再測定し新ベースライン化**（非ゲート＝Inv-1 byte 再ベースラインと同じ「v7 証跡凍結→v8/v9 で再確立」手順）。
- LLM無しのため規約のLLM項はN/A。外部I/O境界（ファイル/サブプロセス/ripgrep）は本物。

---

## 12. スコープ外・却下した代替案

- **soot**: JVM依存。tree-sitterで代替。→ 不採用。
- **tree-sitter SQL grammar**: 当初の却下理由は「方言差大」。**v7 再評価: SQL=Oracle 確定により当該理由は弱まり、tree-sitter 化で分類精度（medium→high）と複数行 PL/SQL の §8.1 抽出精度は原理的に向上する。しかし採否を決めるのは精度ではなく §3/§4 のオフライン単一トラック前提**＝Java/C のような Oracle/PL-SQL の公式・abi3・manylinux prebuilt（py-tree-sitter 0.21系ピン整合）grammar が存在せず、採用は sdist ビルド（§3 前提部分失効）・ABI 不整合（R1）・§4.2 相当の新規 G1 を要する。効果も限定的（支配的偽陽性は §8.3/§8.4 の多ホップ getter 爆発であり SQL 行分類ではない）。**よって v1 は SQL=正規表現を維持**し、tree-sitter Oracle/PL-SQL 化は §14 の条件付き将来候補とする。
- → PRDメモ「sootやtree-sitterも有効活用できないか」への回答: **tree-sitter採用（Java/C/Pro\*C基盤）／soot不採用**。

---

## 13. リスクと未決事項

| # | 重大度 | 項目 | 対応 |
|---|---|---|---|
| R1 | High | 必須依存の cp312・対象アーキ wheel 入手性／py-tree-sitter 0.x 破壊変更 | §4.2 G1で実証。完全版ピン＋ロード方式固定、ABI整合をスモーク |
| R2 | High | 多ホップ偽陽性（汎用getter等）／停止性／決定的degrade | §8.3 型解決依存getter/setterは不動点非投入（構造的抑止）＋静的採否＋決定的切り捨て、§8.1停止性論証、§8.4 全件diagnostics |
| R3 | Medium | 60GB実時間／Aho-Corasick＋来歴グラフのメモリ | §8.2 差分走査の限定効果明記＋来歴グラフをmemory-limit対象。`tests/perf/` 実測 |
| R4 | Medium | 型解決不能 getter 等の残存偽陽性 | §8.4 明示・confidence=low。handcrafted監視 |
| R5 | Medium | Pro\*C 前処理の取りこぼし・行番号ズレ | §7 行番号保存を確定。スコープ外分は §8.4。golden に Pro\*C＋行番号ケース |
| R6 | **High** | ターゲットOS/アーキ未確定（§2.1要確定欄） | **§4.2 G1 のブロッキング前提（未充足なら writing-plans 不可・§15 フェーズ0）** |

---

## 14. 今後（v2+）

- 残り言語（Kotlin / PL/SQL / TS・JS / Python / Perl / C#・VB.NET / Groovy）を §5.2 プラグイン経由で追加。
- Shell を tree-sitter-bash 化（任意）。
- **tree-sitter Oracle/PL-SQL grammar 採用**（SQL 分類 medium→high・§8.1 複数行 PL/SQL 抽出精度向上）。**前提条件: §4.2 G1 相当の検証で、py-tree-sitter ピン版（0.21系）ABI と整合する Oracle/PL-SQL grammar の cp312・対象 manylinux prebuilt wheel がオフライン取得可能であること**。不可なら sdist ビルド可否を §3/§4.2 と合わせ意思決定（§12 の再評価を参照）。
- **「プロジェクト頻出トップN」動的ストップリスト**（v1静的のみ。動的化は事前走査の決定的母数定義とともに v2+）。
- キーワード内チェックポイント（再開粒度の精緻化）。
- **opt-in RFC4180 セル内改行出力（v8 検討・条件付き将来候補）**: Excel でセル内改行を厳密に得たい場合の別出力モード。**前提**: タブ区切り＋クオートは Excel 版／ロケール依存で不安定なため CSV（カンマ）限定とし、§9「タブ/改行サニタイズ」前提と `output_writer._blob_from_data_rows`（書込＝完了判定共有の正規化終端）／`_rows_from_part_text`／`data_sha256`／`--resume` 完了判定の決定性コアを RFC4180 対応へ作り替える別計画を要する（このとき v9 のサニタイズ拡張・区切りエスケープの逆変換も実装）。v1 は ` \n ` 連結（生改行ゼロ・全 codec round-trip）を維持＝決定性コア不変（§9 snippet 切り出し規則・サニタイズ規約）。

---

## 15. 実装フェーズ分割（writing-plans の前提）

単一実装計画は非現実的。次のフェーズ順で計画する（決定性基盤を間接追跡より先に固める）:

- **フェーズ0（ゲート・着手前提）**: §4.2 G1 充足（wheel 実証・対象アーキ/libc確定）。本フェーズ未通過なら以降着手不可。
- **フェーズ1（決定的コア）**: Ingest / grep行パース / 文字コード / 言語ディスパッチ / 分類器（tree-sitter, Pro\*C行番号保存）/ TSVスキーマ / golden 基盤。**multiホップなし・direct のみで完全決定性と golden を先に確立**。
- **フェーズ1.5（決定的コアの方言精密化・v7 追加）**: §5.1 シェバン検出（拡張子なし判別）＋`.csh`/`.tcsh`、§7 SQL=Oracle 方言精密化・Shell の bourne/cshell 二方言、§8.1 用の Oracle/csh 追跡シンボル抽出規則、対応 golden の決定的拡張。**direct のみ・完全決定性を維持**したまま、Phase 2 の追跡正しさ前提（Oracle/csh 代入抽出）を確立。Phase 2 とは別計画。
- **フェーズ2（不動点エンジン）**: §8.1 反復＋§8.3 採否＋§8.2 来歴集約/性能/degrade。フェーズ1（＋1.5）の決定性基盤上で偽陽性抑止・停止性を実測検証。chain複数経路の決定性を golden で固定。**着手前提: §4.1 `pyahocorasick` の §4.2 G1 相当 wheel 実証（Phase 1 ゲートで未検証＝`phase0-gate-result.md` 申し送り）**。
- **フェーズ3（規模・運用）**: 60GB perf ベースライン、`--resume` 原子性、diagnostics 集約、規模分割。
- **フェーズ4（v8/v9 出力可読性改訂・Phase3 完了後の意図的破壊的スキーマ変更）**: §9 の3改訂（`file` 絶対化／direct→indirect chain 集約ソート／構文単位・複数行 snippet）を実装する独立計画。**本フェーズ4 は writing-plans の入力（計画対象）であり、golden 再生成・Inv-1 再確立は writing-plans の前提ではなく成果物**（着手循環の回避・v9 訂正 I-3'）。着手前提はフェーズ1〜3 完了済（本リポジトリは充足）のみ。**Inv-1 再ベースライン手順（必須・正本。changelog/§10.3/§11 はここを参照）**:
  1. **凍結対象の参照（v9 訂正 C-2'）**: 再ベースライン前の基準は `docs/superpowers/plans/phase0-gate-result.md` の **Inv-1 記録節そのもの（L312-316 の「Inv-1〜4 充足の明記」および L385-389 の Inv 表 Inv-1 行）を行番号参照で凍結**する（同文書は本文に「既存 130」L314 と「既存 167」L387 を併記し、167 は `pytest -q → 167 passed` のテスト件数＝バイト数ではない。よって spec 側で byte 数値を**再記述しない**。凍結＝当該節を書き換えず v8/v9 再ベースラインの注記のみ追記）。基準の本質は「Phase3 完了時（v7 スキーマ）に既定経路で golden 14 が byte-identical だった事実」。
  2. コード改修: `model.py:sort_key` を §9 新キーへ差替／`tsv._sanitize` 対象集合拡張／`file` 解決（`Path(source_root).resolve()` 起動時1回）／snippet 切り出し（§9・§7）／`output_writer._data_line`・連結を ` \n ` 仕様へ。
  3. `tests/golden/test_golden.py` に §11 の比較機構（`{SOURCE_ROOT}` 逆置換＋ケース manifest `encoding` で読戻し＋resume 系は `is_complete()==True` も assert）を追加。
  4. **影響3範囲を分離して expected を再生成しレビュー承認**: 〔A: `file` 絶対化＝**全 golden** の `file` 列を `{SOURCE_ROOT}/<relpath>` へ〕〔B: snippet 多行化＝snippet 列を含む全 golden/unit/integration expected（例 `getter_no_expand` の複数行 `field_declaration` 等。**フェーズ4 計画の最初のタスクで対象 expected ファイルを実在 grep し churn 範囲を事前確定**）〕〔C: ソート順変化＝**indirect 行を含む 6 件のうち chain 集約で行順が変わるもの**（`chain_multipath` 等。`shell_direct`/`getter_no_expand`/`indirect_constant` 等は行順不変だが A/B で byte は変わる）。**正確な内訳は再生成 diff（実コード実行結果）で確定し、3要因別にレビュー承認する**（spec は件数を断定せず diff を正本とする）〕。
  5. v8/v9 後の Inv-1 を**新ベースライン**として再確立、`tests/perf`／`budget._ITEMS_PER_MB` を一度だけ再測定（非ゲート）。
  - フェーズ1.5/2 の Oracle/csh・chain 機構への依存は「再生成対象 golden にそれらのケースが含まれる」事実の記述に留め、着手前提には**加えない**（B/C の再生成でカバーされる）。

理由: フェーズ1で「direct のみで完全決定的」を確立する前に多ホップを実装すると、chain/採否/並列集約の非決定性が golden を破壊し続け、writing-tests.md の「大量churn＝構造を疑う」状態に恒常的に陥るため。フェーズ1.5 を Phase 2 の前段に独立させるのも同じ理由 — Oracle/csh の代入抽出（§8.1 の追跡入力）が誤ったまま多ホップを実装すると、Phase 2 の追跡 golden が誤りを恒久固定してしまうため、決定的コアの方言正しさを多ホップ前に確定する。**フェーズ4 の golden 全件再生成は「churn＝構造を疑う」原則の違反ではない**: 同原則が禁ずるのは「非決定性に起因し原因不明のまま繰り返す churn」であり、フェーズ4 は §9 スキーマの**意図的・一回限り・差分が事前に説明可能（file 絶対化／ソート順／snippet 多行化の3要因に分離してレビュー承認）**な再生成である。決定性自体は維持（再生成後も `--jobs` 並列・走査順非依存で byte 安定）し、再生成は新ベースラインの確立であって不安定性の放置ではない。
