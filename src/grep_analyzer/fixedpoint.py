"""不動点・ターゲットスキャン・エンジン（spec §8.1/§8.2/§8.3）。

direct ヒットを seed に constant/var を多ホップ追跡し indirect ヒットと chain を
出す。getter/setter は §8.3 で横展開しないが全反復走査・全件 low 報告(§8.4)。
来歴エッジは intro(実抽出元 Occurrence)ベース＝spec §8.2 を精密化(偽 chain 根治)。
出力は走査順・並列完了順に非依存で決定的(spec §9)。

停止性(spec §8.1 手順5): 追跡シンボルは原ソース字句のみ。母集合有限・採用集合
単調増加(chase_done から削らない＝cap は capped で scan 除外のみ)。よって高々
|母集合| ステップで飽和。--max-depth/max_symbols/max_paths は安全弁。
"""

import multiprocessing
from dataclasses import dataclass
from pathlib import Path

from grep_analyzer import automaton, walk
from grep_analyzer.budget import MemoryBudget, estimate_items
from grep_analyzer.chase import extract_chase_symbols
from grep_analyzer.classify import classify_hit
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.dispatch import detect_language, detect_shell_dialect
from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes
from grep_analyzer.model import Hit
from grep_analyzer.progress import Progress
from grep_analyzer import ripgrep as _rg
from grep_analyzer.provenance import Occurrence, ProvenanceGraph
from grep_analyzer.spill import EdgeStore
from grep_analyzer.stoplist import SymbolPolicy, load_stoplist, partition


@dataclass(frozen=True)
class EngineOptions:
    """spec §8/§10.4 のエンジン挙動パラメータ（Phase 2a/2b 範囲）。"""

    max_depth: int
    min_specificity: int
    stoplist_path: Path | None
    lang_map: dict[str, str]
    include: list[str]
    exclude: list[str]
    jobs: int
    follow_symlinks: bool
    max_file_bytes: int
    max_symbols: int
    max_paths: int
    memory_limit_mb: int | None = None
    use_ripgrep: bool = False
    max_passes: int = 8
    progress: str = "off"
    spill_dir: Path | None = None
    force_chunks: int = 0


_REF_KIND = {"constant": "indirect:constant", "var": "indirect:var",
             "getter": "indirect:getter", "setter": "indirect:setter"}


def _file_meta(rel: str, raw: bytes, lang_map: dict[str, str]):
    """1 度だけデコードし (text, enc, replaced, language, dialect) を返す。"""
    text, enc, replaced = decode_bytes(raw, DEFAULT_FALLBACK)
    language = detect_language(rel, text[:4096], lang_map)
    dialect = detect_shell_dialect(rel, text[:4096]) if language == "shell" else "bourne"
    return text, enc, replaced, language, dialect


def _scan_file(args):
    """1 ファイルをワーカ内で読み走査しヒット素片を返す純関数。

    ストリーミング化＝親に bytes 非常駐・abspath から読む（spec §8.2）。
    automaton 走査は raw 行。出力は Phase 2a と byte 不変。
    """
    rel, abspath, sym_list, lang_map = args
    raw = Path(abspath).read_bytes()
    text, enc, replaced, language, dialect = _file_meta(rel, raw, lang_map)
    au = automaton.build(sym_list)
    found = []
    if au is not None:
        for i, line in enumerate(text.split("\n"), start=1):
            for sym in automaton.scan_line(au, line):
                found.append((sym, i, line))
    return rel, enc, replaced, language, dialect, found


def _kinds_of(language: str, dialect: str, line: str) -> dict[str, str]:
    """1 行の各シンボル→種別。同名は constant>var>getter>setter の決定的優先。"""
    cs = extract_chase_symbols(language, dialect, line)
    out: dict[str, str] = {}
    for kind, names in (("setter", cs.setters), ("getter", cs.getters),
                        ("var", cs.vars), ("constant", cs.constants)):
        for n in names:
            out[n] = kind
    return out


def run_fixedpoint(
    seed_hits: list[Hit], source_root: Path, opts: EngineOptions, diag: Diagnostics,
    *, files=None
) -> list[Hit]:
    """seed から不動点まで多ホップ追跡し indirect Hit を決定的に返す（spec §8.1）。

    files 指定時は内部 walk を省き事前収集 (rel, abspath) 列を使う（同値）。
    """
    source_root = Path(source_root)
    policy = SymbolPolicy(opts.min_specificity, load_stoplist(opts.stoplist_path))
    budget = MemoryBudget(opts.memory_limit_mb)
    graph = ProvenanceGraph()
    keyword = sorted({s.keyword for s in seed_hits})[0] if seed_hits else ""

    intro: dict[str, list[Occurrence]] = {}   # symbol -> 実抽出元 Occurrence 群
    sym_kind: dict[str, str] = {}
    sym_hop: dict[str, int] = {}
    estore = EdgeStore(opts.spill_dir, budget)
    spill_logged = False
    chase_active: set[str] = set()
    chase_done: set[str] = set()
    term_active: set[str] = set()
    term_done: set[str] = set()
    capped: set[str] = set()
    no_expand_logged: set[str] = set()
    replaced_logged: set[str] = set()
    maxdepth_logged: set[Occurrence] = set()

    def _ingest(parent: Occurrence, language: str, dialect: str, line: str,
                hop: int, is_seed: bool = False):
        if hop > opts.max_depth:
            if parent not in maxdepth_logged:
                diag.add("prov_max_depth", f"{parent.symbol}@{parent.relpath}:"
                         f"{parent.lineno} (hop {hop} > --max-depth {opts.max_depth})")
                maxdepth_logged.add(parent)
            return
        cs = extract_chase_symbols(language, dialect, line)
        kinds = _kinds_of(language, dialect, line)
        part = partition(cs, language, policy)
        for sym, reason in sorted(part.rejected):
            diag.add("symbol_rejected", f"{reason}\t{sym}")
        for sym in part.chase:
            if sym in capped:
                continue
            # 非 seed の自己定義行が自分自身を再抽出しても発見元ではない
            # （spec §8.2「発見元≠発見」）。seed は keyword 原点なので例外。
            if not is_seed and sym == parent.symbol:
                continue
            sym_kind.setdefault(sym, kinds.get(sym, "var"))
            sym_hop.setdefault(sym, hop)
            lst = intro.setdefault(sym, [])
            if parent not in lst:
                lst.append(parent)
            if sym not in chase_done:
                chase_active.add(sym)
        for sym in part.terminal:
            if sym in capped:
                continue
            if not is_seed and sym == parent.symbol:
                continue
            sym_kind.setdefault(sym, kinds.get(sym, "getter"))
            sym_hop.setdefault(sym, hop)
            lst = intro.setdefault(sym, [])
            if parent not in lst:
                lst.append(parent)
            if sym not in term_done:
                term_active.add(sym)

    # hop0→hop1: seed ファイル実読で spec §5.1 決定的に言語/方言確定
    for s in seed_hits:
        occ = Occurrence(s.keyword, s.file, s.lineno)
        graph.add_seed(occ)
        sp = source_root / s.file
        if sp.is_file():
            _, _, _, lang, dia = _file_meta(s.file, sp.read_bytes(), opts.lang_map)
        else:
            lang, dia = s.language, "bourne"
        _ingest(occ, lang, dia, s.snippet, hop=1, is_seed=True)

    if files is None:
        files = list(walk.walk_files(
            source_root, include=opts.include, exclude=opts.exclude,
            follow_symlinks=opts.follow_symlinks,
            max_file_bytes=opts.max_file_bytes, diag=diag))
    rel_to_abs = {rel: abspath for rel, abspath in files}
    prog = Progress(opts.progress)
    prog.start(len(files))

    def _apply_global_cap():
        live = sorted(chase_active | chase_done | term_active | term_done,
                      key=lambda s: (sym_hop.get(s, 0), len(s), s))
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
            if s not in capped:
                diag.add("symbol_rejected", f"capped\t{s}")
                capped.add(s)
            chase_active.discard(s)
            term_active.discard(s)  # chase_done 単調維持・scan は capped で除外

    try:
        enc_of: dict[str, tuple[str, bool]] = {}
        hop = 1
        while chase_active or term_active:
            _apply_global_cap()
            if not budget.unlimited and not estore.spilled:
                n_intro = sum(len(v) for v in intro.values())
                n_live = len(chase_active | chase_done | term_active | term_done)
                if budget.exceeded(estimate_items(
                        n_symbols=n_live, n_edges=estore.in_memory_len(),
                        n_intro=n_intro)):
                    estore.maybe_spill_now()
                    if not spill_logged:
                        diag.add("graph_spilled", f"hop={hop}")
                        spill_logged = True
            scan_chase = {s for s in chase_active if s not in capped}
            scan_term = {s for s in term_active if s not in capped}
            scan_syms = sorted(scan_chase | scan_term)
            chase_done |= chase_active
            chase_active = set()
            term_done |= term_active
            term_active = set()
            if not scan_syms or hop > opts.max_depth:
                break
            scan_files = files
            if opts.use_ripgrep:
                keep_rels = _rg.prefilter(source_root, rel_to_abs, scan_syms)
                if keep_rels is not None:
                    scan_files = [(r, a) for r, a in files if r in keep_rels]
            n_intro = sum(len(v) for v in intro.values())
            n_live = len(chase_active | chase_done | term_active | term_done)
            nchunks = 1
            if opts.force_chunks and opts.force_chunks > 1:
                nchunks = min(opts.force_chunks, opts.max_passes,
                              max(1, len(scan_syms)))
            elif not budget.unlimited and budget.exceeded(estimate_items(
                    n_symbols=n_live, n_edges=estore.in_memory_len(),
                    n_intro=n_intro)):
                while nchunks < opts.max_passes and nchunks < len(scan_syms) and \
                        budget.exceeded(estimate_items(
                            n_symbols=-(-len(scan_syms) // (nchunks + 1)),
                            n_edges=estore.in_memory_len(), n_intro=n_intro)):
                    nchunks += 1
            if nchunks <= 1:
                args = [(rel, str(abspath), scan_syms, opts.lang_map)
                        for rel, abspath in scan_files]
                if opts.jobs > 1:
                    with multiprocessing.Pool(opts.jobs) as pool:
                        results = pool.map(_scan_file, args)
                else:
                    results = [_scan_file(a) for a in args]
                pass_results = sorted(results, key=lambda r: r[0])
            else:
                size = -(-len(scan_syms) // nchunks)
                chunks = [scan_syms[i:i + size]
                          for i in range(0, len(scan_syms), size)] or [[]]
                diag.add("automaton_split", f"hop={hop} chunks={len(chunks)}")
                agg: dict[str, list] = {}
                meta: dict[str, tuple] = {}
                for chunk in chunks:
                    args = [(rel, str(abspath), chunk, opts.lang_map)
                            for rel, abspath in scan_files]
                    if opts.jobs > 1:
                        with multiprocessing.Pool(opts.jobs) as pool:
                            res = pool.map(_scan_file, args)
                    else:
                        res = [_scan_file(a) for a in args]
                    for rel, enc, replaced, language, dialect, found in res:
                        meta.setdefault(rel, (enc, replaced, language, dialect))
                        agg.setdefault(rel, []).extend(found)
                pass_results = [(rel, *meta[rel],
                                 sorted(agg[rel], key=lambda t: (t[1], t[0])))
                                for rel in sorted(agg)]
            for rel, enc, replaced, language, dialect, found in pass_results:
                enc_of.setdefault(rel, (enc, replaced))
                if replaced and rel not in replaced_logged:
                    diag.add("decode_replaced", rel)
                    replaced_logged.add(rel)
                for sym, i, line in found:
                    if sym not in scan_chase and sym not in scan_term:
                        continue
                    child = Occurrence(sym, rel, i)
                    for parent in intro.get(sym, []):
                        if parent != child:
                            estore.add(parent, child)
                    if sym in scan_term:
                        if sym not in no_expand_logged:
                            diag.add("getter_setter_no_expand", sym)
                            no_expand_logged.add(sym)
                        continue
                    _ingest(child, language, dialect, line, hop + 1)
            prog.hop(hop, len(scan_syms), len(scan_files))
            hop += 1

        for p, c in estore.sorted_unique():
            graph.add_edge(p, c)

        indirect: list[Hit] = []
        seen: set[Occurrence] = set()
        line_cache: dict[str, list[str]] = {}
        meta_of: dict[str, tuple[str, str, str]] = {}
        for _, c in estore.sorted_unique():
            if c in seen or c.symbol not in (chase_done | term_done):
                continue
            if graph.is_seed_location(c.relpath, c.lineno):
                continue
            seen.add(c)
            if c.relpath not in line_cache:
                raw = rel_to_abs[c.relpath].read_bytes() if c.relpath in rel_to_abs else b""
                text, enc, replaced, lang, dia = _file_meta(c.relpath, raw, opts.lang_map)
                line_cache[c.relpath] = text.split("\n")
                meta_of[c.relpath] = (text, lang, dia)
                enc_of.setdefault(c.relpath, (enc, replaced))
            text, language, dialect = meta_of[c.relpath]
            lines = line_cache[c.relpath]
            line = lines[c.lineno - 1] if 0 <= c.lineno - 1 < len(lines) else ""
            kind = sym_kind.get(c.symbol, "var")
            cat, conf = classify_hit(language, dialect, text, c.lineno, line)
            if kind in ("getter", "setter"):
                conf = "low"
            enc, replaced = enc_of.get(c.relpath, ("utf-8", False))
            for chain in graph.chains_to(c, max_depth=opts.max_depth,
                                         max_paths=opts.max_paths, diag=diag):
                indirect.append(Hit(
                    keyword=keyword, language=language, file=c.relpath, lineno=c.lineno,
                    ref_kind=_REF_KIND[kind], category=cat, category_sub="",
                    usage_summary=f"{cat} ({language})", via_symbol=c.symbol,
                    chain=chain, snippet=line,
                    encoding=enc + (" 要確認" if replaced else ""), confidence=conf))
        prog.done()
        return indirect
    finally:
        estore.close()
