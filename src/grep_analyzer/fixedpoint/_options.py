"""EngineOptions: エンジン挙動パラメータ（spec §8/§10.4）。

`run_fixedpoint` 経由でエンジン内部で参照される。`fixedpoint/__init__.py`
から `from grep_analyzer.fixedpoint import EngineOptions` で再 export される。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [A]
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EngineOptions:
    """spec §8/§10.4 のエンジン挙動パラメータ。"""

    max_depth: int
    min_specificity: int
    stoplist_path: Path | None
    lang_map: dict[str, str]
    include: list[str]
    exclude: list[str]
    jobs: int
    follow_symlinks: bool
    max_file_bytes: int
    max_symbols: int
    max_paths: int
    memory_limit_mb: int | None = None
    use_ripgrep: bool = False
    max_passes: int = 8
    progress: str = "off"
    spill_dir: Path | None = None
    force_chunks: int = 0
    resume: bool = False
    output_encoding: str = "utf-8-sig"
    encoding_fallback: tuple[str, ...] = ("cp932", "euc-jp", "latin-1")
    max_rows_per_part: int = 1_048_575
    diagnostics_detail_limit: int = 1000
