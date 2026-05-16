"""合成代表ツリーの TSV 完全一致による回帰検出（spec §11）。"""

from grep_analyzer.pipeline import run


def test_合成ケースのTSVが期待値と完全一致する(golden_case, tmp_path):
    out = tmp_path / "out"
    rc = run(
        input_dir=golden_case / "input",
        output_dir=out,
        source_root=golden_case / "src",
    )
    assert rc == 0
    for expected in (golden_case / "expected").glob("*.tsv"):
        actual = (out / expected.name).read_text("utf-8-sig")
        assert actual == expected.read_text("utf-8-sig"), expected.name
