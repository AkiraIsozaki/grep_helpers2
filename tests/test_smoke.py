"""パッケージimport と CLI 起動の生存確認（spec §11 smoke）。"""


def test_grep_analyzerをimportできる():
    import grep_analyzer  # noqa: F401


def test_CLIのhelpがexit0を返す():
    import subprocess
    import sys
    from pathlib import Path

    src_dir = Path(__file__).resolve().parents[1] / "src"
    r = subprocess.run(
        [sys.executable, "-m", "grep_analyzer", "--help"],
        capture_output=True, cwd=str(src_dir),
    )
    assert r.returncode == 0


def test_tree_sitter言語がロードできる():
    from grep_analyzer.classifiers.ts_classifier import classify_ts

    assert classify_ts("java", "class A{}\n", 1)[1] == "high"
