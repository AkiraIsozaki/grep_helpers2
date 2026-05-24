"""不動点・ターゲットスキャン・エンジン。

direct ヒットを seed に constant/var を多ホップ追跡し indirect ヒットと chain を
出す。getter/setter は §8.3 で横展開しないが全反復走査・全件 low 報告(§8.4)。
来歴エッジは introducers（実抽出元 Occurrence 群）ベース＝§8.2 を精密化(偽 chain 根治)。
出力は走査順・並列完了順に非依存で決定的(§9)。

停止性(§8.1 手順5): 追跡シンボルは原ソース字句のみ。母集合有限・採用集合
単調増加(state.chase_done から削らない＝cap は state.capped で scan 除外のみ)。よって高々
|母集合| ステップで飽和。--max-depth/max_symbols/max_paths は安全弁。

Related: spec §8.1, §8.2, §8.3, §8.4, §9
"""

from pathlib import Path

from grep_analyzer import ripgrep as _rg
from grep_analyzer import walk
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.fixedpoint._budget_control import (
    apply_global_cap,
    compute_nchunks,
    maybe_spill,
)
from grep_analyzer.fixedpoint._finalize import build_indirect_hits
from grep_analyzer.fixedpoint._ingest import absorb_results
from grep_analyzer.fixedpoint._options import EngineOptions
from grep_analyzer.fixedpoint._scan import make_file_cache, scan_hop
from grep_analyzer.fixedpoint._seed import initialize_state
from grep_analyzer.model import Hit
from grep_analyzer.progress import Progress

__all__ = ["EngineOptions", "run_fixedpoint"]


def run_fixedpoint(
    seed_hits: list[Hit], source_root: Path, opts: EngineOptions, diag: Diagnostics,
    *, files=None
) -> list[Hit]:
    """seed から不動点まで多ホップ追跡し indirect Hit を決定的に返す（spec §8.1）。

    files 指定時は内部 walk を省き事前収集 (relpath, abspath) 列を使う（同値）。
    """
    source_root = Path(source_root)
    state = initialize_state(seed_hits, source_root, opts, diag)

    if files is None:
        files = list(walk.walk_files(
            source_root, include=opts.include, exclude=opts.exclude,
            follow_symlinks=opts.follow_symlinks,
            max_file_bytes=opts.max_file_bytes, diag=diag))
    state.rel_to_abs = {relpath: abspath for relpath, abspath in files}
    progress = Progress(opts.progress)
    progress.start(len(files))
    file_cache = make_file_cache()

    try:
        hop = 1
        while state.chase_active or state.terminal_active:
            apply_global_cap(state)
            maybe_spill(state, hop)
            scan_chase = {s for s in state.chase_active if s not in state.capped}
            scan_term = {s for s in state.terminal_active if s not in state.capped}
            scan_symbols = sorted(scan_chase | scan_term)
            state.chase_done |= state.chase_active
            state.chase_active = set()
            state.terminal_done |= state.terminal_active
            state.terminal_active = set()
            if not scan_symbols or hop > opts.max_depth:
                break
            scan_files = files
            if opts.use_ripgrep:
                keep_rels = _rg.prefilter(source_root, state.rel_to_abs, scan_symbols)
                if keep_rels is not None:
                    scan_files = [(r, a) for r, a in files if r in keep_rels]
            nchunks = compute_nchunks(state, scan_symbols)
            pass_results, n_actual_chunks = scan_hop(
                scan_symbols, scan_files, opts, nchunks, file_cache=file_cache)
            if nchunks > 1:
                diag.add("automaton_split", f"hop={hop} chunks={n_actual_chunks}")
            absorb_results(state, pass_results, scan_chase, scan_term, hop)
            progress.hop(hop, len(scan_symbols), len(scan_files))
            hop += 1

        indirect = build_indirect_hits(state)
        progress.done()
        return indirect
    finally:
        state.edge_store.close()
