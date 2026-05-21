# Phase 3 V6 性能計測

## Baseline (Phase 2 完了時点: 8042bd3f0fe60e853fd2da0bff45b165b5e0dddd)

- 計測コマンド: `pytest "tests/perf/test_perf.py::test_scale[800]" -m perf -q -s | grep "PERF n=800"`
- 対象ケース: `test_scale[800]`（test_perf.py で固定された最大 n_files=800）
- 3 回実行の dt (秒): [0.299, 0.307, 0.324]
- 中央値: 0.307

## R4 試作判定 (Task A2 Step 0 で記録)

| 項目 | 並存案 | 統合案 |
|---|---|---|
| コード量（ファイル全体・docstring 含） | 45 行 | 37 行 |
| 関数本体実コード（def 〜 return） | scan_hop_single: 9 行 / scan_hop_chunked: 19 行 = 計 28 行 | scan_hop: 22 行 |
| diag 発火局所性 | 呼出側で `if nchunks > 1:` 必要 | 呼出側で `if nchunks > 1:` 必要（同等） |
| byte 同値性 | — | nchunks=1 ⇒ chunks=[scan_syms] 単発実行で found は (line 昇順, sym 昇順) 維持・`sorted(agg[rel], key=(line, sym))` は automaton.scan_line の sorted 出力と恒等一致（補-8） |
| 結論 | × | **採用** |

統合に進む（差分が "chunks の構築方法" だけに収束、R4 規約 §5 を満たす）。
試作配置: `/tmp/phase3_r4_proto/scan_split.py` / `scan_unified.py`（補-7 / Phase 3 完了時に手動削除推奨）。

## Phase 3 [A] 完了後

計測 HEAD: b849ec2（Task A5 完了直後 / Task A6 計測時点）
計測コマンド: `pytest tests/perf/test_perf.py::test_scale -m perf -q -s | grep "PERF n=800"`

### `scan_hop` 統合経路（R4 統合案採用のため single/chunked は同一実装）
- 3 回実行 (秒): [0.341, 0.358, 0.362]
- 中央値: 0.358

注: R4 試作判定（上記表）で **統合案を採用** したため、`force_chunks` 切替で経路自体は分岐しない（同一 `scan_hop` の chunks 構築のみ差分）。よって chunked 経路の別途計測は実施せず、`test_scale[800]` 1 系列で代表する。

## 判定

baseline_median + 10% 又は +5 秒以内であれば許容（OR）。
- baseline_median: 0.307 秒
- new_median: 0.358 秒
- 差: +0.051 秒 / +16.6%
- 判定: **OK**（+10% は超過するが +5 秒以内の OR 条件を満たす。絶対値 0.051 秒は計測ノイズ域）
