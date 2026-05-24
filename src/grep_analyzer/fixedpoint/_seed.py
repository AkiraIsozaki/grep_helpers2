"""seed_hits から ChaseState を初期化する（hop0→hop1）。

seed ファイルを実読してその行から spec §5.1 決定的に language/dialect を確定し、
hop=1 で initial ingest を行う。is_seed=True なので「自分が自分を再抽出」も
許容する（seed は keyword 原点）。
"""

from pathlib import Path

from grep_analyzer.budget import MemoryBudget
from grep_analyzer.chase import (
    extract_chase_symbols,
    extract_chase_symbols_from_root,
)
from grep_analyzer.classifiers import _AST_CHASERS
from grep_analyzer.classifiers.ts_classifier import parse_tree
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.embed_preprocess import effective_language
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

    # seed_hits は direct パスがファイル単位でまとめて構築する＝同一ファイルが連続する。
    # 直前 1 ファイル分の (text, lines, language, dialect, パース木) をキャッシュし、
    # 同一ファイルの複数 seed で読込・split・tree-sitter パースを 1 回に集約する
    # （追加メモリは O(1)＝1 ファイル分）。
    cur_relpath = None
    cur_text = cur_lines = cur_lang = cur_dialect = cur_tree_cache = None
    for s in seed_hits:
        occ = Occurrence(s.keyword, s.file, s.lineno)
        state.graph.add_seed(occ)
        from grep_analyzer.walk import is_contained_relpath
        sp = source_root / s.file
        if is_contained_relpath(s.file) and sp.is_file():
            if s.file != cur_relpath:
                cur_text, _, _, cur_lang, cur_dialect = file_meta(
                    s.file, sp.read_bytes(), opts.lang_map,
                    fallback_chain=list(opts.encoding_fallback))
                cur_lines = None          # 非 AST 言語の split は必要時のみ遅延生成
                cur_tree_cache = {}
                cur_relpath = s.file
            dialect = cur_dialect
            lang = effective_language(cur_lang, cur_text, s.lineno)
            if lang in _AST_CHASERS:
                root = parse_tree(lang, cur_text, cache=cur_tree_cache)
                cs = extract_chase_symbols_from_root(lang, root, s.lineno)
            else:
                if cur_lines is None:
                    cur_lines = cur_text.split("\n")
                seed_line = (cur_lines[s.lineno - 1]
                             if 0 <= s.lineno - 1 < len(cur_lines) else "")
                cs = extract_chase_symbols(lang, dialect, seed_line)
        else:
            lang, dialect = s.language, "bourne"
            cs = ChaseSymbols()
        ingest_one(state, occ, lang, cs, kinds_of(cs), hop=1, is_seed=True)
    return state
