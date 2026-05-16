"""分類器の共通型。Phase 1 は direct 行の分類のみ（spec §15 フェーズ1）。"""

# 分類結果 = (共通上位カテゴリ, confidence)。category_sub は v1 空固定（spec §9）。
ClassifyResult = tuple[str, str]
