# golden ケース characterization 注記（2026-05-24 追加分）

設計: `docs/superpowers/specs/2026-05-24-golden-realism-robustness-design.md`。
期待値は `pipeline.run` の実出力を人手レビュー後に凍結（案A：特性化）。再生成は

```bash
python scripts/gen_golden_case.py tests/golden/cases/<case> [--with-diag-summary]
```

判定 rubric: **R1** spec の normative 違反＝実害バグ（凍結しない）／**R2** spec 明示外だが intent 違反＝設計判断（本回は §9 拡張で修正）／**R3** spec にも intent にも反しない（chardet アーティファクト等）＝現挙動を凍結し注記。

| ケース | 懸念 | 固定する挙動 | rubric / 注記 |
|---|---|---|---|
| `grep_binary_nul` | ③ | grep 本文の生バイト/NUL でも rc=0・正常 hit のみ・コロン無し行は `bad_grep_line`。`path:lineno:` 構造を持つ行は content にバイトを含んでも parse 成功（hit 化）し、snippet は実ソースから再構築される | `diagnostics_summary.txt` あり |
| `grep_jar_artifact` | ③ | src 内 jar を `walk_skipped_binary` で除外・`Binary file … matches` 行を `bad_grep_line` 化。正常 hit のみ TSV 化（Main.java:2 のコメント行は `コメント/low`） | `diagnostics_summary.txt` あり。jar は `scripts` 内 zipfile で `date_time` 固定の決定的バイト列。`.gitattributes` で `binary` 指定 |
| `encoding_mixed_tree` | ② | 1 ツリーに UTF-8/CP932/EUC-JP 同居・`encoding` 列がファイル毎に出る（snippet も各ファイル単位で正しく日本語復号される） | **R3**: `encoding` 名は `chardet==5.2.0` のアーティファクト。本セットでは UTF-8→`utf-8`／CP932→**`shift_jis`**／EUC-JP→`euc-jp` で凍結。CP932 は内容次第で `cp932`/`shift_jis` 等に揺れるため決め打ちせず実出力を凍結。`requirements.lock` の chardet 版変更時は本ケースを再生成すること |
| `bom_crlf_source` | ② | 先頭 BOM が行番号を壊さない（`decode_bytes` は `utf-8` 復号で U+FEFF はテキスト先頭に残るが改行を増やさない）・CR は除去でなく空白化される | R3: CR は「除去」でなく空白化（snippet 末尾に空白が付き得る）。`encoding` 列は `utf-8` |
| `messy_c_legacy` | ① | 乱雑 C（タブ/深ネスト/多文1行/コメントアウト/ブロックコメント）の分類と snippet サニタイズ（タブ→空白）。本セットの分類: 1=コメント・3=比較・4=宣言・7=コメント（コメント行 1,7 は `コメント/low`） | R3: 分類は現挙動を凍結。コメント行は §コメントカテゴリ(2026-05-24)で `コメント/low` |
| `source_ctrl_chars` | ①/③ | ソース行の NUL/C0/DEL が空白化され生バイトが TSV に残らない。NUL/C0/DEL は ≤U+007F で valid UTF-8 ゆえ `encoding`=`utf-8`（置換なし）。ソースは `walk_skipped_binary` だが direct hit は処理される | **R2→修正済**: §9 サニタイズ拡張の回帰テスト（spec §9 を 2026-05-24 改訂） |
| `sql_comment` | コメント | SQL の `--` コメント行を `コメント/low`、コード行（WHERE 比較）を `比較/medium` に固定（正規表現系コメント分類の end-to-end） | コメントカテゴリ(2026-05-24)。spec §9/§8.3 参照 |

注: `diagnostics_summary.txt` を持つケースのみ、ハーネスが `diagnostics.txt` の `# summary` ブロック（カテゴリ＋件数）を opt-in 比較する（spec §11）。
