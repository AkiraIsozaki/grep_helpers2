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
from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes
from grep_analyzer.fixedpoint import EngineOptions, run_fixedpoint
from grep_analyzer.ingest import parse_grep_line
from grep_analyzer.model import Hit
from grep_analyzer.snippet import build_snippet
from grep_analyzer.snippet._sanitize_line import _physical_lines
from grep_analyzer.walk import DEFAULT_EXCLUDE, collect_files


def _default_opts() -> EngineOptions:
    return EngineOptions(
        max_depth=10, min_specificity=2, stoplist_path=None, lang_map={},
        include=[], exclude=list(DEFAULT_EXCLUDE), jobs=1, follow_symlinks=False,
        max_file_bytes=5_000_000, max_symbols=100_000, max_paths=1000,
        use_ripgrep=ripgrep.available())


def run(
    input_dir: Path, output_dir: Path, source_root: Path,
    opts: EngineOptions | None = None,
) -> int:
    """input/*.grep を処理し、direct＋不動点 indirect を併合した TSV を出力する。"""
    diag = Diagnostics()
    output_dir.mkdir(parents=True, exist_ok=True)
    if opts is None:
        opts = _default_opts()
    lang_map = opts.lang_map
    files = collect_files(
        Path(source_root), include=opts.include, exclude=opts.exclude,
        follow_symlinks=opts.follow_symlinks,
        max_file_bytes=opts.max_file_bytes, diag=diag)

    fb = list(opts.encoding_fallback) or DEFAULT_FALLBACK
    for grep_file in sorted(Path(input_dir).glob("*.grep")):
        keyword = grep_file.stem
        if opts.resume and resume.is_complete(output_dir, keyword, opts):
            diag.add("resume_skipped", keyword)
            continue
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
        cur_relpath = None
        cur_ctx: tuple | None = None
        cur_is_file = False
        for raw_line in lines:
            parsed = parse_grep_line(raw_line)
            if parsed is None:
                diag.add("bad_grep_line", f"{grep_file.name}: {raw_line!r}")
                continue
            path_bytes, lineno, content_bytes = parsed
            # パスは生バイト由来＝os.fsdecode（FS codec＋surrogateescape）で FS と一致。
            # walk.py の relpath 表現とも統一され、SJIS 混在名でも is_file が当たる。
            relpath = os.fsdecode(path_bytes)
            content = content_bytes.decode(grep_enc, errors="replace")
            if relpath != cur_relpath:
                target = Path(source_root) / relpath
                cur_is_file = target.is_file()
                if cur_is_file:
                    file_text, enc, replaced = decode_bytes(target.read_bytes(), fb)
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
                cur_relpath = relpath
            if not cur_is_file:
                diag.add("missing_source", relpath)
                continue
            (file_text, enc, replaced, language, dialect,
             unsupported, tree_cache, phys_lines) = cur_ctx
            if replaced:
                diag.add("decode_replaced", str(relpath))
            if unsupported:
                diag.add("unsupported_shebang", str(relpath))
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

        indirect = run_fixedpoint(hits, Path(source_root), opts, diag, files=files)
        src_abs = str(Path(source_root).resolve())
        rows = [replace(h, file=f"{src_abs}/{h.file}") for h in hits + indirect]
        output_writer.finalize(output_dir, keyword, rows, opts)

    # SJIS 混在環境では FS 走査由来のファイル名に surrogateescape の孤立サロゲート
    # (U+DC80〜U+DCFF) が混じる。strict UTF-8 だと "surrogates not allowed" で全体が
    # 倒れるため backslashreplace で可視化（純UTF-8維持・原因ファイルは復元可能）。
    (output_dir / "diagnostics.txt").write_text(
        diag.render(detail_limit=opts.diagnostics_detail_limit,
                    exempt=SECTION_8_4_CATEGORIES),
        encoding="utf-8", errors="backslashreplace")
    return 0
