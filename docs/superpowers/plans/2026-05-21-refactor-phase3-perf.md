# Phase 3 V6 性能計測

## Baseline (Phase 2 完了時点: 8042bd3f0fe60e853fd2da0bff45b165b5e0dddd)

- 計測コマンド: `pytest "tests/perf/test_perf.py::test_scale[800]" -m perf -q -s | grep "PERF n=800"`
- 対象ケース: `test_scale[800]`（test_perf.py で固定された最大 n_files=800）
- 3 回実行の dt (秒): [0.299, 0.307, 0.324]
- 中央値: 0.307

## R4 試作判定 (Task A2 Step 0 で記録)

| 項目 | 判定 |
|---|---|
| 統合版コード量 | <行数> |
| 並存版コード量 | <行数> |
| diag 発火局所性 | OK/NG |
| 採用: 統合 or 並存 | <結論> |

## Phase 3 [A] 完了後

（Task A6 後に記録）

### `force_chunks=0`（single 経路）
- 3 回実行: [t1, t2, t3]
- 中央値: <new_median_single>

### `force_chunks=3`（chunked 経路, R4 並存採用時のみ）
- 3 回実行: [t1, t2, t3]
- 中央値: <new_median_chunked>

## 判定

baseline_median + 10% 又は +5 秒以内であれば許容。
- single: baseline_median 0.307 → new <new_single>（差 <diff>%）→ OK/NG
- chunked: 同上
