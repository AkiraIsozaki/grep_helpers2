"""direct＋不動点 indirect 併合パイプライン（spec §15）。"""

from dataclasses import replace
from pathlib import Path

from grep_analyzer import output_writer, resume
from grep_analyzer.classify import classify_hit
from grep_analyzer.diagnostics import Diagnostics, SECTION_8_4_CATEGORIES
from grep_analyzer.dispatch import (
    detect_language,
    detect_shell_dialect,
    extension_resolves_language,
    shebang_dialect,
)
from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes
from grep_analyzer.fixedpoint import EngineOptions, run_fixedpoint
from grep_analyzer.ingest import parse_grep_line
from grep_analyzer.model import Hit
from grep_analyzer.snippet import build_snippet
from grep_analyzer.walk import DEFAULT_EXCLUDE, collect_files


def _default_opts() -> EngineOptions:
    return EngineOptions(
        max_depth=10, min_specificity=2, stoplist_path=None, lang_map={},
        include=[], exclude=list(DEFAULT_EXCLUDE), jobs=1, follow_symlinks=False,
        max_file_bytes=5_000_000, max_symbols=100_000, max_paths=1000)


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
        text, _, _ = decode_bytes(grep_file.read_bytes(), fb)
        hits: list[Hit] = []

        for raw_line in text.splitlines():
            parsed = parse_grep_line(raw_line)
            if parsed is None:
                diag.add("bad_grep_line", f"{grep_file.name}: {raw_line!r}")
                continue
            rel, lineno, content = parsed
            target = Path(source_root) / rel
            if not target.is_file():
                diag.add("missing_source", str(rel))
                continue
            file_text, enc, replaced = decode_bytes(target.read_bytes(), fb)
            if replaced:
                diag.add("decode_replaced", str(rel))
            sample = file_text[:4096]
            language = detect_language(rel, sample, lang_map)
            dialect = detect_shell_dialect(rel, sample) if language == "shell" else "bourne"
            if (
                not extension_resolves_language(rel, lang_map)
                and language != "shell"
                and shebang_dialect(sample) == "other"
            ):
                diag.add("unsupported_shebang", str(rel))
            category, confidence = classify_hit(language, dialect, file_text, lineno, content)
            hits.append(Hit(
                keyword=keyword, language=language, file=rel, lineno=lineno,
                ref_kind="direct", category=category, category_sub="",
                usage_summary=f"{category} ({language})", via_symbol="",
                chain=f"{keyword}@{rel}:{lineno}",
                snippet=build_snippet(language, dialect, file_text, lineno),
                encoding=enc + (" 要確認" if replaced else ""), confidence=confidence,
            ))

        indirect = run_fixedpoint(hits, Path(source_root), opts, diag, files=files)
        src_abs = str(Path(source_root).resolve())
        rows = [replace(h, file=f"{src_abs}/{h.file}") for h in hits + indirect]
        output_writer.finalize(output_dir, keyword, rows, opts)

    (output_dir / "diagnostics.txt").write_text(
        diag.render(detail_limit=opts.diagnostics_detail_limit,
                    exempt=SECTION_8_4_CATEGORIES),
        encoding="utf-8")
    return 0
