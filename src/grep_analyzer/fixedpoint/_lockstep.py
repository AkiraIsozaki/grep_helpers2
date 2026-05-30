"""lock-step 共有エンジン: 全 keyword を1本の union 走査で前進させる（spec §4.1）。

run_fixedpoint（逐次・単一 keyword）のループを忠実に転置する。GLOBAL hop ごとに
全 keyword の active シンボルを union して1回だけ走査し、結果を keyword 別に absorb
する。単一 keyword では逐次版と byte 同値（golden(92) 不変の要）。

単一 keyword 同値の根拠（逐次版とのライン対応）:
- ghop == 逐次版の local hop（単一 keyword では increment が同期）。
- automaton_split / graph_spilled の `hop={ghop}` も逐次版と同一文字列。
- absorb_results へは FULL pass_results を渡す＝逐次版と同一入力。per-relpath 副作用
  （encoding_of / decode_replaced）が走査済み・symbol 非ヒットの relpath でも保たれる。
- compute_nchunks_union([state], …) の n_live は |union記号|＝spec §4.1 の union 意味論で
  あり、逐次版 compute_nchunks の n_live=|done集合| とは意味が異なる。両者が差を生むのは
  finite --memory-limit かつ hop≥2 のときのみで、影響は automaton_split 診断と chunk 数に
  限られる（§8.4-EXEMPT・出力中立。下記 _budget_control.py の注記参照）。
- progress.start/hop/done の呼出回数も単一 keyword で逐次版と一致。

Related: spec §4.1, §6.2, §8.1, §8.2, §8.4
"""

from pathlib import Path

from grep_analyzer import ripgrep as _rg
from grep_analyzer.fixedpoint._budget_control import (
    apply_global_cap,
    compute_nchunks_union,
    maybe_spill,
)
from grep_analyzer.fixedpoint._finalize import build_indirect_hits
from grep_analyzer.fixedpoint._ingest import absorb_results
from grep_analyzer.fixedpoint._scan import make_file_cache, make_pool, scan_hop
from grep_analyzer.progress import Progress


def run_fixedpoint_multi(states_by_kw, source_root, opts, *, files,
                         unsafe_rels=None, enc_memo=None):
    """全 keyword を lock-step で前進させ keyword 別 indirect Hit を返す（spec §4.1）。"""
    source_root = Path(source_root)
    unsafe_rels = unsafe_rels or set()
    rel_to_abs = {r: a for r, a in files}
    for st in states_by_kw.values():
        st.rel_to_abs = rel_to_abs
        st.enc_memo = enc_memo          # finalize が st.enc_memo を使う（Phase3）
    progress = Progress(opts.progress)
    progress.start(len(files))
    file_cache = make_file_cache()
    pool = make_pool(opts)
    try:
        ghop = 1
        while any(st.chase_active or st.terminal_active for st in states_by_kw.values()):
            per_kw = {}
            union = set()
            for kw, st in states_by_kw.items():
                apply_global_cap(st)
                maybe_spill(st, ghop)
                sc = {s for s in st.chase_active if s not in st.capped}
                stm = {s for s in st.terminal_active if s not in st.capped}
                st.chase_done |= st.chase_active
                st.chase_active = set()
                st.terminal_done |= st.terminal_active
                st.terminal_active = set()
                per_kw[kw] = (sc, stm)
                union |= sc | stm
            scan_symbols = sorted(union)
            if not scan_symbols or ghop > opts.max_depth:
                break
            scan_files = files
            if opts.use_ripgrep:
                keep = _rg.prefilter(source_root, rel_to_abs, scan_symbols)
                if keep is not None:
                    safe = keep | unsafe_rels
                    scan_files = [(r, a) for r, a in files if r in safe]
            # 全 state は opts 由来の等価な budget（MemoryBudget(opts.memory_limit_mb)）を持つ＝
            # 先頭を採るのは安全。
            nchunks = compute_nchunks_union(
                list(states_by_kw.values()), scan_symbols,
                opts=opts, budget=next(iter(states_by_kw.values())).budget)
            pass_results, n_actual_chunks = scan_hop(
                scan_symbols, scan_files, opts, nchunks,
                file_cache=file_cache, pool=pool, enc_memo=enc_memo)
            # automaton_split は共有走査ゆえ global hop ごとに1回（spec §6.2＝§8.4 対象外）。
            # 単一keyword では state.diagnostics（逐次版と同一文字列）。複数keyword は Task5。
            if nchunks > 1:
                for st in states_by_kw.values():
                    st.diagnostics.add("automaton_split", f"hop={ghop} chunks={n_actual_chunks}")
            # absorb は OLD run_fixedpoint と同一＝FULL pass_results を各 keyword に渡す。
            # 単一 keyword: 逐次エンジンと byte 同値。pass_results は走査した全 relpath を
            #   含む（found が空＝復号のみ・symbol 非ヒットの relpath も含む）。absorb_results は
            #   symbol filter（_ingest.py:78）の手前で per-relpath 副作用（encoding_of.setdefault /
            #   decode_replaced 診断、_ingest.py:72-76）を発火させるため、found が空でも replaced=True
            #   なファイルの decode_replaced が保たれる。FULL pass_results を渡すことがこの同値の要。
            # 複数 keyword: per-relpath 診断を keyword 横断で過剰報告する（他 keyword の scan 集合で
            #   しか hit しない relpath の decode_replaced/encoding_of が全 keyword に流入＝
            #   cross-keyword pollution）。正しい per-keyword scan-set 帰属は Phase4 Task 4 へ DEFER。
            #   rev.2 C-2 の「any found」絞り込みは INCORRECT（走査済み・symbol 非ヒットの
            #   replaced ファイルの decode_replaced を落とす）と判明したため撤回。Task 4 で
            #   pipeline が実 multi-keyword 走査を配線する際に per-keyword scan-set 帰属で再設計する。
            for kw, st in states_by_kw.items():
                sc, stm = per_kw[kw]
                absorb_results(st, pass_results, sc, stm, ghop)
            progress.hop(ghop, len(scan_symbols), len(scan_files))
            ghop += 1
        result = {kw: build_indirect_hits(st) for kw, st in states_by_kw.items()}
        progress.done()
        return result
    finally:
        if pool is not None:
            pool.close()
            pool.join()
        for st in states_by_kw.values():
            st.edge_store.close()
