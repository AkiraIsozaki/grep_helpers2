"""CLIエントリ（spec §10.4）。Phase 1 は direct-only オプションのみ実装。"""

import argparse
from pathlib import Path

from grep_analyzer.pipeline import run


def main(argv: list[str] | None = None) -> int:
    """引数をパースし direct-only パイプラインを実行する。終了コードを返す。"""
    p = argparse.ArgumentParser(prog="grep_analyzer")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--source-root", required=True, dest="source_root")
    args = p.parse_args(argv)
    return run(
        input_dir=Path(args.input),
        output_dir=Path(args.output),
        source_root=Path(args.source_root),
    )
