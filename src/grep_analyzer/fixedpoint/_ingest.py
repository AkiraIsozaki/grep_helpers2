"""1 行から ChaseState への追跡シンボル投入（spec §8.1 手順）。

extract_chase_symbols で得た候補を stoplist.partition で chase / terminal /
rejected に分け、`introducers`（発見元）に親 Occurrence を記録する。
非 seed の自己定義行が自分自身を再抽出しても発見元にしない（spec §8.2）。

`absorb_results`: scan 結果を ChaseState に反映する（edge_store 追加、
encoding 記録、子の再 ingest）。`hop` は **現在処理中の hop（呼出時点で
完了済み hop の番号）**。内部で hop+1 して次 hop の ingest に渡す。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [A]
"""

from grep_analyzer.chase import extract_chase_symbols
from grep_analyzer.fixedpoint._scan import kinds_of
from grep_analyzer.fixedpoint._state import ChaseState
from grep_analyzer.provenance import Occurrence
from grep_analyzer.stoplist import partition


def ingest_one(state: ChaseState, parent: Occurrence, language: str,
               dialect: str, line: str, hop: int, is_seed: bool = False):
    """1 行を ChaseState に取り込む。spec §8.1 手順 1〜4。

    `hop` は呼出時点で完了済みの hop 番号。子の ingest_one には `hop + 1` を渡す。
    """
    diag = state.diagnostics
    opts = state.options
    if hop > opts.max_depth:
        if parent not in state.maxdepth_logged:
            diag.add("prov_max_depth", f"{parent.symbol}@{parent.relpath}:"
                     f"{parent.lineno} (hop {hop} > --max-depth {opts.max_depth})")
            state.maxdepth_logged.add(parent)
        return
    cs = extract_chase_symbols(language, dialect, line)
    kinds = kinds_of(language, dialect, line)
    part = partition(cs, language, state.policy)
    for sym, reason in sorted(part.rejected):
        diag.add("symbol_rejected", f"{reason}\t{sym}")
    for sym in part.chase:
        if sym in state.capped:
            continue
        if not is_seed and sym == parent.symbol:
            continue
        state.symbol_kind.setdefault(sym, kinds.get(sym, "var"))
        state.symbol_hop.setdefault(sym, hop)
        lst = state.introducers.setdefault(sym, [])
        if parent not in lst:
            lst.append(parent)
        if sym not in state.chase_done:
            state.chase_active.add(sym)
    for sym in part.terminal:
        if sym in state.capped:
            continue
        if not is_seed and sym == parent.symbol:
            continue
        state.symbol_kind.setdefault(sym, kinds.get(sym, "getter"))
        state.symbol_hop.setdefault(sym, hop)
        lst = state.introducers.setdefault(sym, [])
        if parent not in lst:
            lst.append(parent)
        if sym not in state.terminal_done:
            state.terminal_active.add(sym)


def absorb_results(state: ChaseState, pass_results, scan_chase: set[str],
                   scan_term: set[str], hop: int):
    """scan_hop の結果を ChaseState に反映する（edge 追加・diag・子の再 ingest）。

    `hop` は呼出時点で完了済みの hop 番号。子の ingest_one には `hop + 1` を渡す。
    """
    diag = state.diagnostics
    for rel, enc, replaced, language, dialect, found in pass_results:
        state.encoding_of.setdefault(rel, (enc, replaced))
        if replaced and rel not in state.replaced_logged:
            diag.add("decode_replaced", rel)
            state.replaced_logged.add(rel)
        for sym, i, line in found:
            if sym not in scan_chase and sym not in scan_term:
                continue
            child = Occurrence(sym, rel, i)
            for parent in state.introducers.get(sym, []):
                if parent != child:
                    state.edge_store.add(parent, child)
            if sym in scan_term:
                if sym not in state.no_expand_logged:
                    diag.add("getter_setter_no_expand", sym)
                    state.no_expand_logged.add(sym)
                continue
            ingest_one(state, child, language, dialect, line, hop + 1)
