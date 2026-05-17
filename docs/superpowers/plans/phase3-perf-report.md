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
