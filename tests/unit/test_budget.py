"""決定的メモリ近似の仕様（spec §8.2・degrade トリガの決定性）。"""

from grep_analyzer.budget import MemoryBudget, estimate_items


def test_estimate_itemsは各要素数の単純和():
    assert estimate_items(n_symbols=3, n_edges=10, n_intro=4) == 17
    assert estimate_items(n_symbols=0, n_edges=0, n_intro=0) == 0


def test_Noneは無制限で超過しない():
    b = MemoryBudget(None)
    assert b.unlimited is True and b.exceeded(10**9) is False


def test_0はitem予算0で1件以上超過():
    b = MemoryBudget(0)
    assert b.unlimited is False and b.item_budget == 0
    assert b.exceeded(0) is False and b.exceeded(1) is True


def test_N_MBは決定的換算で上限ちょうどは可超過はTrue():
    b = MemoryBudget(1)
    assert b.unlimited is False
    assert b.item_budget == MemoryBudget(1).item_budget
    assert b.exceeded(b.item_budget) is False
    assert b.exceeded(b.item_budget + 1) is True


def test_予算は単調():
    assert MemoryBudget(2).item_budget > MemoryBudget(1).item_budget >= MemoryBudget(0).item_budget


from grep_analyzer.fixedpoint import EngineOptions


def _opts(**kw):
    base = dict(max_depth=5, min_specificity=2, stoplist_path=None, lang_map={},
                include=[], exclude=[], jobs=1, follow_symlinks=False,
                max_file_bytes=1_000_000, max_symbols=1000, max_paths=100,
                memory_limit_mb=None, use_ripgrep=False, max_passes=8,
                progress="off", spill_dir=None, force_chunks=0)
    base.update(kw)
    return EngineOptions(**base)


def test_compute_nchunks_unionは予算無制限なら1():
    from grep_analyzer.fixedpoint._budget_control import compute_nchunks_union
    opts = _opts(force_chunks=0)
    budget_unlimited = MemoryBudget(None)
    assert compute_nchunks_union([], ["A", "B"], opts=opts, budget=budget_unlimited) == 1


def test_compute_nchunks_unionはforce_chunks指定で最小値():
    from grep_analyzer.fixedpoint._budget_control import compute_nchunks_union
    opts_force3 = _opts(force_chunks=3, max_passes=8)
    budget = MemoryBudget(None)
    # min(force_chunks=3, max_passes=8, len(union)=2) == 2
    assert compute_nchunks_union([], ["A", "B"], opts=opts_force3, budget=budget) == 2
