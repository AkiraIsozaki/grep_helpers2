"""不動点・ターゲットスキャン・エンジン（spec §8.1/§8.2/§8.3）。

direct ヒットを seed に constant/var を多ホップ追跡し indirect ヒットと chain を
出す。getter/setter は §8.3 で横展開しないが全反復走査・全件 low 報告(§8.4)。
来歴エッジは intro(実抽出元 Occurrence)ベース＝spec §8.2 を精密化(偽 chain 根治)。
出力は走査順・並列完了順に非依存で決定的(spec §9)。

停止性(spec §8.1 手順5): 追跡シンボルは原ソース字句のみ。母集合有限・採用集合
単調増加(state.chase_done から削らない＝cap は state.capped で scan 除外のみ)。よって高々
|母集合| ステップで飽和。--max-depth/max_symbols/max_paths は安全弁。
"""

from pathlib import Path

from grep_analyzer import walk
from grep_analyzer.budget import MemoryBudget, estimate_items  # estimate_items: perf test の monkeypatch 接点（tests/perf/test_perf.py:49）
from grep_analyzer.chase import extract_chase_symbols
from grep_analyzer.classify import classify_hit
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.model import Hit
from grep_analyzer.progress import Progress
from grep_analyzer import ripgrep as _rg
from grep_analyzer.provenance import Occurrence, ProvenanceGraph
from grep_analyzer.snippet import build_snippet
from grep_analyzer.spill import EdgeStore
from grep_analyzer.stoplist import SymbolPolicy, load_stoplist, partition
from grep_analyzer.fixedpoint._options import EngineOptions
from grep_analyzer.fixedpoint._scan import _file_meta, _kinds_of, _scan_file, scan_hop
from grep_analyzer.fixedpoint._state import ChaseState, _REF_KIND


def run_fixedpoint(
    seed_hits: list[Hit], source_root: Path, opts: EngineOptions, diag: Diagnostics,
    *, files=None
) -> list[Hit]:
    """seed から不動点まで多ホップ追跡し indirect Hit を決定的に返す（spec §8.1）。

    files 指定時は内部 walk を省き事前収集 (rel, abspath) 列を使う（同値）。
    """
    source_root = Path(source_root)
    keyword = sorted({s.keyword for s in seed_hits})[0] if seed_hits else ""
    budget = MemoryBudget(opts.memory_limit_mb)
    state = ChaseState(
        source_root=source_root,
        options=opts,
        diagnostics=diag,
        policy=SymbolPolicy(opts.min_specificity, load_stoplist(opts.stoplist_path)),
        budget=budget,
        graph=ProvenanceGraph(),
        edge_store=EdgeStore(opts.spill_dir, budget),
        keyword=keyword,
    )

    def _ingest(parent: Occurrence, language: str, dialect: str, line: str,
                hop: int, is_seed: bool = False):
        if hop > opts.max_depth:
            if parent not in state.maxdepth_logged:
                diag.add("prov_max_depth", f"{parent.symbol}@{parent.relpath}:"
                         f"{parent.lineno} (hop {hop} > --max-depth {opts.max_depth})")
                state.maxdepth_logged.add(parent)
            return
        cs = extract_chase_symbols(language, dialect, line)
        kinds = _kinds_of(language, dialect, line)
        part = partition(cs, language, state.policy)
        for sym, reason in sorted(part.rejected):
            diag.add("symbol_rejected", f"{reason}\t{sym}")
        for sym in part.chase:
            if sym in state.capped:
                continue
            # 非 seed の自己定義行が自分自身を再抽出しても発見元ではない
            # （spec §8.2「発見元≠発見」）。seed は keyword 原点なので例外。
            if not is_seed and sym == parent.symbol:
                continue
            state.symbol_kind.setdefault(sym, kinds.get(sym, "var"))
            state.symbol_hop.setdefault(sym, hop)
            lst = state.introducers.setdefault(sym, [])
            if parent not in lst:
                lst.append(parent)
            if sym not in state.chase_done:
                state.chase_active.add(sym)
        for sym in part.terminal:
            if sym in state.capped:
                continue
            if not is_seed and sym == parent.symbol:
                continue
            state.symbol_kind.setdefault(sym, kinds.get(sym, "getter"))
            state.symbol_hop.setdefault(sym, hop)
            lst = state.introducers.setdefault(sym, [])
            if parent not in lst:
                lst.append(parent)
            if sym not in state.terminal_done:
                state.terminal_active.add(sym)

    # hop0→hop1: seed ファイル実読で spec §5.1 決定的に言語/方言確定
    for s in seed_hits:
        occ = Occurrence(s.keyword, s.file, s.lineno)
        state.graph.add_seed(occ)
        sp = source_root / s.file
        if sp.is_file():
            text, _, _, lang, dia = _file_meta(
                s.file, sp.read_bytes(), opts.lang_map,
                fallback_chain=list(opts.encoding_fallback))
            _ls = text.split("\n")
            seed_line = _ls[s.lineno - 1] if 0 <= s.lineno - 1 < len(_ls) else ""
        else:
            lang, dia = s.language, "bourne"
            seed_line = ""
        _ingest(occ, lang, dia, seed_line, hop=1, is_seed=True)

    if files is None:
        files = list(walk.walk_files(
            source_root, include=opts.include, exclude=opts.exclude,
            follow_symlinks=opts.follow_symlinks,
            max_file_bytes=opts.max_file_bytes, diag=diag))
    state.rel_to_abs = {rel: abspath for rel, abspath in files}
    prog = Progress(opts.progress)
    prog.start(len(files))

    def _apply_global_cap():
        live = sorted(state.chase_active | state.chase_done | state.terminal_active | state.terminal_done,
                      key=lambda s: (state.symbol_hop.get(s, 0), len(s), s))
        keep_count = opts.max_symbols
        if not budget.unlimited:
            # spec §8.2 L164 優先1: --memory-limit 超過時の §8.3 決定的切り捨て。
            # edges は priority-2 spill で退避(n_edges=0)、intro はシンボル連動
            # (n_intro≈keep_count)。キー不変・単調縮小・決定的。keep_count=0 は memory 0 等。
            while keep_count > 0 and budget.exceeded(estimate_items(
                    n_symbols=keep_count, n_edges=0, n_intro=keep_count)):
                keep_count -= 1
        if len(live) <= keep_count:
            return
        for s in live[keep_count:]:
            if s not in state.capped:
                diag.add("symbol_rejected", f"capped\t{s}")
                state.capped.add(s)
            state.chase_active.discard(s)
            state.terminal_active.discard(s)  # chase_done 単調維持・scan は capped で除外

    try:
        hop = 1
        while state.chase_active or state.terminal_active:
            _apply_global_cap()
            if not budget.unlimited and not state.edge_store.spilled:
                n_intro = sum(len(v) for v in state.introducers.values())
                n_live = len(state.chase_active | state.chase_done | state.terminal_active | state.terminal_done)
                if budget.exceeded(estimate_items(
                        n_symbols=n_live, n_edges=state.edge_store.in_memory_len(),
                        n_intro=n_intro)):
                    state.edge_store.maybe_spill_now()
                    if not state.spill_logged:
                        diag.add("graph_spilled", f"hop={hop}")
                        state.spill_logged = True
            scan_chase = {s for s in state.chase_active if s not in state.capped}
            scan_term = {s for s in state.terminal_active if s not in state.capped}
            scan_syms = sorted(scan_chase | scan_term)
            state.chase_done |= state.chase_active
            state.chase_active = set()
            state.terminal_done |= state.terminal_active
            state.terminal_active = set()
            if not scan_syms or hop > opts.max_depth:
                break
            scan_files = files
            if opts.use_ripgrep:
                keep_rels = _rg.prefilter(source_root, state.rel_to_abs, scan_syms)
                if keep_rels is not None:
                    scan_files = [(r, a) for r, a in files if r in keep_rels]
            n_intro = sum(len(v) for v in state.introducers.values())
            n_live = len(state.chase_active | state.chase_done | state.terminal_active | state.terminal_done)
            nchunks = 1
            if opts.force_chunks and opts.force_chunks > 1:
                nchunks = min(opts.force_chunks, opts.max_passes,
                              max(1, len(scan_syms)))
            elif not budget.unlimited and budget.exceeded(estimate_items(
                    n_symbols=n_live, n_edges=state.edge_store.in_memory_len(),
                    n_intro=n_intro)):
                while nchunks < opts.max_passes and nchunks < len(scan_syms) and \
                        budget.exceeded(estimate_items(
                            n_symbols=-(-len(scan_syms) // (nchunks + 1)),
                            n_edges=state.edge_store.in_memory_len(), n_intro=n_intro)):
                    nchunks += 1
            pass_results, n_actual_chunks = scan_hop(scan_syms, scan_files, opts, nchunks)
            if nchunks > 1:
                diag.add("automaton_split", f"hop={hop} chunks={n_actual_chunks}")
            for rel, enc, replaced, language, dialect, found in pass_results:
                state.encoding_of.setdefault(rel, (enc, replaced))
                if replaced and rel not in state.replaced_logged:
                    diag.add("decode_replaced", rel)
                    state.replaced_logged.add(rel)
                for sym, i, line in found:
                    if sym not in scan_chase and sym not in scan_term:
                        continue
                    child = Occurrence(sym, rel, i)
                    for parent in state.introducers.get(sym, []):
                        if parent != child:
                            state.edge_store.add(parent, child)
                    if sym in scan_term:
                        if sym not in state.no_expand_logged:
                            diag.add("getter_setter_no_expand", sym)
                            state.no_expand_logged.add(sym)
                        continue
                    _ingest(child, language, dialect, line, hop + 1)
            prog.hop(hop, len(scan_syms), len(scan_files))
            hop += 1

        for p, c in state.edge_store.sorted_unique():
            state.graph.add_edge(p, c)

        indirect: list[Hit] = []
        seen: set[Occurrence] = set()
        line_cache: dict[str, list[str]] = {}
        meta_of: dict[str, tuple[str, str, str]] = {}
        for _, c in state.edge_store.sorted_unique():
            if c in seen or c.symbol not in (state.chase_done | state.terminal_done):
                continue
            if state.graph.is_seed_location(c.relpath, c.lineno):
                continue
            seen.add(c)
            if c.relpath not in line_cache:
                raw = state.rel_to_abs[c.relpath].read_bytes() if c.relpath in state.rel_to_abs else b""
                text, enc, replaced, lang, dia = _file_meta(c.relpath, raw, opts.lang_map, fallback_chain=list(opts.encoding_fallback))
                line_cache[c.relpath] = text.split("\n")
                meta_of[c.relpath] = (text, lang, dia)
                state.encoding_of.setdefault(c.relpath, (enc, replaced))
            text, language, dialect = meta_of[c.relpath]
            lines = line_cache[c.relpath]
            line = lines[c.lineno - 1] if 0 <= c.lineno - 1 < len(lines) else ""
            kind = state.symbol_kind.get(c.symbol, "var")
            cat, conf = classify_hit(language, dialect, text, c.lineno, line)
            if kind in ("getter", "setter"):
                conf = "low"
            enc, replaced = state.encoding_of.get(c.relpath, ("utf-8", False))
            for chain in state.graph.chains_to(c, max_depth=opts.max_depth,
                                         max_paths=opts.max_paths, diag=diag):
                indirect.append(Hit(
                    keyword=keyword, language=language, file=c.relpath,
                    lineno=c.lineno, ref_kind=_REF_KIND[kind], category=cat,
                    category_sub="", usage_summary=f"{cat} ({language})",
                    via_symbol=c.symbol, chain=chain,
                    snippet=build_snippet(language, dialect, text, c.lineno),
                    encoding=enc + (" 要確認" if replaced else ""),
                    confidence=conf))
        prog.done()
        return indirect
    finally:
        state.edge_store.close()
