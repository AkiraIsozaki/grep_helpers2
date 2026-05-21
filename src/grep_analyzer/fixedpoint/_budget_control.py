"""グローバル cap / spill / nchunks 計算（spec §8.2 L164 優先 1 / §8.3）。

- apply_global_cap: --memory-limit / --max-symbols でシンボル集合を切り詰める。
  単調縮小・決定的（キー: (symbol_hop, len(s), s)）。
- maybe_spill: in-memory edge 数と introducers 数で予算超過判定し、超過時に
  edge_store.maybe_spill_now() を呼ぶ。1 度だけ diag を立てる。
- compute_nchunks: 1 hop の chunk 数を予算と force_chunks から決める。

注: compute_nchunks は **chase_active/terminal_active を空にした直後**に呼ばれる
前提（n_live はその時点の (chase|terminal)_done 集合のみから計算される）。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [A]
"""

from grep_analyzer import budget as _budget
from grep_analyzer.fixedpoint._state import ChaseState


def apply_global_cap(state: ChaseState):
    """シンボル集合を memory_limit / max_symbols で決定的に切り詰める。"""
    diag = state.diagnostics
    opts = state.options
    live = sorted(state.chase_active | state.chase_done
                  | state.terminal_active | state.terminal_done,
                  key=lambda s: (state.symbol_hop.get(s, 0), len(s), s))
    keep_count = opts.max_symbols
    if not state.budget.unlimited:
        while keep_count > 0 and state.budget.exceeded(_budget.estimate_items(
                n_symbols=keep_count, n_edges=0, n_intro=keep_count)):
            keep_count -= 1
    if len(live) <= keep_count:
        return
    for s in live[keep_count:]:
        if s not in state.capped:
            diag.add("symbol_rejected", f"capped\t{s}")
            state.capped.add(s)
        state.chase_active.discard(s)
        state.terminal_active.discard(s)


def maybe_spill(state: ChaseState, hop: int):
    """予算超過時に edge_store を spill する（1 度だけ diag 記録）。"""
    if state.budget.unlimited or state.edge_store.spilled:
        return
    n_intro = sum(len(v) for v in state.introducers.values())
    n_live = len(state.chase_active | state.chase_done
                 | state.terminal_active | state.terminal_done)
    if state.budget.exceeded(_budget.estimate_items(
            n_symbols=n_live, n_edges=state.edge_store.in_memory_len(),
            n_intro=n_intro)):
        state.edge_store.maybe_spill_now()
        if not state.spill_logged:
            state.diagnostics.add("graph_spilled", f"hop={hop}")
            state.spill_logged = True


def compute_nchunks(state: ChaseState, scan_syms: list[str]) -> int:
    """1 hop の chunk 数を決める。`force_chunks` 指定優先、超過予算時のみ自動増やす。"""
    opts = state.options
    nchunks = 1
    if opts.force_chunks and opts.force_chunks > 1:
        return min(opts.force_chunks, opts.max_passes, max(1, len(scan_syms)))
    if state.budget.unlimited:
        return 1
    n_intro = sum(len(v) for v in state.introducers.values())
    n_live = len(state.chase_active | state.chase_done
                 | state.terminal_active | state.terminal_done)
    if not state.budget.exceeded(_budget.estimate_items(
            n_symbols=n_live, n_edges=state.edge_store.in_memory_len(),
            n_intro=n_intro)):
        return 1
    while nchunks < opts.max_passes and nchunks < len(scan_syms) and \
            state.budget.exceeded(_budget.estimate_items(
                n_symbols=-(-len(scan_syms) // (nchunks + 1)),
                n_edges=state.edge_store.in_memory_len(), n_intro=n_intro)):
        nchunks += 1
    return nchunks
