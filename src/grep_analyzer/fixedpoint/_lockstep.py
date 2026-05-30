"""lock-step 共有エンジン: 全 keyword を1本の union 走査で前進させる（spec §4.1）。

run_fixedpoint（逐次・単一 keyword）のループを忠実に転置する。GLOBAL hop ごとに
全 keyword の active シンボルを union して1回だけ走査し、結果を keyword 別に absorb
する。単一 keyword では逐次版と byte 同値（golden(92) 不変の要）。

単一 keyword 同値の根拠（逐次版とのライン対応）:
- ghop == 逐次版の local hop（単一 keyword では increment が同期）。
- automaton_split / graph_spilled の `hop={ghop}` も逐次版と同一文字列。
- C-2 の per-keyword 絞り込みは単一 keyword では want=scan_symbols 全部・found 記号は
  全て scan_symbols ∈ want ゆえ恒等（kw_results == pass_results）。
- compute_nchunks_union([state], …) == compute_nchunks(state, …)（Task2 で証明済）。
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
from grep_analyzer.fixedpoint._scan import make_file_cache, scan_hop
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
    # make_pool は fixedpoint パッケージ名前空間経由で解決し、利用箇所での
    # monkeypatch（Pool 生成回数の検証テスト）を従来どおり成立させる。
    from grep_analyzer import fixedpoint as _fp
    pool = _fp.make_pool(opts)
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
            # rev.2 C-2: 各 keyword の absorb 前に pass_results を「その keyword の scan 集合の
            # 記号が found に1件でもある relpath」に絞る（diagnostics 汚染＝他keyword記号だけ
            # hit した relpath の decode_replaced/encoding_of を防ぐ）。単一keyword では恒等。
            for kw, st in states_by_kw.items():
                sc, stm = per_kw[kw]
                want = sc | stm
                kw_results = [
                    (rel, enc, rep, lang, dia, [t for t in found if t[0] in want])
                    for (rel, enc, rep, lang, dia, found) in pass_results
                    if any(t[0] in want for t in found)]
                absorb_results(st, kw_results, sc, stm, ghop)
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
