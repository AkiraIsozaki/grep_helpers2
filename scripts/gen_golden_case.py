# scripts/gen_golden_case.py
"""golden ケースの expected/ を現 pipeline 出力から（再）生成する開発ツール。

使い方:
    python scripts/gen_golden_case.py tests/golden/cases/<case> [--with-diag-summary]

挙動: <case>/input・<case>/src で pipeline.run を回し、tests/golden/test_golden.py と
同一の {SOURCE_ROOT} 逆置換（各行先頭1回）を施して <case>/expected/*.tsv を上書きする。
--with-diag-summary 指定時は diagnostics.txt の "# summary" ブロックを
<case>/expected/diagnostics_summary.txt に書く。

注意: 生成後は必ず `git diff` で内容を人手レビューしてからコミットする（spec 案A）。
"""
import argparse
import dataclasses
import json
import tempfile
from pathlib import Path

from grep_analyzer.pipeline import _default_opts, run


def _opts_for(case: Path):
    o = _default_opts()
    cfg = case / "opts.json"
    if cfg.is_file():
        d = json.loads(cfg.read_text("utf-8"))
        repl = {k: d[k] for k in ("follow_symlinks", "output_encoding", "resume")
                if k in d}
        o = dataclasses.replace(o, **repl)
    return o


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("case")
    ap.add_argument("--with-diag-summary", action="store_true")
    args = ap.parse_args()
    case = Path(args.case)
    opts = _opts_for(case)
    out = Path(tempfile.mkdtemp(prefix="gen_golden_"))
    rc = run(input_dir=case / "input", output_dir=out,
             source_root=case / "src", opts=opts)
    assert rc == 0, f"pipeline rc={rc}"

    sr = str((case / "src").resolve())
    exp = case / "expected"
    exp.mkdir(parents=True, exist_ok=True)
    for tsv in sorted(out.glob("*.tsv")):
        mpath = out / f"{tsv.stem}.manifest.json"
        enc = "utf-8-sig"
        if mpath.is_file():
            enc = json.loads(mpath.read_text("utf-8")).get("encoding", "utf-8-sig")
        text = tsv.read_text(enc)
        text = "".join(
            (ln.replace(sr + "/", "{SOURCE_ROOT}/", 1) if (sr + "/") in ln else ln)
            for ln in text.splitlines(keepends=True))
        (exp / tsv.name).write_text(text, "utf-8-sig")
        print(f"wrote {exp / tsv.name}")

    if args.with_diag_summary:
        diag = (out / "diagnostics.txt").read_text("utf-8")
        lines, in_sum = [], False
        for ln in diag.splitlines():
            if ln == "# summary":
                in_sum = True
                continue
            if ln == "# detail":
                break
            if in_sum:
                lines.append(ln)
        (exp / "diagnostics_summary.txt").write_text("\n".join(lines) + "\n", "utf-8")
        print(f"wrote {exp / 'diagnostics_summary.txt'}")


if __name__ == "__main__":
    main()
