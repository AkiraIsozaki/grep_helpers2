"""scan worker と scan-hop オーケストレーション。

`_scan_file` は multiprocessing.Pool 用のトップレベル純関数（pickle 制約）。
追跡状態オブジェクトは worker に渡さず、main process で構築した args タプル
のみ渡す。`scan_hop` は呼出側から渡された必要プリミティブだけを引数に取り、
worker からの戻り値を呼出側で追跡状態へ反映する（worker isolation 厳守）。

`file_meta` / `kinds_of` は追跡状態を引数に取らない純関数 helper として
`_seed` / `_ingest` / `_finalize` から共有 import される（pickle 制約と矛盾なし）。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [A]
"""

import multiprocessing
from pathlib import Path

from grep_analyzer import automaton
from grep_analyzer.chase import extract_chase_symbols
from grep_analyzer.dispatch import detect_language, detect_shell_dialect
from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes


def file_meta(rel: str, raw: bytes, lang_map: dict[str, str], fallback_chain=None):
    """1 度だけデコードし (text, encoding, replaced, language, dialect) を返す。"""
    chain = list(fallback_chain) if fallback_chain else DEFAULT_FALLBACK
    text, enc, replaced = decode_bytes(raw, chain)
    language = detect_language(rel, text[:4096], lang_map)
    dialect = detect_shell_dialect(rel, text[:4096]) if language == "shell" else "bourne"
    return text, enc, replaced, language, dialect


def _scan_file(args):
    """1 ファイルをワーカ内で読み走査しヒット素片を返す純関数。

    ストリーミング化＝親に bytes 非常駐・abspath から読む。automaton 走査は raw 行。
    """
    rel, abspath, sym_list, lang_map, fallback = args
    raw = Path(abspath).read_bytes()
    text, enc, replaced, language, dialect = file_meta(rel, raw, lang_map, fallback_chain=fallback)
    automaton_obj = automaton.build(sym_list)
    found = []
    if automaton_obj is not None:
        for i, line in enumerate(text.split("\n"), start=1):
            for sym in automaton.scan_line(automaton_obj, line):
                found.append((sym, i, line))
    return rel, enc, replaced, language, dialect, found


def kinds_of(language: str, dialect: str, line: str) -> dict[str, str]:
    """1 行の各シンボル→種別。同名は逆順ループで最後に書き込む constant が優先。"""
    chase_symbols = extract_chase_symbols(language, dialect, line)
    out: dict[str, str] = {}
    for kind, names in (("setter", chase_symbols.setters), ("getter", chase_symbols.getters),
                        ("var", chase_symbols.vars), ("constant", chase_symbols.constants)):
        for n in names:
            out[n] = kind
    return out


def scan_hop(scan_syms, scan_files, opts, nchunks):
    """1 hop の走査を chunks に分けて実行し、rel 単位の集約済み結果を返す。

    `nchunks=1` の場合は単一 chunk として全 sym を 1 度に走査する（既存
    fixedpoint.py L260-272 の単発経路と byte 同値）。`nchunks>1` の場合は
    chunk 別に Pool.map し、rel 単位で found を集約してから (lineno, sym) で
    再ソート（既存 L273-289 と byte 同値）。

    戻り値: (pass_results, n_actual_chunks)
      - pass_results: [(rel, enc, replaced, language, dialect, found)] の list
      - n_actual_chunks: 呼出側 diag.add("automaton_split", ...) 用
    """
    if nchunks <= 1:
        chunks = [scan_syms]
    else:
        size = -(-len(scan_syms) // nchunks)
        chunks = [scan_syms[i:i + size]
                  for i in range(0, len(scan_syms), size)] or [[]]
    hits_by_relpath: dict[str, list] = {}
    file_meta_by_relpath: dict[str, tuple] = {}
    for chunk in chunks:
        args = [(rel, str(abspath), chunk, opts.lang_map, list(opts.encoding_fallback))
                for rel, abspath in scan_files]
        if opts.jobs > 1:
            with multiprocessing.Pool(opts.jobs) as pool:
                res = pool.map(_scan_file, args)
        else:
            res = [_scan_file(a) for a in args]
        for rel, enc, replaced, language, dialect, found in res:
            file_meta_by_relpath.setdefault(rel, (enc, replaced, language, dialect))
            hits_by_relpath.setdefault(rel, []).extend(found)
    pass_results = [(rel, *file_meta_by_relpath[rel],
                     sorted(hits_by_relpath[rel], key=lambda t: (t[1], t[0])))
                    for rel in sorted(hits_by_relpath)]
    return pass_results, len(chunks)
