"""Phase 2b 配線の境界契約（spec §8.2・既定出力不変・診断重複解消）。in-process。"""

import io
from contextlib import redirect_stderr
from pathlib import Path

from grep_analyzer.cli import main


def _tree(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "C.java").write_text('class C { static final String S_OK = "x"; }\n', "utf-8")
    (src / "U.java").write_text("class U { String x = S_OK; }\n", "utf-8")
    inp = tmp_path / "input"; inp.mkdir()
    (inp / "S_OK.grep").write_text('C.java:1:static final String S_OK = "x";\n', "utf-8")
    (inp / "OTHER.grep").write_text('C.java:1:static final String S_OK = "x";\n', "utf-8")
    return src, inp


def test_既定オプションは決定的でindirectが出る(tmp_path: Path):
    src, inp = _tree(tmp_path)
    o1, o2 = tmp_path / "o1", tmp_path / "o2"
    assert main(["--input", str(inp), "--output", str(o1),
                 "--source-root", str(src)]) == 0
    main(["--input", str(inp), "--output", str(o2), "--source-root", str(src)])
    a = (o1 / "S_OK.tsv").read_text("utf-8-sig")
    assert "indirect:constant" in a and "S_OK@C.java:1 -> S_OK@U.java:1" in a
    assert a == (o2 / "S_OK.tsv").read_text("utf-8-sig")


def test_walk診断はkeyword数によらず重複しない(tmp_path: Path):
    src, inp = _tree(tmp_path)
    (src / "build").mkdir()
    (src / "build" / "G.java").write_text("class G{}\n", "utf-8")
    out = tmp_path / "o"
    main(["--input", str(inp), "--output", str(out), "--source-root", str(src)])
    d = (out / "diagnostics.txt").read_text("utf-8")
    assert d.count("walk_excluded\tbuild/G.java") == 1


def test_progress_onはstderrのみでTSV不変(tmp_path: Path):
    src, inp = _tree(tmp_path)
    b = tmp_path / "b"; main(["--input", str(inp), "--output", str(b),
                              "--source-root", str(src)])
    p = tmp_path / "p"
    err = io.StringIO()
    with redirect_stderr(err):
        main(["--input", str(inp), "--output", str(p),
              "--source-root", str(src), "--progress", "on"])
    assert "[grep_analyzer]" in err.getvalue()
    assert (b / "S_OK.tsv").read_text("utf-8-sig") == \
           (p / "S_OK.tsv").read_text("utf-8-sig")


def test_memory_limit0はdirect不変でindirectは決定的に減る(tmp_path: Path):
    src, inp = _tree(tmp_path)
    a = tmp_path / "a"; main(["--input", str(inp), "--output", str(a),
                              "--source-root", str(src)])
    b = tmp_path / "b"
    main(["--input", str(inp), "--output", str(b), "--source-root", str(src),
          "--memory-limit", "0", "--max-passes", "8"])
    da = [ln for ln in (a / "S_OK.tsv").read_text("utf-8-sig").splitlines()
          if "\tdirect\t" in ln]
    db = [ln for ln in (b / "S_OK.tsv").read_text("utf-8-sig").splitlines()
          if "\tdirect\t" in ln]
    assert da == db and da                                  # direct 行不変
    a2 = (b / "S_OK.tsv").read_text("utf-8-sig")
    b2 = tmp_path / "b2"
    main(["--input", str(inp), "--output", str(b2), "--source-root", str(src),
          "--memory-limit", "0", "--max-passes", "8"])
    assert a2 == (b2 / "S_OK.tsv").read_text("utf-8-sig")    # memory0 も決定的
