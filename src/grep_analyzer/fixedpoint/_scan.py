"""scan worker と scan-hop オーケストレーション。

`_scan_file` は multiprocessing.Pool 用のトップレベル純関数（pickle 制約）。
追跡状態オブジェクトは worker に渡さず、main process で構築した args タプル
のみ渡す。`scan_hop` は呼出側から渡された必要プリミティブだけを引数に取り、
worker からの戻り値を呼出側で追跡状態へ反映する（worker isolation 厳守）。

`file_meta` / `kinds_of` は追跡状態を引数に取らない純関数 helper として
`_seed` / `_ingest` / `_finalize` から共有 import される（pickle 制約と矛盾なし）。
"""

import hashlib
import json
import multiprocessing
import tempfile
from collections import OrderedDict
from pathlib import Path

from grep_analyzer import automaton
from grep_analyzer.chase import extract_chase_symbols_from_root
from grep_analyzer.classifiers import _AST_CHASERS
from grep_analyzer.classifiers.ts_classifier import parse_tree
from grep_analyzer.dispatch import detect_language, detect_shell_dialect
from grep_analyzer.embed_preprocess import inline_template_spans
from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes, decode_with_memo
from grep_analyzer.fixedpoint._encmemo import EncMemo
from grep_analyzer.fixedpoint._encmemo import _DEFAULT_MAX as _ENC_MEMO_MAX
from grep_analyzer.model import ChaseSymbols


def _meta_from_text(relpath, text, enc, replaced, lang_map):
    """(text,enc,replaced) ＋言語/方言判定（text[:4096] サンプリング）を 5-tuple に組む。

    file_meta と _read_meta の enc_memo 経路が共有する単一情報源（golden 不変の要）。
    """
    language = detect_language(relpath, text[:4096], lang_map)
    dialect = detect_shell_dialect(relpath, text[:4096]) if language == "shell" else "bourne"
    return text, enc, replaced, language, dialect


def file_meta(relpath: str, raw: bytes, lang_map: dict[str, str], fallback_chain=None):
    """1 度だけデコードし (text, encoding, replaced, language, dialect) を返す。"""
    chain = list(fallback_chain) if fallback_chain else DEFAULT_FALLBACK
    text, enc, replaced = decode_bytes(raw, chain)
    return _meta_from_text(relpath, text, enc, replaced, lang_map)


def meta_via_memo(enc_memo, key, relpath, raw, lang_map, fallback):
    """file_meta と byte 同値だが enc_memo 経由で chardet を抑止する 5-tuple（単一情報源）。

    key は str(abspath)（未正規化）。memo は純粋な再計算メモ化ゆえ key の差異
    （例: source_root 非正規化）は冗長な chardet（性能）を生むだけで出力は不変。
    """
    text, enc, replaced = decode_with_memo(enc_memo, key, raw, fallback)
    return _meta_from_text(relpath, text, enc, replaced, lang_map)


_FILE_CACHE_BUDGET = 64 * 1024 * 1024   # 復号テキスト常駐の上限（文字数の概算予算）


class _FileCache:
    """abspath→(text,enc,replaced,language,dialect) の予算つき LRU。

    hop 間で再読込・再復号・再言語判定を抑止する。tree は保持しない
    （巨大ファイルで予算が破綻するため。再 parse は lazy parse が回避）。
    キーは abspath（run 内で一意・ソースは run 中不変前提でメモ化は出力不変）。

    予算は復号テキストの **文字数** 合計の概算上限（多バイト文字では実バイトは
    最大数倍）。`len(self._d) > 1` ガードにより、予算超の単一巨大ファイルは退避せず
    常駐させる（thrash 回避）。ゆえに常駐は厳密には O(最大ファイル長)＝定数上限内で
    実質 O(1)。並列時は worker ごとに本クラスを持つため予算は jobs 分割する。
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


def _read_meta(relpath, abspath, lang_map, fallback, cache, enc_memo=None):
    """file_meta 結果を階層キャッシュ経由で取得。

    上段=テキストキャッシュ(cache)、下段=enc-memo(enc_memo)。cache hit は即返す。
    cache miss かつ enc_memo がある場合は decode_with_memo で chardet を回避し、
    file_meta と **byte 同値** の 5 タプルを text[:4096] サンプリングで再構築する。
    cache=None は従来どおり毎回読込（enc_memo の効果は decode 段にのみ及ぶ）。
    """
    if cache is not None:
        hit = cache.get(abspath)
        if hit is not None:
            return hit                       # 5要素 (text,enc,replaced,language,dialect)
    if enc_memo is None:
        meta = file_meta(relpath, Path(abspath).read_bytes(), lang_map, fallback_chain=fallback)
    else:
        raw = Path(abspath).read_bytes()
        meta = meta_via_memo(enc_memo, abspath, relpath, raw, lang_map, fallback)
    if cache is not None:
        cache.put(abspath, meta)
    return meta


def _scan_one(relpath, abspath, automaton_obj, lang_map, fallback, cache=None, enc_memo=None):
    """1 ファイルを **構築済 automaton** で読み走査しヒット素片を返す純関数。

    ストリーミング化＝親に bytes 非常駐・abspath から読む。automaton 走査はデコード済
    テキストの各行。automaton はチャンク単位で 1 度だけ構築し全ファイルで使い回す
    （scan_line は iter のみで非破壊＝再利用安全）。
    """
    try:
        text, enc, replaced, language, dialect = _read_meta(
            relpath, abspath, lang_map, fallback, cache, enc_memo)
    except OSError:
        # walk 後の TOCTOU（消失/権限変化）等。run 全体を落とさず空ヒットへ降格。
        return relpath, "utf-8", False, "c", "bourne", []
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


# multiprocessing ワーカ：Pool は run 単位で 1 度だけ生成し全 hop/chunk で再利用する。
# initializer では lang_map / fallback / 空 LRU のみ確定し、automaton はチャンク到来時に
# signature（= chunk 内容のハッシュ）変化を見て再構築する（symbols は temp ファイル経由）。
# sig が内容ハッシュなので同一 symbol 集合の hop 連続では再構築をスキップする。
# automaton を各ワーカが明示構築するため start method 非依存（fork/spawn いずれも可）。
# worker LRU は Pool 永続化により hop 間で効く（#1 の並列版）。常駐は worker ごとに独立な
# ため予算は jobs 分割し、全 worker 合計を単一 run と同じ上限（O(1)）に保つ。
_WORKER_AUTOMATON = None
_WORKER_SIG = None
_WORKER_LANG_MAP: dict[str, str] | None = None
_WORKER_FALLBACK: list[str] | None = None
_WORKER_CACHE: "_FileCache | None" = None
_WORKER_ENC: "EncMemo | None" = None


def _worker_init(lang_map, fallback, jobs) -> None:
    """Pool worker 初期化（run 単位 1 回）。automaton は chunk 到来時に遅延構築。"""
    global _WORKER_LANG_MAP, _WORKER_FALLBACK, _WORKER_CACHE, _WORKER_SIG, _WORKER_AUTOMATON
    global _WORKER_ENC
    _WORKER_LANG_MAP = lang_map
    _WORKER_FALLBACK = fallback
    # worker ごとに独立 LRU を持つため予算を jobs 分割（合計常駐 ≤ 単一 run 上限）。
    _WORKER_CACHE = _FileCache(budget=_FILE_CACHE_BUDGET // max(1, jobs))
    # worker ごとに独立 LRU ＝予算を jobs 分割し合計常駐を有界化（_FileCache と同論拠）。
    _WORKER_ENC = EncMemo(max_entries=max(1, _ENC_MEMO_MAX // max(1, jobs)))
    _WORKER_SIG = None
    _WORKER_AUTOMATON = None


def _scan_file_worker(args):
    """Pool worker 本体：signature 変化時のみ automaton を再構築して 1 ファイル走査。"""
    relpath, abspath, sig, sym_path = args
    global _WORKER_AUTOMATON, _WORKER_SIG
    if sig != _WORKER_SIG:
        with open(sym_path, encoding="utf-8") as f:
            _WORKER_AUTOMATON = automaton.build(json.load(f))
        _WORKER_SIG = sig
    return _scan_one(relpath, abspath, _WORKER_AUTOMATON,
                     _WORKER_LANG_MAP, _WORKER_FALLBACK,
                     cache=_WORKER_CACHE, enc_memo=_WORKER_ENC)


def make_pool(opts):
    """jobs>1 のとき run 単位の Pool を 1 度だけ生成する（jobs<=1 は None）。"""
    if opts.jobs <= 1:
        return None
    return multiprocessing.Pool(
        opts.jobs, initializer=_worker_init,
        initargs=(opts.lang_map, list(opts.encoding_fallback), opts.jobs))


def kinds_of(chase_symbols: ChaseSymbols) -> dict[str, str]:
    """ChaseSymbols の各シンボル→種別。同名は constant 優先（最後に書く）。"""
    out: dict[str, str] = {}
    for kind, names in (("setter", chase_symbols.setters), ("getter", chase_symbols.getters),
                        ("var", chase_symbols.vars), ("constant", chase_symbols.constants)):
        for n in names:
            out[n] = kind
    return out


def scan_hop(scan_symbols, scan_files, opts, nchunks, file_cache=None, pool=None, enc_memo=None):
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
        # Pool は run 単位で 1 度だけ生成され（make_pool）、chunk の automaton は worker 側で
        # signature(= chunk 内容ハッシュ)変化時のみ再構築する。symbols は temp ファイル経由。
        # sig を内容ハッシュにすることで (a) temp パス再利用での stale automaton を排除し、
        # (b) 同一 symbol 集合の hop 連続で worker の再構築をスキップできる。
        if opts.jobs > 1 and pool is not None:
            sig = hashlib.sha1(json.dumps(chunk).encode("utf-8")).hexdigest()
            sf = tempfile.NamedTemporaryFile("w", suffix=".sym", delete=False,
                                             encoding="utf-8")
            sym_path = sf.name
            try:
                with sf:
                    json.dump(chunk, sf)
                res = pool.map(
                    _scan_file_worker,
                    [(relpath, str(abspath), sig, sym_path)
                     for relpath, abspath in scan_files])
            finally:
                Path(sym_path).unlink(missing_ok=True)
        else:
            automaton_obj = automaton.build(chunk)
            res = [_scan_one(relpath, str(abspath), automaton_obj,
                             opts.lang_map, fallback,
                             cache=file_cache, enc_memo=enc_memo)
                   for relpath, abspath in scan_files]
        for relpath, enc, replaced, language, dialect, found in res:
            file_meta_by_relpath.setdefault(relpath, (enc, replaced, language, dialect))
            hits_by_relpath.setdefault(relpath, []).extend(found)
    pass_results = [(relpath, *file_meta_by_relpath[relpath],
                     sorted(hits_by_relpath[relpath], key=lambda t: (t[1], t[0])))
                    for relpath in sorted(hits_by_relpath)]
    return pass_results, len(chunks)
