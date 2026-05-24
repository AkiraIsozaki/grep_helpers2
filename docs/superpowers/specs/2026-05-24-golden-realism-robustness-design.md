# golden セット 現実性・堅牢性 補強 設計

- 日付: 2026-05-24
- ステータス: ドラフト（ブレインストーミング合意済 → 3 視点 批判的 AI レビュー反映済 → ユーザー spec レビュー前）
- 関連: 本体 spec `2026-05-16-grep-analyzer-design.md` §9（サニタイズ規約＝改修対象）、§11（golden 比較機構＝正本・改修対象）、§10.1（復号フォールバック）、§10.3（diagnostics）

## 0. 改訂履歴

- v1: ブレインストーミング合意（6 ケース＋opt-in diagnostics 完全一致＋.gitattributes）。
- **v2（本版）: 3 視点の批判的 AI レビューを実コード検証付きで反映**。主な変更:
  - 【Critical】#3 の `encoding` 列を「cp932/euc-jp」と決め打ちしない（chardet 検出アーティファクトで `shift_jis` 等に揺れる＝実証）。#3 は分類が ASCII signal で頑健な **SQL 限定**へ。
  - 【Critical】案A の「実害バグ vs 仕様」判定 rubric を明文化（§3）。実測で確定した「ソース行の生 NUL/C0 制御が `sanitize_field` を素通りして出力 TSV セルに残る」件を、**ユーザー判断によりスコープ内で §9 サニタイズ拡張して修正**（§7）。
  - 【Important】diagnostics 比較を完全一致 → **`# summary` ブロック（カテゴリ＋件数）限定**へ（脆さ低減・§5）。
  - 【Important】`.gitattributes` を `tests/golden/cases/** -text` ＋ jar `binary` へ拡張（expected/*.tsv の BOM・diagnostics も保護・§6）。
  - 【Important】`messy_long_line` を**削除**（`tests/unit/test_snippet.py` で担保済）。空いた枠を `source_ctrl_chars`（§7 改修の回帰テスト）へ振替。
  - 【Minor】事実誤り訂正: 既存ケースは **39**（38 ではない）。`#4` は「CR 除去」でなく「CR→空白化」。§1.2 表の NUL 行記述を訂正。

## 1. 背景

ユーザーから `docs/ref/golden` に「golden になりそうな例」が提示され、(a) 採用可否、(b) 現行 golden への 3 つの懸念（お上品すぎ／文字コード混在／バイナリ混入で落ちないか）について検討依頼があった。

### 1.1 `docs/ref/golden` の採用可否 — ファイル流用は不可

| 観点 | `docs/ref/golden`（新候補） | 現行 `tests/golden/cases`（正） |
|---|---|---|
| 依存ツール | `analyze*.py` / `scripts/measure_kpi.py` / `LANG_SPECS`（**現コードに存在しない**＝旧 KPI 設計の遺物） | `grep_analyzer.pipeline.run`（現行） |
| ディレクトリ | `<lang>/inputs/`（複数形） | `cases/<case>/input/`（単数形） |
| TSV スキーマ | 9 列・日本語ヘッダ・CSV クオート | 13 列・英語ヘッダ・TSV |
| 対応言語 | kotlin / dotnet(C#/VB) を含む | kotlin/dotnet **分類器なし**（java,c,py,js,ts,perl,groovy,shell,sql のみ） |

→ `expected/` も `src/` もそのままは使えない。発想（使用タイプ×ファイルのカバレッジ行列、Pro\*C の EXEC SQL モデル化、getter/setter 間接連鎖）は参考になるが、その多くは現行 cases に既存（`getter_no_expand` / `indirect_constant` / `chain_multipath` / `proc_exec_sql_chase` 等）。**結論: ファイル単位の採用はせず、発想のみ参考にする。`docs/ref/golden` は参照資料として現状維持（削除しない）。**

### 1.2 3 懸念の実地検証結果（本設計の根拠）

一時ケースで `pipeline.run` を実行し現挙動を確認した（すべて `rc=0`＝落ちない）:

| 試験 | 結果 |
|---|---|
| grep 本文の**コロン無し**バイナリ行（NUL/`\xff`） | `rc=0`、`bad_grep_line` 診断へ。なお `path:lineno:` 構造を持つ行は content に生バイトを含んでも parse 成功し hit 化される（落ちない） |
| ソースがバイナリ（grep が指す） | `rc=0`、`walk_skipped_binary`＋direct hit は復号置換（`encoding=…要確認`）で継続 |
| 混在エンコーディングツリー（utf-8/cp932/euc-jp） | `rc=0`、復号はファイル単位。ただし**短い非 UTF-8 ファイルは chardet が誤検出**し `encoding`/`snippet` が化ける場合がある（§4 #3 参照） |
| 本物 jar を src 配置＋`Binary file <path> matches` 行を grep に混入 | `rc=0`、TSV は正常 hit のみ、`bad_grep_line`(=Binary file 行)＋`walk_skipped_binary`(=jar) |

堅牢性は設計（`ingest.parse_grep_line` のバイト境界 parse／`encoding.decode_bytes` の無例外フォールバック／`walk` のバイナリ除外）で既に担保。**問題は「それを固定する golden が無い」こと**＝将来のリファクタで静かに壊れ得る。

### 1.3 現行 golden の現実性ギャップ

- **お上品すぎ（懸念①）**: 現行 **39** ケース（`pytest tests/golden` = 39 passed）は極小・潔癖な合成スニペット（例 `c_direct/src/m.c` は 2 行）。乱雑な実コードを表現していない。`docs/ref/golden` も同様に潔癖（規模が大きいだけ）。
- **文字コード混在（懸念②）**: 非 ASCII ソースは `encoding_utf8/jp.java`(UTF-8) と `cp932_resume/q.sql`(CP932) の各 1 ファイルが**別ケースに孤立**。1 ツリーに複数 encoding が同居するケースが無い。
- **バイナリ（懸念③）**: NUL を含む fixture が皆無。バイナリ混入は一切テストされていない。さらにレビューで**ソース行の生 NUL/C0 制御文字が出力 TSV セルへ素通りする**現挙動を確認（§7 で対処）。

## 2. 目的とスコープ

### 2.1 目的

3 懸念に対応する新規 golden ケースを**現行ハーネス `tests/golden/cases/` に追加**し、(i) 乱雑な実コード、(ii) 混在エンコーディング、(iii) バイナリ/NUL 混入の各挙動を回帰固定する。狙いは「現状すでに堅牢な挙動」を golden で凍結し、将来のリファクタ耐性を得ること。加えて、レビューで確定した**サニタイズ漏れ（NUL/C0 制御）をスコープ内で修正**し正しい挙動として固定する（§7・ユーザー判断）。

### 2.2 スコープ内の本体変更（最小）

- **§9 サニタイズ集合の拡張**（`tsv._SANITIZE_MAP`）: 全 C0 制御（U+0000–U+001F）＋ DEL（U+007F）＋ C1 制御（U+0080–U+009F）を半角空白へ。既存集合（`\t\r\n\v\f` U+0085 U+2028 U+2029）を**包含**する（U+0085 は C1、`\t\r\n\v\f` は C0 ⊂ 新集合）。
- **ハーネス拡張**（`tests/golden/test_golden.py`）: opt-in の diagnostics summary 比較（§5）。
- **`.gitattributes` 新規**（§6）。
- **本体 spec §9/§11 への normative 反映**（§8）。

### 2.3 スコープ外（YAGNI）

- `docs/ref/golden` のファイル移植・旧 KPI ツールの復活・kotlin/dotnet 等 未対応言語。
- 分類精度の向上（§9 サニタイズ以外のアナライザ機能変更）。レビューで別の実害バグが出た場合のみ別タスク化。
- 既存ユニットで担保済の挙動の golden 重複追加（例: 非 UTF-8 ファイル名は `tests/unit/test_pipeline.py` で担保済 → golden 不要。snippet クランプは `tests/unit/test_snippet.py` で担保済 → `messy_long_line` 不要）。

## 3. 方針 — 案A（特性化＋判定 rubric）

採用方針は **characterization（現挙動を凍結）**。各ケース共通手順:

1. `src/`・`input/*.grep`（バイト単位）を作成。fixture のファイル名は **ASCII 限定**（`os.fsdecode` の surrogate 依存を作らない）。
2. `pipeline.run` を実行。
3. **人手レビュー**で出力（TSV＋該当する diagnostics summary）を確認する。
4. 妥当なら `expected/` に確定（凍結）。
5. レビューで**問題出力**を発見した場合は次の rubric で判定する。

### 3.1 「実害バグ vs 仕様」判定 rubric

- **(R1) spec の normative 規定に違反 → 実害バグ。凍結しない。** 修正タスク化（スコープ内/外は別途判断）。
- **(R2) spec が明示していないが intent（例 §9 の「Excel/TSV で 1 セルを保つ」）に反する → 設計判断事項。** 本設計では §7 のとおり NUL/C0 を**スコープ内で修正**し、正しい挙動を凍結する（ユーザー判断）。今後同種が出た場合は known-issue 記録の上で都度判断。
- **(R3) spec にも intent にも反しない（単に潔癖でないだけ／chardet アーティファクト等）→ 仕様。現挙動を凍結し README に注記。** 例: §4 #3 の chardet 検出名揺れ。

判定は §11 の characterization 注記（集約 README）に根拠とともに記録する。

理由: 今回の目的は堅牢性の回帰固定であり、まず現挙動を凍結するのが最短かつ低リスク。理想値方式（あるべき出力を全面手書きしアナライザを直す）は spec 突き合わせコストが過剰で本目的に不適。rubric により「真の問題」だけを明示的に扱う。

## 4. 追加ケース一覧（6 件）

すべて `tests/golden/cases/<case>/`（既存と同形式: `src/`・`input/*.grep`・`expected/*.tsv`・任意 `opts.json`・本設計で追加する任意 `expected/diagnostics_summary.txt`）。`conftest.py` が `cases/*/` を自動 parametrize するため、ディレクトリ追加だけで pytest に乗る。期待値は**決め打ちせず実 run 出力を凍結**する（特に encoding 列）。

| # | ケース名 | 懸念 | 内容 | 固定する挙動（expected） |
|---|---|---|---|---|
| 1 | `grep_binary_nul` | ③ | 通常テキスト src。grep 本文に **コロン無し**生バイト行（NUL/`\xff`）＋`path:lineno:` 構造を持つが content に生バイトを含む行を混入 | `rc=0`、正常 hit は TSV 化、コロン無し行は `bad_grep_line`。**grep 文字列内バイトの parse 非クラッシュ**を固定（summary-diag） |
| 2 | `grep_jar_artifact` | ③ | `src/lib/app.jar`（本物の小 jar）＋通常 Java。grep ダンプに正常 hit＋`Binary file lib/app.jar matches` 行 | `rc=0`、TSV は正常 hit のみ、`bad_grep_line`(Binary file 行)＋`walk_skipped_binary`(jar)（summary-diag）。**ディスク上のバイナリ資産の現実シナリオ**（ユーザー要望） |
| 3 | `encoding_mixed_tree` | ② | **SQL** ファイルを UTF-8/CP932/EUC-JP で同一ツリーに配置。各々の文字コードの grep（`grep -rn` 相当の混在 grep） | `encoding` 列が**ファイル毎に出る（実 run 値を凍結。chardet 検出名は `shift_jis` 等に揺れ得るため決め打ちしない）**。分類は ASCII signal（`WHERE`/`=` 等）で頑健＝化けに影響されないことを固定。README に「encoding 名は chardet アーティファクト」と注記 |
| 4 | `bom_crlf_source` | ② | 先頭 BOM（＋CRLF 改行）の source（Windows 編集された旧資産想定） | BOM が行番号を壊さない（`decode_bytes` は `utf-8` 復号で BOM は U+FEFF として残るが改行を増やさない）。**CR は除去でなく空白化**される現挙動、line1 ヒット時の snippet 先頭 U+FEFF 残留を含め、実 run 出力を凍結 |
| 5 | `messy_c_legacy` | ① | 汚い C: タブ/空白混在インデント・行末空白・深ネスト・KW 入りコメントアウト・`a=1; b=CODE; c=2;` 多文 1 行・ブロックコメント | 乱雑入力の分類（条件判定/代入/その他）と snippet サニタイズ（タブ→空白）を固定 |
| 6 | `source_ctrl_chars` | ①/③ | grep が指すソース行に NUL・各種 C0 制御・`\t\v\f\r`・DEL を埋込（バイナリ片がソースに混入した旧資産想定） | §7 改修後、**全制御文字が空白へ正規化**され出力 TSV に生バイトが残らないことを固定（§7 サニタイズ拡張の回帰テスト） |

補足:

- **#3** は「日本語等で grep すると混在エンコーディングの grep ファイルが生まれる」旧資産移行の実シナリオを再現する。`encoding` 列はソース毎に `decode_bytes(target)` の結果が出る（grep ファイル側の単一 encoding 判定とは独立）。SQL に限定するのは、category/confidence が `content`（混在ファイルの単一 grep_enc 復号）に依存し、Perl/groovy/shell では非 ASCII signal が mojibake で分類を変え得るため。SQL は ASCII signal で頑健。
- **#1, #2** のみ `expected/diagnostics_summary.txt` を併設（§5）。
- **#2** の jar は §6 の `.gitattributes` で `binary` 明示。jar 内容と `Binary file …` 行は手書き固定のため、jar のバイト（zip タイムスタンプ等で可変）に依存せず expected は安定。jar は先頭 8192 バイトに NUL を含む（zip ヘッダのゼロ値フィールド）ため `walk` のバイナリ判定（`b"\x00" in head`）に確実に掛かる。
- **#6** は §7 のサニタイズ拡張により出力が clean ASCII（制御文字→空白）になるため、expected に生バイトは載らない。

## 5. ハーネス拡張 — opt-in diagnostics summary 比較

現行 `test_golden.py` は TSV 完全一致のみ。バイナリ系の主眼（`bad_grep_line` / `walk_skipped_binary`）は diagnostics にしか現れないが、**detail の完全一致は脆い**（detail に `repr(raw_line)` を焼き込み、`detail_limit`（既定 1000）件数依存、書込 `backslashreplace`/読込差）。そこで **`# summary` ブロック（カテゴリ＋件数）限定**で比較する。`expected/diagnostics_summary.txt` が存在するケースのみ:

```python
exp_sum = golden_case / "expected" / "diagnostics_summary.txt"
if exp_sum.is_file():
    actual = (out / "diagnostics.txt").read_text("utf-8")
    lines, in_sum = [], False
    for ln in actual.splitlines():
        if ln == "# summary":
            in_sum = True; continue
        if ln == "# detail":
            break
        if in_sum:
            lines.append(ln)
    actual_sum = "\n".join(lines) + "\n"
    assert actual_sum == exp_sum.read_text("utf-8"), "diagnostics_summary"
```

- `diagnostics.render`（§10.3）の summary はカテゴリ昇順ソートで**決定的**。summary は件数のみで `repr`・path・detail_limit に非依存＝脆さが小さい。
- summary 行に絶対パスは出ない（diagnostics は全て relpath/symbol/件数）。`{SOURCE_ROOT}` 逆置換は不要。
- `expected/diagnostics_summary.txt` が**存在するケースのみ**比較する opt-in。既存 39 ケースは不在ゆえ無影響。
- fixture 名は ASCII 限定のため、diagnostics の `backslashreplace` 書込／`utf-8` 読込の非対称は顕在化しない。

## 6. git の特殊ファイル保護 — `.gitattributes`（新規・リポジトリ直下）

golden は**バイト完全一致**の資産であり eol 正規化を一切受けてはならない。`expected/*.tsv`（UTF-8 BOM＋LF）・`diagnostics_summary.txt`・混在エンコーディング/CRLF/BOM/バイナリの src・grep をまとめて保護する:

```
tests/golden/cases/**                                 -text
tests/golden/cases/grep_jar_artifact/src/lib/app.jar  binary
```

- `-text`（golden 全体）: eol 自動変換を抑止し、`core.autocrlf=true` 環境でも expected TSV が CRLF 化されず `utf-8-sig` 比較が崩れない（既存 39 ケースの BOM 付き expected も同時に保護される）。
- `binary`（jar）: `-text -diff` の短縮。zip バイナリの差分表示・正規化を抑止。

現状ソロ運用・`core.autocrlf` 無効でも往復するが、将来の環境差・正規化事故への防御。

## 7. §9 サニタイズ拡張（NUL/C0/C1/DEL → 空白）

レビューで確定: 現 `sanitize_field`（`src/grep_analyzer/tsv.py`、唯一のサニタイズ集約点。snippet 含む全セルが output_writer 経由でここを通る）は `_SANITIZE_MAP = {\t,\r,\n,\v,\f,U+0085,U+2028,U+2029}` のみを空白化し、**NUL/その他 C0 制御は素通り**。結果、ソース行に生 NUL があると出力 TSV セルに生 `\x00` が残る（spec §9 の「1 セルを保つ」intent に反する＝rubric R2）。ユーザー判断によりスコープ内で修正する。

- 改修: `_SANITIZE_MAP` を**全制御文字（C0 U+0000–U+001F／DEL U+007F／C1 U+0080–U+009F）＋ U+2028 ＋ U+2029**を空白化する集合へ拡張。これは現集合を包含する（後方互換）。
- 決定性: 「決定性アルゴリズムは不変・対象文字集合のみ拡張」（spec §9 規約③の既定路線と同じ性質）。`split("\n")`/`data_sha256` の決定性コアは不変。
- 回帰影響: 既存 39 ケースは C0/C1 制御を含まない（`sanitize_ctrl` の TAB は旧集合で既に空白化済）ため expected は**バイト不変**（§9 検証で確認）。
- 注意: latin-1 フォールバックで decode された 0x80–0x9F バイトは U+0080–U+009F（C1）となり空白化される。正規に decode されたテキストにこの範囲が content として現れることは実質ない（安全）。

## 8. 本体 spec への反映

memory「確定設計は spec が正本」に従い、`2026-05-16-grep-analyzer-design.md` に normative 追記:

- **§9（サニタイズ規約①）**: 空白化対象を「行/改ページ分割クラスの明示列挙」から「全制御文字（C0/DEL/C1）＋ U+2028 ＋ U+2029」へ拡張。現列挙を包含する旨を明記。
- **§11（golden 比較機構）**: 「`expected/diagnostics_summary.txt` 存在時は、生成 `diagnostics.txt` の `# summary` ブロック（カテゴリ＋件数）のみを完全一致比較する（opt-in。不在ケースは TSV のみ＝現行不変）。detail は決定的だが脆さ回避のため比較対象外」を追記。

## 9. 検証

- `pytest tests/golden -q` で **既存 39 ＋新規 6 = 45 全 green**。
- `pytest tests/unit -q`（または全体）で §7 改修の回帰なしを確認。
- 既存 39 ケースの expected が**バイト不変**（§7 サニタイズ拡張後も差分ゼロ）であることを `git diff --stat` で確認。
- 新規 6 ケースの `expected/`（TSV＋該当 summary）は §3 の人手レビューを経て凍結したものであること。
- **chardet 依存の明示**: `encoding` 列は `chardet==5.2.0`（`requirements.lock` ハッシュ pin）の検出結果に依存し決定的。lock 変更時は #3/#4 の expected 再確認を必須とする旨を §11 集約 README に記す。

## 10. characterization 注記の置き場所

per-case README は既存 39 ケースと非対称になり保守 negative（レビュー指摘）。代わりに **`tests/golden/cases/README.md`（集約・新規）** に、新規 6 ケースが「何を固定しているか」「rubric 判定（R1/R2/R3）と根拠」「chardet 依存の注記」をまとめて記す。

## 11. 想定する作業順序（writing-plans へ引き継ぐ素案）

1. §7 サニタイズ拡張（TDD）＋ §5 ハーネス拡張＋ §6 `.gitattributes`。既存 39 が green・バイト不変のまま＝無影響を確認。
2. ケースを 1 件ずつ作成→`run`→人手レビュー（rubric 適用）→凍結。順序は `③→②→①`（堅牢性が最優先目的）。
3. 本体 spec §9/§11 反映（§8）、集約 README（§10）。
4. 全体検証（§9）。
