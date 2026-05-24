"""来歴グラフと chain 正規形。単純パスのみ列挙（07e81bb 明確化準拠）。

Related: spec §9
"""

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

        生成時打ち切り（spec §9 安全弁）: 収集本数が max_paths+1 に達した時点で
        DFS を停止する（+1 は「真に超過したか」を判定し prov_path_capped の誤発火を
        防ぐため＝旧 `> max_paths` 意味を厳密復元）。DFS 順は seed `sorted`・隣接
        `sort` で決定的なので打ち切り後の集合も決定的。max_paths 未達は従来と同値。
        深い連鎖での RecursionError は捕捉し prov_recursion_skipped を記録のうえ
        ここまでの結果で打ち切る（巨大 --max-depth クラッシュの防御。再帰上限は固定で
        入力も固定ゆえ打ち切り点・部分結果とも決定的）。
        """
        limit = max_paths + 1
        results: list[str] = []
        try:
            for seed in sorted(self._seeds):
                if len(results) >= limit:
                    break
                self._dfs(seed, target, [seed], {seed}, set(),
                          max_depth, limit, diag, results)
        except RecursionError:
            diag.add("prov_recursion_skipped", _hop(target))
        results = sorted(set(results))
        if len(results) > max_paths:
            diag.add("prov_path_capped", f"{_hop(target)}\t>={max_paths}")
            results = results[:max_paths]
        return results

    def _dfs(self, node, target, path, visited_occurrences, visited_symbols,
             max_depth, limit, diag, results) -> None:
        if len(results) >= limit:               # 生成時打ち切り（指数爆発の根治）
            return
        if node == target:
            results.append(" -> ".join(_hop(o) for o in path))
            return
        if len(path) - 1 >= max_depth:
            diag.add("prov_max_depth", _hop(path[0]) + " ... " + _hop(node))
            return
        for next_occ in self._adj.get(node, []):
            if len(results) >= limit:
                return
            if next_occ in visited_occurrences or next_occ.symbol in visited_symbols:
                diag.add("prov_cycle_cut", _hop(node) + " -> " + _hop(next_occ))
                continue
            self._dfs(next_occ, target, path + [next_occ],
                      visited_occurrences | {next_occ},
                      visited_symbols | {next_occ.symbol},
                      max_depth, limit, diag, results)
