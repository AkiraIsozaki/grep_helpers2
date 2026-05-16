"""ドメインモデル（Hit）とTSVスキーマ・決定的ソート（spec §9）。"""

from dataclasses import dataclass

TSV_COLUMNS = [
    "keyword", "language", "file", "lineno", "ref_kind",
    "category", "category_sub", "usage_summary", "via_symbol",
    "chain", "snippet", "encoding", "confidence",
]


@dataclass(frozen=True)
class Hit:
    """TSV1行に対応する分類結果。Phase 1 では ref_kind は常に "direct"。"""

    keyword: str
    language: str
    file: str
    lineno: int
    ref_kind: str
    category: str
    category_sub: str
    usage_summary: str
    via_symbol: str
    chain: str
    snippet: str
    encoding: str
    confidence: str

    def to_row(self) -> list[str]:
        """TSV_COLUMNS の順で文字列セルのリストを返す。"""
        return [
            self.keyword, self.language, self.file, str(self.lineno),
            self.ref_kind, self.category, self.category_sub,
            self.usage_summary, self.via_symbol, self.chain,
            self.snippet, self.encoding, self.confidence,
        ]


def sort_key(h: Hit) -> tuple:
    """spec §9 の全順序安定ソートキー。lineno は数値順。"""
    return (
        h.file, h.lineno, h.ref_kind, h.via_symbol, h.chain,
        h.category, h.category_sub, h.confidence, h.usage_summary, h.snippet,
    )
