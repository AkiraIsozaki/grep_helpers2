"""scan worker と scan-hop オーケストレーション。

`_scan_file` は multiprocessing.Pool 用のトップレベル純関数（pickle 制約）。
追跡状態オブジェクトは worker に渡さず、main process で構築した args タプル
のみ渡す。`scan_hop` は呼出側から渡された必要プリミティブだけを引数に取り、
worker からの戻り値を呼出側で追跡状態へ反映する（worker isolation 厳守）。

`file_meta` / `kinds_of` は追跡状態を引数に取らない純関数 helper として
`_seed` / `_ingest` / `_finalize` から共有 import される（pickle 制約と矛盾なし）。
"""

import multiprocessing
from collections import OrderedDict
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


_FILE_CACHE_BUDGET = 64 * 1024 * 1024   # 復号テキスト常駐の上限（定数＝常駐 O(1)）


class _FileCache:
    """abspath→(text,enc,replaced,language,dialect) の byte 予算つき LRU。

    hop 間で再読込・再復号・再言語判定を抑止する。tree は保持しない
    （巨大ファイルで予算が破綻するため。再 parse は lazy parse が回避）。
    キーは abspath（run 内で一意・ソースは run 中不変前提でメモ化は出力不変）。
    """

    def __init__(self, budget: int = _FILE_CACHE_BUDGET):
        self.budget = budget
        self._d: "OrderedDict[str, tuple]" = OrderedDict()
        self._bytes = 0

    def get(self, key: str):
        v = self._d.get(key)
        if v is not None:
            self._d.move_to_end(key)
        return v

    def put(self, key: str, value: tuple) -> None:
        if key in self._d:
            self._bytes -= len(self._d[key][0])
            del self._d[key]
        self._d[key] = value
        self._bytes += len(value[0])
        while self._bytes > self.budget and len(self._d) > 1:
            _, old = self._d.popitem(last=False)
            self._bytes -= len(old[0])


def make_file_cache() -> _FileCache:
    """run 単位の hop 間ファイルキャッシュを生成する。"""
    return _FileCache()


def _read_meta(relpath, abspath, lang_map, fallback, cache):
    """file_meta 結果を cache 経由で取得（cache=None は従来どおり毎回読込）。"""
    if cache is not None:
        hit = cache.get(abspath)
        if hit is not None:
            return hit
    meta = file_meta(relpath, Path(abspath).read_bytes(), lang_map, fallback_chain=fallback)
    if cache is not None:
        cache.put(abspath, meta)
    return meta


def _scan_one(relpath, abspath, automaton_obj, lang_map, fallback, cache=None):
    """1 ファイルを **構築済 automaton** で読み走査しヒット素片を返す純関数。

    ストリーミング化＝親に bytes 非常駐・abspath から読む。automaton 走査はデコード済
    テキストの各行。automaton はチャンク単位で 1 度だけ構築し全ファイルで使い回す
    （scan_line は iter のみで非破壊＝再利用安全）。
    """
    text, enc, replaced, language, dialect = _read_meta(
        relpath, abspath, lang_map, fallback, cache)
    found = []
    if automaton_obj is not None:
        is_ast = language in _AST_CHASERS
        ts_root = None
        ang_root = None
        spans = []
        parsed = False                      # 最初の symbol ヒットまで parse を遅延
        for i, line in enumerate(text.split("\n"), start=1):
            symbols = list(automaton.scan_line(automaton_obj, line))
            if not symbols:
                continue
            if is_ast and not parsed:
                parsed = True
                try:
                    ts_root = parse_tree(language, text)
                except Exception:
                    ts_root = None
                if ts_root is not None and language == "typescript":
                    spans = inline_template_spans(text)
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


def _scan_file(args):
    """後方互換の 1 ファイル走査エントリ（symbol_list から automaton を構築して委譲）。

    引数タプルは従来どおり `(relpath, abspath, symbol_list, lang_map, fallback)`。
    本番のホット経路（scan_hop）は automaton をチャンク単位で 1 度だけ構築するため
    この関数を使わない。単体テスト等の 1 ファイル走査の互換のため温存する。
    """
    relpath, abspath, symbol_list, lang_map, fallback = args
    return _scan_one(relpath, abspath, automaton.build(symbol_list), lang_map, fallback)


# multiprocessing ワーカ：automaton / lang_map / fallback はワーカ毎に initializer で
# 1 度だけ構築・保持する（pickle 制約下でチャンク内の全ファイルが共有＝再構築回避）。
# automaton を initializer で各ワーカが明示構築するため start method 非依存
# （fork でも spawn でも正しく初期化される。グローバルは fork 継承に依存しない）。
_WORKER_AUTOMATON = None
_WORKER_LANG_MAP: dict[str, str] | None = None
_WORKER_FALLBACK: list[str] | None = None


def _worker_init(symbol_list, lang_map, fallback) -> None:
    """Pool worker 初期化：チャンク symbol から automaton を 1 度だけ構築。"""
    global _WORKER_AUTOMATON, _WORKER_LANG_MAP, _WORKER_FALLBACK
    _WORKER_AUTOMATON = automaton.build(symbol_list)
    _WORKER_LANG_MAP = lang_map
    _WORKER_FALLBACK = fallback


def _scan_file_worker(args):
    """Pool worker 本体：initializer 構築済の automaton を使って 1 ファイル走査。"""
    relpath, abspath = args
    return _scan_one(relpath, abspath, _WORKER_AUTOMATON, _WORKER_LANG_MAP, _WORKER_FALLBACK)


def kinds_of(chase_symbols: ChaseSymbols) -> dict[str, str]:
    """ChaseSymbols の各シンボル→種別。同名は constant 優先（最後に書く）。"""
    out: dict[str, str] = {}
    for kind, names in (("setter", chase_symbols.setters), ("getter", chase_symbols.getters),
                        ("var", chase_symbols.vars), ("constant", chase_symbols.constants)):
        for n in names:
            out[n] = kind
    return out


def scan_hop(scan_symbols, scan_files, opts, nchunks, file_cache=None):
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
    fallback = list(opts.encoding_fallback)
    for chunk in chunks:
        # automaton はチャンク単位で 1 度だけ構築する（旧実装はファイル毎に再構築していた）。
        # Pool はチャンク毎に automaton が変わるためチャンク毎生成（degrade で nchunks が
        # 大きいと fork×jobs×nchunks のプロセス起動コストが残る＝将来の最適化余地）。
        if opts.jobs > 1:
            with multiprocessing.Pool(
                    opts.jobs, initializer=_worker_init,
                    initargs=(chunk, opts.lang_map, fallback)) as pool:
                res = pool.map(_scan_file_worker,
                               [(relpath, str(abspath)) for relpath, abspath in scan_files])
        else:
            automaton_obj = automaton.build(chunk)
            res = [_scan_one(relpath, str(abspath), automaton_obj,
                             opts.lang_map, fallback, cache=file_cache)
                   for relpath, abspath in scan_files]
        for relpath, enc, replaced, language, dialect, found in res:
            file_meta_by_relpath.setdefault(relpath, (enc, replaced, language, dialect))
            hits_by_relpath.setdefault(relpath, []).extend(found)
    pass_results = [(relpath, *file_meta_by_relpath[relpath],
                     sorted(hits_by_relpath[relpath], key=lambda t: (t[1], t[0])))
                    for relpath in sorted(hits_by_relpath)]
    return pass_results, len(chunks)
