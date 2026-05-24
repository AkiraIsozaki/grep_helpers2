import argparse
from pathlib import Path

from grep_analyzer.fixedpoint import EngineOptions
from grep_analyzer.pipeline import run
from grep_analyzer.walk import DEFAULT_EXCLUDE


def _parse_lang_map(spec: str | None) -> dict[str, str]:
    """`.ext=lang,.e2=l2` を {".ext":"lang"} に。空は {}（spec §10.4/§5.1手順1）。"""
    lang_map: dict[str, str] = {}
    if spec:
        for pair in spec.split(","):
            ext, _, lang = pair.partition("=")
            if ext and lang:
                lang_map[ext if ext.startswith(".") else "." + ext] = lang
    return lang_map


def _make_parser() -> argparse.ArgumentParser:
    """共通 ArgumentParser を組み立てて返す。"""
    parser = argparse.ArgumentParser(prog="grep_analyzer")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-root", required=True, dest="source_root")
    parser.add_argument("--max-depth", type=int, default=10, dest="max_depth")
    parser.add_argument("--min-specificity", type=int, default=2, dest="min_specificity")
    parser.add_argument("--stoplist", default=None)
    parser.add_argument("--lang-map", default=None, dest="lang_map")
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--exclude", action="append", default=None)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--follow-symlinks", action="store_true", dest="follow_symlinks")
    parser.add_argument("--max-file-bytes", type=int, default=5_000_000, dest="max_file_bytes")
    parser.add_argument("--max-symbols", type=int, default=100_000, dest="max_symbols")
    parser.add_argument("--max-paths", type=int, default=1000, dest="max_paths")
    parser.add_argument("--memory-limit", type=int, default=None, dest="memory_limit_mb")
    # rg prefilter は既定 OFF（opt-in）。実測で中規模実コードでは #1 LRU+#2 lazy parse が
    # savings を先取り済みで利得ゼロ、密集小ファイルでは subprocess コストで微減速だったため
    # （phase3-perf-report.md）。巨大木(>LRU 予算)向けに明示オプションとして温存する。
    parser.add_argument("--use-ripgrep", action="store_true", dest="use_ripgrep")
    parser.add_argument("--max-passes", type=int, default=8, dest="max_passes")
    parser.add_argument("--progress", default="off")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--output-encoding", default="utf-8-sig", dest="output_encoding")
    parser.add_argument("--encoding-fallback", default="cp932,euc-jp,latin-1",
                        dest="encoding_fallback")
    parser.add_argument("--max-rows-per-part", type=int, default=1_048_575,
                        dest="max_rows_per_part")
    parser.add_argument("--diagnostics-detail-limit", type=int, default=1000,
                        dest="diagnostics_detail_limit")
    return parser


def _opts_from(args: argparse.Namespace) -> EngineOptions:
    """parse 済み Namespace から EngineOptions を生成する。"""
    return EngineOptions(
        max_depth=args.max_depth, min_specificity=args.min_specificity,
        stoplist_path=Path(args.stoplist) if args.stoplist else None,
        lang_map=_parse_lang_map(args.lang_map), include=args.include,
        exclude=args.exclude if args.exclude is not None else list(DEFAULT_EXCLUDE),
        jobs=args.jobs, follow_symlinks=args.follow_symlinks,
        max_file_bytes=args.max_file_bytes, max_symbols=args.max_symbols,
        max_paths=args.max_paths,
        memory_limit_mb=args.memory_limit_mb, use_ripgrep=args.use_ripgrep,
        max_passes=args.max_passes, progress=args.progress,
        resume=args.resume,
        output_encoding=args.output_encoding,
        encoding_fallback=tuple(
            s for s in args.encoding_fallback.split(",") if s),
        max_rows_per_part=args.max_rows_per_part,
        diagnostics_detail_limit=args.diagnostics_detail_limit,
    )


def _build_opts(argv: list[str] | None = None) -> EngineOptions:
    """argv をパースし EngineOptions を返す（テスト・CLI 補助用）。"""
    args = _make_parser().parse_args(argv)
    return _opts_from(args)


def main(argv: list[str] | None = None) -> int:
    """引数をパースし direct＋不動点パイプラインを実行する（spec §10.4）。"""
    args = _make_parser().parse_args(argv)
    opts = _opts_from(args)
    return run(input_dir=Path(args.input), output_dir=Path(args.output),
               source_root=Path(args.source_root), opts=opts)
