"""標準エラー進捗（spec §8.2）。level=="on" 以外は完全無音。注入された

stream（既定 sys.stderr）専用で TSV/diagnostics/終了コードに無影響。
"""

import sys


class Progress:
    """走査進捗を stderr へ出す（off/未知 level は無音）。"""

    def __init__(self, level: str, stream=None) -> None:
        self._on = level == "on"
        self._stream = stream if stream is not None else sys.stderr
        self._total = 0

    def start(self, total_files: int) -> None:
        """走査開始（総ファイル数）。"""
        self._total = total_files
        if self._on:
            print(f"[grep_analyzer] start files={total_files}",
                  file=self._stream, flush=True)

    def hop(self, hop: int, n_symbols: int, scanned: int) -> None:
        """1 ホップ進捗。"""
        if self._on:
            print(f"[grep_analyzer] hop={hop} symbols={n_symbols} "
                  f"scanned={scanned}/{self._total}", file=self._stream, flush=True)

    def done(self) -> None:
        """走査完了。"""
        if self._on:
            print("[grep_analyzer] done", file=self._stream, flush=True)
