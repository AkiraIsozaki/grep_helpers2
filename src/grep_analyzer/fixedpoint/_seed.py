"""seed_hits から ChaseState を初期化する（hop0→hop1）。

seed ファイルを実読してその行から spec §5.1 決定的に language/dialect を確定し、
hop=1 で initial ingest を行う。is_seed=True なので「自分が自分を再抽出」も
許容する（seed は keyword 原点）。
"""

from pathlib import Path

from grep_analyzer.budget import MemoryBudget
from grep_analyzer.chase import extract_chase_symbols, extract_chase_symbols_tree
from grep_analyzer.classifiers import _AST_CHASERS
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.fixedpoint._ingest import ingest_one
from grep_analyzer.fixedpoint._options import EngineOptions
from grep_analyzer.fixedpoint._scan import file_meta, kinds_of
from grep_analyzer.fixedpoint._state import ChaseState
from grep_analyzer.model import ChaseSymbols, Hit
from grep_analyzer.provenance import Occurrence, ProvenanceGraph
from grep_analyzer.spill import EdgeStore
from grep_analyzer.stoplist import SymbolPolicy, load_stoplist


def initialize_state(seed_hits: list[Hit], source_root: Path,
                     opts: EngineOptions, diag: Diagnostics) -> ChaseState:
    """seed_hits を ChaseState に取り込み、hop=1 までの初期 ingest を完了させる。"""
    policy = SymbolPolicy(opts.min_specificity, load_stoplist(opts.stoplist_path))
    budget = MemoryBudget(opts.memory_limit_mb)
    graph = ProvenanceGraph()
    keyword = sorted({s.keyword for s in seed_hits})[0] if seed_hits else ""

    state = ChaseState(
        source_root=source_root,
        options=opts,
        diagnostics=diag,
        policy=policy,
        budget=budget,
        graph=graph,
        edge_store=EdgeStore(opts.spill_dir, budget),
        keyword=keyword,
    )

    for s in seed_hits:
        occ = Occurrence(s.keyword, s.file, s.lineno)
        state.graph.add_seed(occ)
        sp = source_root / s.file
        if sp.is_file():
            text, _, _, lang, dialect = file_meta(
                s.file, sp.read_bytes(), opts.lang_map,
                fallback_chain=list(opts.encoding_fallback))
            if lang in _AST_CHASERS:
                cs = extract_chase_symbols_tree(lang, text, s.lineno)
            else:
                _ls = text.split("\n")
                seed_line = _ls[s.lineno - 1] if 0 <= s.lineno - 1 < len(_ls) else ""
                cs = extract_chase_symbols(lang, dialect, seed_line)
        else:
            lang, dialect = s.language, "bourne"
            cs = ChaseSymbols()
        ingest_one(state, occ, lang, cs, kinds_of(cs), hop=1, is_seed=True)
    return state
