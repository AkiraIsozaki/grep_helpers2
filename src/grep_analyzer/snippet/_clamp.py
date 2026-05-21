"""snippet 縮約（spec §9「上限と切り詰め」）。

ヒット行を中心に上下対称に拡張し、行数 LINE_MAX / 文字数 CHAR_MAX で
頭打ちにする。文字数は連結後 body の Python `len()`（コードポイント数）。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [C]
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
    s, e = 0, len(lines) - 1
    hit_text = lines[hit]
    out = ([hit_text[:char_max - 1] + ELL] if len(hit_text) > char_max
           else [hit_text])
    up, dn = hit - 1, hit + 1
    while True:
        if len(out) >= line_max:
            break
        progressed = False
        if up >= s:
            cand = [lines[up]] + out
            ra = (up - 1) - s + 1 if (up - 1) >= s else 0
            rb = e - dn + 1 if dn <= e else 0
            if len(cand) <= line_max and len(_render(cand, ra, rb)) <= char_max:
                out, up, progressed = cand, up - 1, True
        if len(out) >= line_max:
            break
        if dn <= e:
            cand = out + [lines[dn]]
            ra = up - s + 1 if up >= s else 0
            rb = e - (dn + 1) + 1 if (dn + 1) <= e else 0
            if len(cand) <= line_max and len(_render(cand, ra, rb)) <= char_max:
                out, dn, progressed = cand, dn + 1, True
        if not progressed:
            break
    top_k = up - s + 1 if up >= s else 0
    bot_k = e - dn + 1 if dn <= e else 0
    return _render(out, top_k, bot_k)
