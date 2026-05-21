"""来歴グラフと chain 正規形（spec §9・07e81bb 明確化準拠）。単純パスのみ列挙。"""

from dataclasses import dataclass

from grep_analyzer.diagnostics import Diagnostics


@dataclass(frozen=True, order=True)
class Occurrence:
    """ヒット出現＝来歴グラフのノード。order=True で決定的ソート可能。"""

    symbol: str
    relpath: str
    lineno: int


def _hop(o: Occurrence) -> str:
    """spec §9 ホップ表記 `symbol@relpath:lineno`。"""
    return f"{o.symbol}@{o.relpath}:{o.lineno}"


class ProvenanceGraph:
    """発見元→発見の有向グラフ。種から各ヒットへの単純パスを chain 化する。"""

    def __init__(self) -> None:
        self._seeds: set[Occurrence] = set()
        self._seed_loc: set[tuple[str, int]] = set()
        self._adj: dict[Occurrence, list[Occurrence]] = {}

    def add_seed(self, occ: Occurrence) -> None:
        """起点（direct 相当）を登録。物理行も seed として記録。"""
        self._seeds.add(occ)
        self._seed_loc.add((occ.relpath, occ.lineno))

    def is_seed_location(self, relpath: str, lineno: int) -> bool:
        """(relpath,lineno) が direct seed 物理行か（間接再出力の除外判定）。"""
        return (relpath, lineno) in self._seed_loc

    def add_edge(self, parent: Occurrence, child: Occurrence) -> None:
        """発見元 parent → 発見 child のエッジを追加（決定的順序を維持）。"""
        lst = self._adj.setdefault(parent, [])
        if child not in lst:
            lst.append(child)
            lst.sort()

    def chains_to(
        self, target: Occurrence, *, max_depth: int, max_paths: int, diag: Diagnostics
    ) -> list[str]:
        """各 seed から target への単純パスを chain 文字列の決定的リストで返す。

        単純パス＝同一 Occurrence 非反復、起点以降の追跡識別子(symbol)非反復
        （spec §9・07e81bb 明確化）。max_depth はホップ数(` -> `本数)。
        循環/深さ/経路数の打ち切り＝prov_cycle_cut/prov_max_depth/prov_path_capped。
        """
        results: list[str] = []
        for seed in sorted(self._seeds):
            self._dfs(seed, target, [seed], {seed}, set(), max_depth, diag, results)
        results = sorted(set(results))
        if len(results) > max_paths:
            diag.add("prov_path_capped", f"{_hop(target)}\t{len(results)}>{max_paths}")
            results = results[:max_paths]
        return results

    def _dfs(self, node, target, path, visited_occurrences, visited_symbols,
             max_depth, diag, results) -> None:
        if node == target:
            results.append(" -> ".join(_hop(o) for o in path))
            return
        if len(path) - 1 >= max_depth:
            diag.add("prov_max_depth", _hop(path[0]) + " ... " + _hop(node))
            return
        for next_occ in self._adj.get(node, []):
            if next_occ in visited_occurrences or next_occ.symbol in visited_symbols:
                diag.add("prov_cycle_cut", _hop(node) + " -> " + _hop(next_occ))
                continue
            self._dfs(next_occ, target, path + [next_occ],
                      visited_occurrences | {next_occ},
                      visited_symbols | {next_occ.symbol}, max_depth, diag, results)
