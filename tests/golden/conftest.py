"""golden ケースを自動 parametrize する（spec §11）。"""

from pathlib import Path

import pytest

CASES = sorted((Path(__file__).parent / "cases").glob("*/"))


@pytest.fixture(params=[c.name for c in CASES])
def golden_case(request):
    return Path(__file__).parent / "cases" / request.param
