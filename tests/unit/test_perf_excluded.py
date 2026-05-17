"""perf 非ゲート機構の自己検証（spec v4 §4 WS6・I-B）。"""

pytest_plugins = ["pytester"]


def test_perfは既定でskip_reasonにperfを含む(pytester):
    pytester.makeini("[pytest]\nmarkers =\n    perf: 非ゲート\n"
                     "    requires_ripgrep: rg")          # 内側 marker 登録
    pytester.makeconftest(open(str(__file__).replace(
        "tests/unit/test_perf_excluded.py", "tests/conftest.py")).read())
    pytester.makepyfile(test_p="""
import pytest
@pytest.mark.perf
def test_heavy():
    assert True
""")
    r = pytester.runpytest("-rs")                          # 既定（-m 無指定）
    r.assert_outcomes(skipped=1, passed=0)                  # skip 注入（deselect 非）
    r.stdout.fnmatch_lines(["*perf*"])                      # reason に perf
