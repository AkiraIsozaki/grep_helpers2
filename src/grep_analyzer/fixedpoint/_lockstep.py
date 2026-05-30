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
            union_keep = None       # prefilter が返した union keep（None＝全件走査）
            if opts.use_ripgrep:
                union_keep = _rg.prefilter(source_root, rel_to_abs, scan_symbols)
                if union_keep is not None:
                    safe = union_keep | unsafe_rels
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
            # per-keyword decode_replaced/encoding_of 帰属（Phase4 Task4a・rev.2 C-2）。
            # 共有 union 走査（scan_files・automaton・復号）は global hop ごとに1回だが、
            # absorb の per-relpath 副作用（encoding_of.setdefault / decode_replaced 診断、
            # _ingest.py:72-76）は「逐次版 keyword K がその hop で走査したであろう relpath 集合」に
            # 帰属させる必要がある。さもないと他 keyword の scan 集合でしか hit しない relpath の
            # decode_replaced が全 keyword に流入する（cross-keyword pollution）。
            #
            # - prefilter OFF（または keep=None／非ASCII記号で全件走査）: keep_K = 走査した全 relpath
            #   ＝FULL pass_results を渡す（U2 既定挙動。golden/tests が通る経路）。単一 keyword では
            #   union_keep も同じく全件ゆえ FULL＝逐次版と byte 同値（regression test がロック）。
            # - prefilter ON（union_keep が keep 集合）: keyword K 自身の scan 集合
            #   keep_K = prefilter(K の sorted(sc|stm)) | unsafe_rels を計算し、pass_results を
            #   keep_K の relpath に絞って渡す＝逐次版 keyword K が走査した relpath と一致。
            #   union 走査（高価な共有復号/automaton）は1回のままで、追加コストは安価な rg keep のみ。
            for kw, st in states_by_kw.items():
                sc, stm = per_kw[kw]
                kw_results = pass_results
                if opts.use_ripgrep and union_keep is not None:
                    keep_k = _rg.prefilter(source_root, rel_to_abs, sorted(sc | stm))
                    if keep_k is not None:
                        keep_k = keep_k | unsafe_rels
                        kw_results = [r for r in pass_results if r[0] in keep_k]
                    # keep_k is None（非ASCII記号 → 全件走査）の場合は FULL のまま
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
