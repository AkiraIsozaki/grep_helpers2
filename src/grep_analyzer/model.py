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
    """spec §9 v9 全順序キー。

    (ref_kind_rank, chain_group, file, lineno, ref_kind, via_symbol,
     category, category_sub, confidence, usage_summary, snippet,
     language, encoding)。ref_kind_rank: direct→0 / indirect:*→1。
    chain_group: direct→"" / indirect:*→chain。lineno は数値順。
    """
    ref_kind_rank = 0 if h.ref_kind == "direct" else 1
    chain_group = "" if h.ref_kind == "direct" else h.chain
    return (
        ref_kind_rank, chain_group, h.file, h.lineno, h.ref_kind,
        h.via_symbol, h.category, h.category_sub, h.confidence,
        h.usage_summary, h.snippet, h.language, h.encoding,
    )
