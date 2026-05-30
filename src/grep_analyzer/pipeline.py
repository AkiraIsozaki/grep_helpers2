"""direct＋不動点 indirect 併合パイプライン。

Related: spec §15
"""

import os
from dataclasses import replace
from pathlib import Path

from grep_analyzer import output_writer, resume, ripgrep
from grep_analyzer.classify import classify_hit
from grep_analyzer.diagnostics import Diagnostics, SECTION_8_4_CATEGORIES
from grep_analyzer.dispatch import (
    detect_language,
    detect_shell_dialect,
    extension_resolves_language,
    shebang_dialect,
    shebang_language,
)
from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes, decode_with_memo
from grep_analyzer.fixedpoint import EngineOptions, run_fixedpoint_multi
from grep_analyzer.fixedpoint._encmemo import EncMemo
from grep_analyzer.fixedpoint._seed import initialize_state
from grep_analyzer.ingest import parse_grep_line
from grep_analyzer.model import Hit
from grep_analyzer.snippet import build_snippet
from grep_analyzer.snippet._sanitize_line import _physical_lines
from grep_analyzer.walk import (
    DEFAULT_EXCLUDE,
    collect_files_ex,
    is_contained_relpath,
    is_within_root,
)


def _default_opts() -> EngineOptions:
    return EngineOptions(
        max_depth=10, min_specificity=2, stoplist_path=None, lang_map={},
        include=[], exclude=list(DEFAULT_EXCLUDE), jobs=1, follow_symlinks=False,
        max_file_bytes=5_000_000, max_symbols=100_000, max_paths=1000)


def _effective_use_ripgrep(explicit: bool | None, total_bytes: int, threshold: int) -> bool:
    """tri-state を実効 bool に解決。明示(True/False)優先、None は rg 可用かつ総バイト>=閾値。"""
    if explicit is not None:
        return explicit
    return ripgrep.available() and total_bytes >= threshold


def run(
    input_dir: Path, output_dir: Path, source_root: Path,
    opts: EngineOptions | None = None,
) -> int:
    """input/*.grep を処理し、direct＋不動点 indirect を併合した TSV を出力する。

    全 keyword を1本の lock-step 走査（run_fixedpoint_multi）で前進させる転置構造
    （Phase4 Task4）。direct 構築は keyword 単位に前と byte 同値、enc_memo を run 全体で
    共有する。diagnostics は逐次版の単一 diag 追記順（walk → keyword ソート順に
    [direct, indirect]）を merge_in_order で再現する。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    if opts is None:
        opts = _default_opts()
    lang_map = opts.lang_map
    # --- 1. walk + 実効 use_ripgrep 解決（walk 由来診断は walk_diag に集約） ---
    walk_diag = Diagnostics()
    # collect_files_ex: 64KiB NUL prefix（collect_files の 8KiB より厳格）＋ total_bytes/unsafe_rels を prefilter 判定に使う
    files, total_bytes, unsafe_rels = collect_files_ex(
        Path(source_root), include=opts.include, exclude=opts.exclude,
        follow_symlinks=opts.follow_symlinks,
        max_file_bytes=opts.max_file_bytes, diag=walk_diag)
    explicit = opts.use_ripgrep
    effective = _effective_use_ripgrep(
        explicit, total_bytes, opts.ripgrep_threshold_bytes)
    opts = replace(opts, use_ripgrep=effective)
    if explicit is None and effective:
        walk_diag.add("prefilter_auto_engaged",
                      f"total_bytes={total_bytes} threshold={opts.ripgrep_threshold_bytes}")

    fb = list(opts.encoding_fallback) or DEFAULT_FALLBACK
    # run 共有 enc-memo：direct/seed/finalize の再読込で keyword をまたいで chardet を重複排除する
    # （jobs>1 の並列 SCAN は process-local の _WORKER_ENC を使い fork 越しに共有不可＝scan の
    # keyword 間重複排除は逐次経路のみ）。キーは str(abspath)（未正規化）だが memo は純粋なので
    # キー差異は冗長 chardet（性能）に留まり出力は不変。
    enc_memo = EncMemo()

    # --- 2. keyword 単位 direct 構築（既存ロジックを verbatim 流用） ---
    direct_hits: dict[str, list[Hit]] = {}
    direct_diag: dict[str, Diagnostics] = {}
    resume_skipped: list[str] = []
    for grep_file in sorted(Path(input_dir).glob("*.grep")):
        keyword = grep_file.stem
        # H-2 resume: 完了済 keyword は direct も states も finalize も行わずスキップ。
        if opts.resume and resume.is_complete(output_dir, keyword, opts):
            resume_skipped.append(keyword)
            continue
        kw_diag = Diagnostics()
        direct_diag[keyword] = kw_diag
        grep_bytes = grep_file.read_bytes()
        # content 復号用にファイル単位で文字コードを 1 回だけ判定（chardet 1回・行間一貫）。
        # パスは生バイトのまま os.fsdecode するため、ここでは encoding のみ使う。
        _, grep_enc, _ = decode_bytes(grep_bytes, fb)
        hits: list[Hit] = []

        lines = grep_bytes.split(b"\n")
        if lines and lines[-1] == b"":
            lines.pop()                       # 末尾改行による空要素（splitlines 相当）
        # grep 出力はファイル単位でヒットがまとまる（grep -rn / rg）。直前 1 ファイル分の
        # 読込・復号・言語判定・パース木をキャッシュし、同一ファイルの連続ヒットで
        # ディスク再読込と tree-sitter 再パースを抑止する（追加メモリは O(1)＝1 ファイル分）。
        # 診断（decode_replaced/unsupported_shebang/missing_source）は §10.3 の件数・順序を
        # 保つため従来どおりヒット行ごとに発火する。
        # cur_ctx は relpath 単位のキャッシュ。欠落ファイルでは None を入れ、
        # 「cur_ctx is None ⇔ 現 relpath は非ファイル」を構造的不変条件にする
        # （別フラグと cur_ctx の手動同期を排し、欠落診断の取りこぼしを防ぐ）。
        cur_relpath = None
        cur_ctx: tuple | None = None
        for raw_line in lines:
            parsed = parse_grep_line(raw_line)
            if parsed is None:
                kw_diag.add("bad_grep_line", f"{grep_file.name}: {raw_line!r}")
                continue
            path_bytes, lineno, content_bytes = parsed
            # パスは生バイト由来＝os.fsdecode（FS codec＋surrogateescape）で FS と一致。
            # walk.py の relpath 表現とも統一され、SJIS 混在名でも is_file が当たる。
            relpath = os.fsdecode(path_bytes)
            content = content_bytes.decode(grep_enc, errors="replace")
            if relpath != cur_relpath:
                cur_relpath = relpath
                target = Path(source_root) / relpath
                if is_contained_relpath(relpath) and target.is_file() and is_within_root(source_root, target):
                    file_text, enc, replaced = decode_with_memo(
                        enc_memo, str(target), target.read_bytes(), fb)
                    sample = file_text[:4096]
                    language = detect_language(relpath, sample, lang_map)
                    dialect = (detect_shell_dialect(relpath, sample)
                               if language == "shell" else "bourne")
                    unsupported = (
                        not extension_resolves_language(relpath, lang_map)
                        and shebang_dialect(sample) is not None  # シェバン行が存在
                        and shebang_language(sample) is None      # 対応言語に解決しない
                    )
                    cur_ctx = (file_text, enc, replaced, language, dialect,
                               unsupported, {}, _physical_lines(file_text))
                else:
                    cur_ctx = None
            if cur_ctx is None:
                kw_diag.add("missing_source", relpath)
                continue
            (file_text, enc, replaced, language, dialect,
             unsupported, tree_cache, phys_lines) = cur_ctx
            if replaced:
                kw_diag.add("decode_replaced", str(relpath))
            if unsupported:
                kw_diag.add("unsupported_shebang", str(relpath))
            category, confidence = classify_hit(
                language, dialect, file_text, lineno, content, cache=tree_cache)
            hits.append(Hit(
                keyword=keyword, language=language, file=relpath, lineno=lineno,
                ref_kind="direct", category=category, category_sub="",
                usage_summary=f"{category} ({language})", via_symbol="",
                chain=f"{keyword}@{relpath}:{lineno}",
                snippet=build_snippet(language, dialect, file_text, lineno,
                                      cache=tree_cache, lines=phys_lines),
                encoding=enc + (" 要確認" if replaced else ""), confidence=confidence,
            ))
        direct_hits[keyword] = hits

    # --- 3. states 構築（同一 keyword ソート順・keyword 別 indirect_diag） ---
    indirect_diag: dict[str, Diagnostics] = {}
    states_by_kw = {}
    for kw in direct_hits:                    # dict は挿入順＝glob ソート順を保持
        indirect_diag[kw] = Diagnostics()
        states_by_kw[kw] = initialize_state(
            direct_hits[kw], Path(source_root), opts, indirect_diag[kw],
            enc_memo=enc_memo)

    # --- 4. 1本の lock-step pass ---
    indirect = run_fixedpoint_multi(
        states_by_kw, Path(source_root), opts,
        files=files, unsafe_rels=unsafe_rels, enc_memo=enc_memo)

    # --- 5. finalize（keyword ソート順＝従来 glob 順と同一） ---
    src_abs = str(Path(source_root).resolve())
    for kw in sorted(states_by_kw):
        rows = [replace(h, file=f"{src_abs}/{h.file}")
                for h in direct_hits[kw] + indirect[kw]]
        output_writer.finalize(output_dir, kw, rows, opts)

    # --- 6. diagnostics 併合（逐次版の単一 diag 追記順を再現） ---
    # 逐次版順序: walk → keyword ソート順に [その keyword の direct diags, 続けて
    # その keyword の initialize_state + fixedpoint indirect diags]。merge_in_order は
    # カテゴリ別 detail を与えた順に連結し counts を合算する。
    # NOTE(Task5): keyword 横断の DETAIL 順 byte 一致（特に automaton_split を含む共有 hop
    # 診断）は Phase4 Task5 の課題。本タスクのゲートは golden（TSV + diagnostics SUMMARY 件数）
    # と per-keyword TSV byte 一致。counts は merge_in_order の合算で逐次版と一致する。
    # 加えて resume_skipped の DETAIL 順も変化している（旧: glob ループ中に inline 追記され
    # 他診断とインターリーブ／新: 末尾に sorted 順でまとめて append）。件数は不変だが、これも
    # Task5 の detail-order 負債の一部であり、Task5 が見落とさないよう明記する。
    diag = Diagnostics()
    ordered_diags = [walk_diag]
    for kw in sorted(states_by_kw):
        ordered_diags.append(direct_diag[kw])
        ordered_diags.append(indirect_diag[kw])
    diag.merge_in_order(ordered_diags)
    for kw in sorted(resume_skipped):
        diag.add("resume_skipped", kw)

    # SJIS 混在環境では FS 走査由来のファイル名に surrogateescape の孤立サロゲート
    # (U+DC80〜U+DCFF) が混じる。strict UTF-8 だと "surrogates not allowed" で全体が
    # 倒れるため backslashreplace で可視化（純UTF-8維持・原因ファイルは復元可能）。
    (output_dir / "diagnostics.txt").write_text(
        diag.render(detail_limit=opts.diagnostics_detail_limit,
                    exempt=SECTION_8_4_CATEGORIES),
        encoding="utf-8", errors="backslashreplace")
    return 0
