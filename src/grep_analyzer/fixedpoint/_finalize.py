"""scan ループ終了後の indirect Hit 列構築。

edge_store の (parent, child) を graph に追加し、終端 Occurrence ごとに
chain_to を列挙して indirect Hit を生成する。seed と同じ (relpath, lineno) は
除外する（seed は direct 側で既に出力されている）。

Related: spec §8.2, §9
"""

from grep_analyzer.classify import classify_hit
from grep_analyzer.fixedpoint._scan import file_meta
from grep_analyzer.fixedpoint._state import ChaseState
from grep_analyzer.model import Hit
from grep_analyzer.provenance import Occurrence
from grep_analyzer.snippet import build_snippet

_REF_KIND = {"constant": "indirect:constant", "var": "indirect:var",
             "getter": "indirect:getter", "setter": "indirect:setter"}


def build_indirect_hits(state: ChaseState) -> list[Hit]:
    """edge_store を走査し indirect Hit 列を決定的に構築する。"""
    opts = state.options
    diag = state.diagnostics
    for p, c in state.edge_store.sorted_unique():
        state.graph.add_edge(p, c)

    indirect: list[Hit] = []
    seen: set[Occurrence] = set()
    line_cache: dict[str, list[str]] = {}
    file_meta_by_relpath: dict[str, tuple[str, str, str]] = {}
    for _, c in state.edge_store.sorted_unique():
        if c in seen or c.symbol not in (state.chase_done | state.terminal_done):
            continue
        if state.graph.is_seed_location(c.relpath, c.lineno):
            continue
        seen.add(c)
        if c.relpath not in line_cache:
            raw = state.rel_to_abs[c.relpath].read_bytes() if c.relpath in state.rel_to_abs else b""
            text, enc, replaced, lang, dialect = file_meta(
                c.relpath, raw, opts.lang_map,
                fallback_chain=list(opts.encoding_fallback))
            line_cache[c.relpath] = text.split("\n")
            file_meta_by_relpath[c.relpath] = (text, lang, dialect)
            state.encoding_of.setdefault(c.relpath, (enc, replaced))
        text, language, dialect = file_meta_by_relpath[c.relpath]
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
                keyword=state.keyword, language=language, file=c.relpath,
                lineno=c.lineno, ref_kind=_REF_KIND[kind], category=cat,
                category_sub="", usage_summary=f"{cat} ({language})",
                via_symbol=c.symbol, chain=chain,
                snippet=build_snippet(language, dialect, text, c.lineno),
                encoding=enc + (" 要確認" if replaced else ""),
                confidence=conf))
    return indirect
