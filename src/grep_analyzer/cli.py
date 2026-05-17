import argparse
from pathlib import Path

from grep_analyzer.fixedpoint import EngineOptions
from grep_analyzer.pipeline import run
from grep_analyzer.walk import DEFAULT_EXCLUDE


def _parse_lang_map(spec: str | None) -> dict[str, str]:
    """`.ext=lang,.e2=l2` を {".ext":"lang"} に。空は {}（spec §10.4/§5.1手順1）。"""
    out: dict[str, str] = {}
    if spec:
        for pair in spec.split(","):
            ext, _, lang = pair.partition("=")
            if ext and lang:
                out[ext if ext.startswith(".") else "." + ext] = lang
    return out


def main(argv: list[str] | None = None) -> int:
    """引数をパースし direct＋不動点パイプラインを実行する（spec §10.4）。"""
    p = argparse.ArgumentParser(prog="grep_analyzer")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--source-root", required=True, dest="source_root")
    p.add_argument("--max-depth", type=int, default=10, dest="max_depth")
    p.add_argument("--min-specificity", type=int, default=2, dest="min_specificity")
    p.add_argument("--stoplist", default=None)
    p.add_argument("--lang-map", default=None, dest="lang_map")
    p.add_argument("--include", action="append", default=[])
    p.add_argument("--exclude", action="append", default=None)
    p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--follow-symlinks", action="store_true", dest="follow_symlinks")
    p.add_argument("--max-file-bytes", type=int, default=5_000_000, dest="max_file_bytes")
    p.add_argument("--max-symbols", type=int, default=100_000, dest="max_symbols")
    p.add_argument("--max-paths", type=int, default=1000, dest="max_paths")
    p.add_argument("--memory-limit", type=int, default=None, dest="memory_limit_mb")
    p.add_argument("--use-ripgrep", action="store_true", dest="use_ripgrep")
    p.add_argument("--max-passes", type=int, default=8, dest="max_passes")
    p.add_argument("--progress", default="off")
    args = p.parse_args(argv)
    opts = EngineOptions(
        max_depth=args.max_depth, min_specificity=args.min_specificity,
        stoplist_path=Path(args.stoplist) if args.stoplist else None,
        lang_map=_parse_lang_map(args.lang_map), include=args.include,
        exclude=args.exclude if args.exclude is not None else list(DEFAULT_EXCLUDE),
        jobs=args.jobs, follow_symlinks=args.follow_symlinks,
        max_file_bytes=args.max_file_bytes, max_symbols=args.max_symbols,
        max_paths=args.max_paths,
        memory_limit_mb=args.memory_limit_mb, use_ripgrep=args.use_ripgrep,
        max_passes=args.max_passes, progress=args.progress,
    )
    return run(input_dir=Path(args.input), output_dir=Path(args.output),
               source_root=Path(args.source_root), opts=opts)
