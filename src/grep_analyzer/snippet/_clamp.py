"""snippet 縮約（「上限と切り詰め」）。

ヒット行を中心に上下対称に拡張し、行数 LINE_MAX / 文字数 CHAR_MAX で
頭打ちにする。文字数は連結後 body の Python `len()`（コードポイント数）。

Related: spec §9 / docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [C]
"""

SEP = " \\n "
ELL = "…"
LINE_MAX = 12
CHAR_MAX = 800


def _render(rows: list[str], top_k: int, bot_k: int) -> str:
    body = SEP.join(rows)
    if top_k:
        body = f"{ELL}(+{top_k}上行省略)" + body
    if bot_k:
        body = body + f"{ELL}(+{bot_k}下行省略)"
    return body


def clamp_lines(lines: list[str], hit: int, line_max: int = LINE_MAX,
                char_max: int = CHAR_MAX) -> str:
    """選択範囲 lines をヒット中心に縮約。

    hit は lines 内 0 始まり index。lines は連結前に呼び出し側で
    サニタイズ＋区切り衝突エスケープ済（build_snippet が責務）。
    """
    span_start, span_end = 0, len(lines) - 1
    hit_text = lines[hit]
    out = ([hit_text[:char_max - 1] + ELL] if len(hit_text) > char_max
           else [hit_text])
    up_idx, down_idx = hit - 1, hit + 1
    while True:
        if len(out) >= line_max:
            break
        progressed = False
        if up_idx >= span_start:
            cand = [lines[up_idx]] + out
            above_count = (up_idx - 1) - span_start + 1 if (up_idx - 1) >= span_start else 0
            below_count = span_end - down_idx + 1 if down_idx <= span_end else 0
            if len(cand) <= line_max and len(_render(cand, above_count, below_count)) <= char_max:
                out, up_idx, progressed = cand, up_idx - 1, True
        if len(out) >= line_max:
            break
        if down_idx <= span_end:
            cand = out + [lines[down_idx]]
            above_count = up_idx - span_start + 1 if up_idx >= span_start else 0
            below_count = span_end - (down_idx + 1) + 1 if (down_idx + 1) <= span_end else 0
            if len(cand) <= line_max and len(_render(cand, above_count, below_count)) <= char_max:
                out, down_idx, progressed = cand, down_idx + 1, True
        if not progressed:
            break
    top_k = up_idx - span_start + 1 if up_idx >= span_start else 0
    bot_k = span_end - down_idx + 1 if down_idx <= span_end else 0
    return _render(out, top_k, bot_k)
