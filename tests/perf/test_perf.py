"""非ゲート perf 計測（spec §11・@pytest.mark.perf）。Task 11 で計測本体追加。"""

import pytest


@pytest.mark.perf
def test_perf_placeholder():
    assert True
