"""非致命の診断を集約する（spec §10.3）。先頭にカテゴリ別件数サマリ、続いて詳細。"""

from collections import Counter, defaultdict


class Diagnostics:
    """カテゴリ別に診断メッセージを蓄積し、サマリ＋詳細で描画する。"""

    def __init__(self) -> None:
        self._counts: Counter = Counter()
        self._detail: dict[str, list[str]] = defaultdict(list)

    def add(self, category: str, message: str) -> None:
        """1件の診断を記録する。"""
        self._counts[category] += 1
        self._detail[category].append(message)

    def render(self) -> str:
        """spec §10.3 のスキーマ（summary→detail）でテキスト化する。"""
        out = ["# summary"]
        for cat in sorted(self._counts):
            out.append(f"{cat}\t{self._counts[cat]}")
        out.append("# detail")
        for cat in sorted(self._detail):
            for msg in self._detail[cat]:
                out.append(f"{cat}\t{msg}")
        return "\n".join(out) + "\n"
