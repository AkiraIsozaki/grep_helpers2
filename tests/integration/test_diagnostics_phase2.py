"""§8.4 診断正本の境界契約（spec §8.4/§10.3・全件性・決定性）。"""

from pathlib import Path

from grep_analyzer.cli import main


def _run(tmp_path, src_files, grep, keyword, extra=None, outname="out"):
    src = tmp_path / "src"; src.mkdir(exist_ok=True)
    for rel, body in src_files.items():
        f = src / rel; f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, "utf-8")
    inp = tmp_path / "input"; inp.mkdir(exist_ok=True)
    (inp / f"{keyword}.grep").write_text(grep, "utf-8")
    out = tmp_path / outname
    main(["--input", str(inp), "--output", str(out), "--source-root", str(src)] + (extra or []))
    return (out / "diagnostics.txt").read_text("utf-8")


def test_複数getterが全件抑止記録される(tmp_path: Path):
    d = _run(tmp_path,
             {"S.java": "class S{ int vv = a.getName(); String ww = b.getCode(); }\n",
              "T.java": "class T{ String n = c.getName(); String m = d.getCode(); }\n"},
             "S.java:1:int vv = a.getName();\n", "vv")
    assert "getter_setter_no_expand\tgetName" in d and "getter_setter_no_expand\tgetCode" in d


def test_集合上限切り捨てが記録される(tmp_path: Path):
    d = _run(tmp_path,
             {"A.java": "class A{ int aa=bb; int bb=cc; int cc=1; }\n",
              "B.java": "class B{ int zz=aa; }\n"},
             "A.java:1:int aa=bb;\n", "aa",
             extra=["--max-symbols", "1", "--min-specificity", "1"])
    assert "symbol_rejected\tcapped" in d


def test_生成コード除外とmax_depth到達が記録される(tmp_path: Path):
    d = _run(tmp_path,
             {"build/Gen.java": "class Gen{ String x = STATUS_OK; }\n",
              "K.java": 'class K{ static final String STATUS_OK="S"; }\n',
              "L.java": "class L{ String yy = STATUS_OK; String zz = yy; }\n"},
             'K.java:1:static final String STATUS_OK="S";\n', "STATUS_OK",
             extra=["--max-depth", "1"])
    assert "walk_excluded\tbuild/Gen.java" in d
    assert "prov_max_depth" in d   # hop2 ingest が --max-depth 1 で打ち切り→fixedpoint 記録


def test_diagnosticsは2回実行で完全一致の決定的(tmp_path: Path):
    files = {"A.java": "class A{ static final int KK=1; }\n",
             **{f"{n}.java": f"class {n}{{ int vv=KK; }}\n" for n in "BCDEF"}}
    d1 = _run(tmp_path, files, "A.java:1:static final int KK=1;\n", "KK", outname="r1")
    d2 = _run(tmp_path, files, "A.java:1:static final int KK=1;\n", "KK", outname="r2")
    assert d1 == d2
