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

- **キャッシュ系の寄与（A→C・どちらも rg OFF）が本命**: n=300 で 1.138→0.452＝**約 2.5×**、
  n=600 で 1.914→1.007＝**約 1.9×**。主因は **#1（LRU）+ #2（lazy parse）**。これは実測値。
- **A→B（既定どうし）**: n=300 ≈ **1.95×**、n=600 ≈ **1.70×**。
- **rg の寄与（B vs C）**: 本合成コーパスでは rg ON が OFF より **遅い**（n≈1.2–1.3×）。
  ただし当初の見立て「rg がほぼ全ファイルを keep し非選択的」は **誤り**で、prefilter を
  instrument すると実際の keep は **各 hop で 1〜17%**（hop1=6/300, hop2=50/300, hop3=37/300,
  hop4–6=3〜4/300）と **高選択的**。遅い真因は合成ファイルが約 50 バイトと極小で、
  300 ファイルを in-process 走査する方が rg のサブプロセス（fork/exec＋全木走査＋IPC）より
  安いため。**当時は「実コードでは純益＝既定ON妥当」と仮説したが、後日 /usr/include で
  実測して棄却した**（下記「#3 …実測 → 既定OFF」節。中規模実コードで利得ゼロ）。
  選択度ベースの適応ゲートは試作したが、選択度は元々良好で真因がファイルサイズのため
  無効と判明し撤去した（複雑性のみ増す）。
- メモリは rss ほぼ一定。`jobs=1` は単一 LRU（≤64MiB）、`jobs>1` は worker ごとに予算を
  jobs 分割するため合計常駐は単一 run と同オーダー（O(1) 維持）。

---

## #3 rg 既定ON の実コードベース実測 → 既定OFF（opt-in）へ撤回（2026-05-24）

当初 #3 で「rg は実コードでは効くはず」と仮説のまま既定ONにしていたが、実コードで実測し撤回した。

### 計測（実C・通常サイズのファイル）

| シナリオ | 結果 |
|----------|------|
| /usr/include/linux（763 ファイル・median 5.5KB・約5MB ≤ 64MB LRU）max_depth=2 | **rg-OFF=11.16s / rg-ON=10.92s ＝ 1.02×（利得なし）**・byte 一致 ✓ |
| full /usr/include（5,804 ファイル・**86MB > 64MB LRU**）max_depth=2 | 両モードともマッチ集合の tree-sitter パースが支配的で **>900s** 測定不能（パース律速） |
| 合成・密集 tiny ファイル（既出） | **rg 約1.2–1.3× 遅い**（per-hop subprocess コスト） |

### 機構的な結論

rg prefilter が省けるのは「キャッシュ済み非マッチファイルの **automaton 走査**」という安価な部分のみ。
**重い部分（読込・復号・マッチファイルの tree-sitter パース）は `#1 LRU`＋`#2 lazy parse` が既に最適化済み**で、
rg はそれを重複して省けない。よって:

- 中規模実コード（LRU 予算内）: **利得ゼロ**。
- 巨大木（>LRU 予算）: rg-OFF は LRU thrash で再復号が増え rg が相対的に有利になるが、これは
  **キャッシュ容量の副作用**であり、本質はパース律速。LRU 予算調整の方が筋。
- 密集小ファイル: subprocess コストで**微減速**。

### 決定

**rg prefilter を既定 OFF（opt-in）へ戻した**（`--use-ripgrep` で明示有効化）。実測で既定ON を正当化
できず、SJIS 混在環境では既定OFF が最も安全（改修前の既定挙動＝rg 不使用を復元）。
ハードン済み prefilter（非ASCII symbol 無効化・非UTF-8 ファイル名の bytes/os.fsdecode・UTF-16↔_is_binary）は
opt-in 利用者向けに維持。速度の本命は #1 LRU＋#2 lazy parse（rg OFF 同士で実測 ~2–2.5×）で不変。
