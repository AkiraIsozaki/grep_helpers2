"""scan worker と scan-hop オーケストレーション。

`_scan_file` は multiprocessing.Pool 用のトップレベル純関数（pickle 制約）。
追跡状態オブジェクトは worker に渡さず、main process で構築した args タプル
のみ渡す。`scan_hop` は呼出側から渡された必要プリミティブだけを引数に取り、
worker からの戻り値を呼出側で追跡状態へ反映する（worker isolation 厳守）。

`file_meta` / `kinds_of` は追跡状態を引数に取らない純関数 helper として
`_seed` / `_ingest` / `_finalize` から共有 import される（pickle 制約と矛盾なし）。
"""

import multiprocessing
from pathlib import Path

from grep_analyzer import automaton
from grep_analyzer.chase import extract_chase_symbols_from_root
from grep_analyzer.classifiers import _AST_CHASERS
from grep_analyzer.classifiers.ts_classifier import parse_tree
from grep_analyzer.dispatch import detect_language, detect_shell_dialect
from grep_analyzer.embed_preprocess import inline_template_spans
from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes
from grep_analyzer.model import ChaseSymbols


def file_meta(relpath: str, raw: bytes, lang_map: dict[str, str], fallback_chain=None):
    """1 度だけデコードし (text, encoding, replaced, language, dialect) を返す。"""
    chain = list(fallback_chain) if fallback_chain else DEFAULT_FALLBACK
    text, enc, replaced = decode_bytes(raw, chain)
    language = detect_language(relpath, text[:4096], lang_map)
    dialect = detect_shell_dialect(relpath, text[:4096]) if language == "shell" else "bourne"
    return text, enc, replaced, language, dialect


def _scan_file(args):
    """1 ファイルをワーカ内で読み走査しヒット素片を返す純関数。

    ストリーミング化＝親に bytes 非常駐・abspath から読む。automaton 走査は raw 行。
    """
    relpath, abspath, symbol_list, lang_map, fallback = args
    raw = Path(abspath).read_bytes()
    text, enc, replaced, language, dialect = file_meta(relpath, raw, lang_map, fallback_chain=fallback)
    automaton_obj = automaton.build(symbol_list)
    found = []
    if automaton_obj is not None:
        ts_root = None
        ang_root = None
        spans = []
        if language in _AST_CHASERS:
            try:
                ts_root = parse_tree(language, text)
            except Exception:
                ts_root = None
            if language == "typescript":
                spans = inline_template_spans(text)
        for i, line in enumerate(text.split("\n"), start=1):
            symbols = list(automaton.scan_line(automaton_obj, line))
            if not symbols:
                continue
            cs = None
            if ts_root is not None:
                if spans and any(s <= i - 1 <= e for s, e in spans):
                    if ang_root is None:
                        try:
                            ang_root = parse_tree("angular_inline", text)
                        except Exception:
                            ang_root = None
                    cs = (extract_chase_symbols_from_root("angular_inline", ang_root, i)
                          if ang_root is not None else None)
                else:
                    cs = extract_chase_symbols_from_root(language, ts_root, i)
            for symbol in symbols:
                found.append((symbol, i, line, cs))
    return relpath, enc, replaced, language, dialect, found


def kinds_of(chase_symbols: ChaseSymbols) -> dict[str, str]:
    """ChaseSymbols の各シンボル→種別。同名は constant 優先（最後に書く）。"""
    out: dict[str, str] = {}
    for kind, names in (("setter", chase_symbols.setters), ("getter", chase_symbols.getters),
                        ("var", chase_symbols.vars), ("constant", chase_symbols.constants)):
        for n in names:
            out[n] = kind
    return out


def scan_hop(scan_symbols, scan_files, opts, nchunks):
    """1 hop の走査を chunks に分けて実行し、relpath 単位の集約済み結果を返す。

    `nchunks=1` の場合は単一 chunk として全 symbol を 1 度に走査する。`nchunks>1`
    の場合は chunk 別に Pool.map し、relpath 単位で found を集約してから
    (lineno, symbol) で再ソートする。いずれの経路も出力 byte は同値。

    戻り値: (pass_results, n_actual_chunks)
      - pass_results: [(relpath, enc, replaced, language, dialect, found)] の list
      - n_actual_chunks: 呼出側 diag.add("automaton_split", ...) 用
    """
    if nchunks <= 1:
        chunks = [scan_symbols]
    else:
        size = -(-len(scan_symbols) // nchunks)
        chunks = [scan_symbols[i:i + size]
                  for i in range(0, len(scan_symbols), size)] or [[]]
    hits_by_relpath: dict[str, list] = {}
    file_meta_by_relpath: dict[str, tuple] = {}
    for chunk in chunks:
        args = [(relpath, str(abspath), chunk, opts.lang_map, list(opts.encoding_fallback))
                for relpath, abspath in scan_files]
        if opts.jobs > 1:
            with multiprocessing.Pool(opts.jobs) as pool:
                res = pool.map(_scan_file, args)
        else:
            res = [_scan_file(a) for a in args]
        for relpath, enc, replaced, language, dialect, found in res:
            file_meta_by_relpath.setdefault(relpath, (enc, replaced, language, dialect))
            hits_by_relpath.setdefault(relpath, []).extend(found)
    pass_results = [(relpath, *file_meta_by_relpath[relpath],
                     sorted(hits_by_relpath[relpath], key=lambda t: (t[1], t[0])))
                    for relpath in sorted(hits_by_relpath)]
    return pass_results, len(chunks)
