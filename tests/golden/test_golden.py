"""合成代表ツリーの TSV 完全一致による回帰検出（spec §11 v9 機構）。"""

import dataclasses
import json
from pathlib import Path

from grep_analyzer import resume
from grep_analyzer.pipeline import _default_opts, run


def _opts_for(case: Path):
    """ケース任意 opts.json を _default_opts へ反映（無ければ既定）。"""
    cfg = case / "opts.json"
    o = _default_opts()
    if cfg.is_file():
        d = json.loads(cfg.read_text("utf-8"))
        repl = {}
        if "follow_symlinks" in d:
            repl["follow_symlinks"] = d["follow_symlinks"]
        if "output_encoding" in d:
            repl["output_encoding"] = d["output_encoding"]
        if "resume" in d:
            repl["resume"] = d["resume"]
        o = dataclasses.replace(o, **repl)
    return o


def test_合成ケースのTSVが期待値と完全一致する(golden_case, tmp_path):
    out = tmp_path / "out"
    opts = _opts_for(golden_case)
    rc = run(input_dir=golden_case / "input", output_dir=out,
             source_root=golden_case / "src", opts=opts)
    assert rc == 0
    sr = str(Path(golden_case / "src").resolve())            # spec §11(b)
    for expected in sorted((golden_case / "expected").glob("*.tsv")):
        keyword = expected.stem
        mpath = out / f"{keyword}.manifest.json"
        enc = "utf-8-sig"
        if mpath.is_file():                                  # spec §11(a)
            enc = json.loads(mpath.read_text("utf-8")).get(
                "encoding", "utf-8-sig")
        actual = (out / expected.name).read_text(enc)
        # spec §11(b): 各データ行ごとに先頭1回置換（ファイル全体1回は禁止
        # ＝2行目以降が絶対パスで残り環境依存になる。chain_multipath 等
        # 複数 file 行ケースで顕在）。file 列は各行で snippet より前なので
        # 行内の最初の SR+"/" が file セル（keyword/language 列は SR を
        # 含まない＝golden が保証。新規ケースは上記 Task11 制約で担保）。
        actual = "".join(
            (ln.replace(sr + "/", "{SOURCE_ROOT}/", 1)
             if (sr + "/") in ln else ln)
            for ln in actual.splitlines(keepends=True))
        assert actual == expected.read_text("utf-8-sig"), expected.name
    exp_sum = golden_case / "expected" / "diagnostics_summary.txt"
    if exp_sum.is_file():                                 # spec §11 opt-in
        diag_text = (out / "diagnostics.txt").read_text("utf-8")
        lines, in_sum = [], False
        for ln in diag_text.splitlines():
            if ln == "# summary":
                in_sum = True
                continue
            if ln == "# detail":
                break
            if in_sum:
                lines.append(ln)
        actual_sum = "\n".join(lines) + "\n"
        assert actual_sum == exp_sum.read_text("utf-8"), "diagnostics_summary.txt"
    cfg = golden_case / "opts.json"
    if cfg.is_file() and json.loads(
            cfg.read_text("utf-8")).get("assert_resume_complete"):
        for expected in sorted((golden_case / "expected").glob("*.tsv")):  # §11(d)
            assert resume.is_complete(out, expected.stem, opts)


def test_golden各ケースはjobs2でもjobs1とバイト同値(golden_case, tmp_path):
    """並列完了順非依存の決定性を全 golden ケースで恒久照合する（C-3）。"""
    opts1 = _opts_for(golden_case)
    out1 = tmp_path / "j1"
    assert run(input_dir=golden_case / "input", output_dir=out1,
               source_root=golden_case / "src", opts=opts1) == 0

    opts2 = dataclasses.replace(_opts_for(golden_case), jobs=2)
    out2 = tmp_path / "j2"
    assert run(input_dir=golden_case / "input", output_dir=out2,
               source_root=golden_case / "src", opts=opts2) == 0

    for expected in sorted((golden_case / "expected").glob("*.tsv")):
        name = expected.name
        assert (out2 / name).read_bytes() == (out1 / name).read_bytes(), name
