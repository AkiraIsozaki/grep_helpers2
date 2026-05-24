# Phase 3 perf レポート（2026-05-17）

## 計測環境

- Python 3.12.13
- arch: x86_64
- kernel: 6.17.0-29-generic (Linux)
- pytest 9.0.3
- corpus_gen: seed=7, n_files=600（`tests/perf/corpus_gen.py`）

---

## PERF スケール計測（`test_scale`）

corpus_gen seed=1 の合成ソース木を n=200/400/800 ファイルで実行。

```
PERF n=200 dt=0.095s rss_kb=38240
PERF n=400 dt=0.209s rss_kb=38496
PERF n=800 dt=0.547s rss_kb=39392
```

### スケール特性

| n    | dt (s) | rss_kb |
|------|--------|--------|
| 200  | 0.095  | 38240  |
| 400  | 0.209  | 38496  |
| 800  | 0.547  | 39392  |

- **時間スケーリング**: n=200→400 で×2.2、n=400→800 で×2.6。ほぼ線形 O(n)。
  ソース木走査はファイル数 n に比例するため、単一 grep キーワード・max_depth 制限下では
  O(n) に近い挙動を示す（多ホップ連鎖が発生する場合は O(n×depth) になりうるが
  本コーパスでは depth は 1〜2 ホップ程度）。
- **メモリスケーリング**: rss_kb はほぼ一定（38240→39392）。ファイル数増加に対して
  メモリはほぼ O(1)（チャンクストリーミング処理＋スピル機能により定常メモリ）。

**O() 推定**: `T(n) ≈ O(n)`、`M(n) ≈ O(1)`

---

## CALIB 較正計測（`test_calibrate_items_per_mb`）

corpus_gen seed=7, n_files=600、`--memory-limit 100000`（budget 経路有効化・degrade 非発火）。
grep 入力は `pkg0/C0.java:1:<実ファイル行>` 形式（実行コンテキストで extract_chase_symbols が
シンボルを抽出できるよう実ファイル行をスニペットとして使用）。

```
CALIB peak_bytes=1612149 max_items=200000 bytes_per_item=8.1 ITEMS_PER_MB=130084
```

### 較正式

```
bytes_per_item = peak_bytes / max_items
             = 1612149 / 200000
             = 8.060745...

items_per_mb  = floor(1_048_576 / max(1.0, bytes_per_item))
             = floor(1_048_576 / 8.060745...)
             = 130084 (整数)
```

注: `CALIB` 行が出力する `bytes_per_item=8.1` はテストの `f"bytes_per_item={bytes_per_item:.1f}"` による
表示丸め（小数点以下1桁）であり、コードは丸め前の浮動小数点値をそのまま使用する。
丸め後の `8.1` で再計算すると `floor(1_048_576 / 8.1) = 129453` となり実際の採用値と一致しない。
権威ある入力は `peak_bytes=1612149`・`max_items=200000` の2値であり、`8.1` は表示専用の値。

`tracemalloc.get_traced_memory()` のピーク値（peak）を使用。
`estimate_items` スパイは 21 回呼ばれ（`seen` 非空確認済み）、max(seen) = 200000 を
`max_items` として採用。この `max_items=200000` は corpus の実追跡シンボル数ではなく、
最初の `_apply_global_cap` 呼出における
`estimate_items(n_symbols=max_symbols, n_edges=0, n_intro=max_symbols)` の結果
（`max_symbols=100000` 既定 → 100000+0+100000=200000）であり、
シンボルキャップに由来する較正基準点である。

### 採用値

```
# src/grep_analyzer/budget.py:9
_ITEMS_PER_MB = 130084   # (較正前: 4096)
```

---

## Inv-1 能動ガード確認

較正後（`_ITEMS_PER_MB = 130084`）の `test_既定出力は_items_per_mb値に不感` PASS:

- 既定経路は `budget.unlimited=True`（`--memory-limit` 未指定）→ `estimate_items` 一切非呼出
- `_ITEMS_PER_MB` を極値（1, 10^9）に monkeypatch しても出力 sha256 が変わらない
- golden 14 tests も byte-identical = PASS

---

## 注記

- `test_scale` の grep 入力スニペットは最小形式（`S0`）のため fixedpoint 追跡なし→
  純粋なウォーク+スキャン性能を計測。
- `test_calibrate_items_per_mb` は実ファイル行スニペットで fixedpoint 追跡を起動し
  budget 経路（`if not budget.unlimited`）を確実に踏むよう設計。
- `_ITEMS_PER_MB` は degrade 発火の決定的トリガ定数であり、実バイト厳密性は求めない。
  本較正値はこの環境での実測に基づく。

---

## Phase4 再較正証跡（spec §15・2026-05-18）

snippet 多行化（`build_snippet`／spec v9 §9）で 1 レコード最大バイトが増大し
過小評価となるため、既存と同一手順（`test_calibrate_items_per_mb` を **単体実行**・
corpus_gen seed=7 n_files=600・`--memory-limit 100000`）で再較正。`max_items=200000`
はシンボルキャップ由来の不変基準点（`100000+0+100000`）で snippet 非依存。変数は
`tracemalloc` peak。単体実行で 12 回計測し安定（`peak_bytes` ≈ 2,831K–2,834K・
`ITEMS_PER_MB` ≈ 74,002–74,155）、中央値採用:

```
CALIB peak_bytes=2832276 max_items=200000 bytes_per_item=14.2 ITEMS_PER_MB=74044
```

```
bytes_per_item = 2832276 / 200000 = 14.161380
items_per_mb   = floor(1_048_576 / 14.161380) = 74044
```

採用値（`src/grep_analyzer/budget.py:9`）: `_ITEMS_PER_MB = 74044`（旧 130084）。
過小評価是正＝より早期かつ実バイト整合的に degrade トリガ。Inv-1 非ゲート影響なし
（既定経路は `budget.unlimited=True` で `estimate_items` 非呼出・`_ITEMS_PER_MB`
不感を `tests/integration/test_inv1_items_per_mb.py` が再ベースライン後も PASS で機械保証）。
注: フル perf スイート同時実行時は他テストが `tracemalloc` 基線へ影響し peak が
小さく出るため、報告書の手順どおり**単体実行の CALIB 行**を権威値とする。

---

## 不動点パス改善（2026-05-24・lazy parse / hop間 LRU / rg既定 / pool再利用 / direct cache）

適用変更（`docs/superpowers/plans/2026-05-24-perf-fixedpoint-caching.md`）:

- **#2** `_scan_one` の tree-sitter parse を symbol ヒットまで遅延（非マッチ多数ファイルのパース排除）。
- **#1** 不動点 hop 間の復号メタ（text/enc/lang/dialect）を 64MiB 予算つき LRU でキャッシュ
  （再読込・再 chardet・再言語判定を排除。tree 非保持で常駐メモリ O(1) 維持）。
- **#6** direct パスの `is_file`/物理行分割を relpath 単位にキャッシュ（高ヒット密度の毎ヒット stat/再 split を 1 回化）。
- **#5** `multiprocessing.Pool` を run 単位で 1 度だけ生成し hop/chunk 間で再利用
  （automaton は worker 側で signature 変化時のみ再構築・worker LRU 永続化）。
- **#3** ripgrep prefilter を `rg` 検出時の既定 ON に（`--no-use-ripgrep` で opt-out）。

### 測定（test_fixedpoint_heavy 相当・seed=7・実ファイル行 seed・jobs=1）

同一セッションで連続 A/B/C 計測（各 warmup 後 3 回 min）。**注: 出力 byte 不変は golden
全件＋`test_perf_caching` が機械保証。本表は速度のみ。** devcontainer はノイズが大きいため
単発 pytest 値ではなく back-to-back min を権威とする。

| 構成 | n=300 | n=600 |
|------|-------|-------|
| A: 改善前（commit 1ebcb92・rg OFF） | 1.138s | 1.914s |
| B: 改善後 既定（rg ON） | 0.585s | 1.128s |
| C: 改善後 rg OFF | 0.452s | 1.007s |

- **A→B（既定どうし）**: n=300 ≈ **1.95×**、n=600 ≈ **1.70×** 高速化。
- **B vs C（rg の寄与）**: 本合成コーパスでは **rg ON が OFF より遅い**（n=600 で +12%）。
  理由: tiny ファイルが密に相互参照するため hop ごとに rg がほぼ全ファイルを keep し、
  絞り込み効果なしに per-hop サブプロセス起動コストだけ乗る（rg 病理的コーパス）。
  実コードベース（大きめファイル・疎な参照・初期 hop で symbol 集合が小）では rg が効く想定。
  **#3 の既定 ON はワークロード依存**であり、密小ファイル系では `--no-use-ripgrep` 推奨。
- 速度向上の主因は **#1（LRU）+ #2（lazy parse）**。メモリは rss ほぼ一定（O(1) 維持）。
