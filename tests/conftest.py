"""pytest 共通設定。src レイアウトを import 可能にする。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "requires_ripgrep: 実 ripgrep を要する（無ければ skip）")


def pytest_collection_modifyitems(config, items):
    import re
    import shutil
    rg = shutil.which("rg") is not None
    markexpr = config.getoption("markexpr") or ""        # -m の式（"-m" でなく markexpr）
    # "perf" がトークンとして式に現れるか（"not perf" 等の部分文字列誤判定回避）。
    perf_selected = bool(re.search(r"\bperf\b", markexpr))
    skip_rg = pytest.mark.skip(reason="ripgrep 不在のため skip（任意機能）")
    skip_perf = pytest.mark.skip(reason="perf は非ゲート（既定除外）")
    for item in items:
        if "requires_ripgrep" in item.keywords and not rg:
            item.add_marker(skip_rg)
        if "perf" in item.keywords and not perf_selected:
            item.add_marker(skip_perf)
