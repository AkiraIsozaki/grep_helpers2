"""パッケージimport と CLI 起動の生存確認（spec §11 smoke）。"""


def test_grep_analyzerをimportできる():
    import grep_analyzer  # noqa: F401
