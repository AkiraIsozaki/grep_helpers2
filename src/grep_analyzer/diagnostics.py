"""非致命の診断を集約する。先頭にカテゴリ別件数サマリ、続いて詳細。

Related: spec §10.3
"""

from collections import Counter, defaultdict

SECTION_8_4_CATEGORIES = frozenset({"symbol_rejected", "getter_setter_no_expand"})

# メモリ安全のための「カテゴリごとの詳細保持上限」。カウント(_counts)は常に全件で
# 正確だが、明細(_detail)はこの件数で頭打ちにして OOM を防ぐ（A-2）。実運用・
# 全テストで到達しない高さに設定。render の縮約（detail_limit）とは独立。
_MAX_RETAINED = 200_000


def _is_exempt(cat: str, exempt=SECTION_8_4_CATEGORIES) -> bool:
    """§8.4 全件性カテゴリ（縮約免除）。prov_ プレフィックス一致を含む。

    縮約免除判定の**唯一の実装**（render はこれに委譲＝prov_ ロジック非重複）。
    """
    return cat in exempt or cat.startswith("prov_")


class Diagnostics:
    """カテゴリ別に診断メッセージを蓄積し、サマリ＋詳細で描画する。"""

    def __init__(self) -> None:
        self._counts: Counter = Counter()
        self._detail: dict[str, list[str]] = defaultdict(list)

    def add(self, category: str, message: str) -> None:
        """1件の診断を記録する（カウントは全件、明細は _MAX_RETAINED 件で頭打ち）。"""
        self._counts[category] += 1
        lst = self._detail[category]
        if len(lst) < _MAX_RETAINED:
            lst.append(message)

    def render(self, detail_limit: int = 0, exempt=None) -> str:
        """spec §10.3 スキーマ。detail_limit=0 は無制限＝保持上限内なら現行と完全同一。"""
        is_exempt = (lambda c: _is_exempt(c, exempt)) \
            if exempt is not None else (lambda c: False)  # prov_ ロジック単一源
        out = ["# summary"]
        for cat in sorted(self._counts):
            out.append(f"{cat}\t{self._counts[cat]}")   # 常に真総数
        out.append("# detail")
        for cat in sorted(self._detail):
            msgs = self._detail[cat]
            total = self._counts[cat]                    # 真総数（保持上限で msgs より大のことあり）
            if detail_limit > 0 and not is_exempt(cat) and total > detail_limit:
                for msg in msgs[:detail_limit]:
                    out.append(f"{cat}\t{msg}")
                out.append(f"{cat}\t(... {total - detail_limit} more, {total} total)")
            else:
                for msg in msgs:
                    out.append(f"{cat}\t{msg}")
                if total > len(msgs):                    # 保持上限で落ちた明細を明示
                    out.append(f"{cat}\t(... retained cap {_MAX_RETAINED}, {total} total)")
        return "\n".join(out) + "\n"
