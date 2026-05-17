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
