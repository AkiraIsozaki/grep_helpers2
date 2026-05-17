"""pytest 共通設定。src レイアウトを import 可能にする。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "requires_ripgrep: 実 ripgrep を要する（無ければ skip）")


def pytest_collection_modifyitems(config, items):
    import shutil
    if shutil.which("rg") is not None:
        return
    skip = pytest.mark.skip(reason="ripgrep 不在のため skip（任意機能）")
    for item in items:
        if "requires_ripgrep" in item.keywords:
            item.add_marker(skip)
