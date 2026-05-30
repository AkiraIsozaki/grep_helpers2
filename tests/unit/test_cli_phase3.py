"""Phase 3 CLI フラグの EngineOptions 反映（spec §10.4 / WS1-4-6）。"""

from grep_analyzer.cli import _build_opts


def test_phase3フラグ既定値():
    o = _build_opts([
        "--input", "i", "--output", "o", "--source-root", "s"])
    assert o.resume is False
    assert o.output_encoding == "utf-8-sig"
    assert list(o.encoding_fallback) == ["cp932", "euc-jp", "latin-1"]
    assert o.max_rows_per_part == 1_048_575
    assert o.diagnostics_detail_limit == 1000


def test_phase3フラグ明示指定():
    o = _build_opts([
        "--input", "i", "--output", "o", "--source-root", "s",
        "--resume", "--output-encoding", "cp932",
        "--encoding-fallback", "euc-jp,latin-1",
        "--max-rows-per-part", "5", "--diagnostics-detail-limit", "0"])
    assert o.resume is True
    assert o.output_encoding == "cp932"
    assert list(o.encoding_fallback) == ["euc-jp", "latin-1"]
    assert o.max_rows_per_part == 5
    assert o.diagnostics_detail_limit == 0


def test_use_ripgrep既定はNone_明示でTrueFalse():
    from grep_analyzer.cli import _build_opts
    base = ["--input", "i", "--output", "o", "--source-root", "s"]
    assert _build_opts(base).use_ripgrep is None
    assert _build_opts(base + ["--use-ripgrep"]).use_ripgrep is True
    assert _build_opts(base + ["--no-use-ripgrep"]).use_ripgrep is False


def test_閾値既定は1GiB_可変():
    from grep_analyzer.cli import _build_opts
    base = ["--input", "i", "--output", "o", "--source-root", "s"]
    assert _build_opts(base).ripgrep_threshold_bytes == 1 << 30
    assert _build_opts(base + ["--ripgrep-threshold-bytes", "100"]).ripgrep_threshold_bytes == 100
