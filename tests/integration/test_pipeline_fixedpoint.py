"""direct→不動点→併合 TSV の境界契約（spec §8/§9/§10.4）。in-process。"""

from pathlib import Path

from grep_analyzer.cli import main


def _setup(tmp_path, src_files, grep, keyword):
    src = tmp_path / "src"; src.mkdir()
    for rel, body in src_files.items():
        (src / rel).write_text(body, "utf-8")
    inp = tmp_path / "input"; inp.mkdir()
    (inp / f"{keyword}.grep").write_text(grep, "utf-8")
    return src, inp


def test_間接ヒットがdirectと併合され決定的TSVになる(tmp_path: Path):
    src, inp = _setup(tmp_path,
        {"C.java": 'class C { static final String STATUS_OK = "S"; }\n',
         "U.java": "class U { String x = STATUS_OK; }\n"},
        'C.java:1:static final String STATUS_OK = "S";\n', "STATUS_OK")
    o1, o2 = tmp_path / "o1", tmp_path / "o2"
    assert main(["--input", str(inp), "--output", str(o1), "--source-root", str(src)]) == 0
    main(["--input", str(inp), "--output", str(o2), "--source-root", str(src)])
    a = (o1 / "STATUS_OK.tsv").read_text("utf-8-sig")
    cols = a.splitlines()[0].split("\t")
    rows = [dict(zip(cols, ln.split("\t"))) for ln in a.splitlines()[1:]]
    # 再ベースライン理由A: file 列は spec v9 §9 で絶対化 → 絶対パスで索引
    base = str(Path(src).resolve())
    kinds = {r["file"]: r["ref_kind"] for r in rows}
    assert (kinds[f"{base}/C.java"] == "direct"
            and kinds[f"{base}/U.java"] == "indirect:constant")
    assert a == (o2 / "STATUS_OK.tsv").read_text("utf-8-sig")


def test_max_depth0は間接追跡せずdirectのみ(tmp_path: Path):
    src, inp = _setup(tmp_path,
        {"C.java": 'class C { static final String STATUS_OK = "S"; }\n',
         "U.java": "class U { String x = STATUS_OK; }\n"},
        'C.java:1:static final String STATUS_OK = "S";\n', "STATUS_OK")
    o = tmp_path / "o"
    main(["--input", str(inp), "--output", str(o), "--source-root", str(src), "--max-depth", "0"])
    rows = (o / "STATUS_OK.tsv").read_text("utf-8-sig").splitlines()[1:]
    assert rows and all("\tdirect\t" in r for r in rows)


def test_lang_mapはdirectとindirectで対称に効く(tmp_path: Path):
    src, inp = _setup(tmp_path,
        {"C.inc": 'class C { static final String STATUS_OK = "S"; }\n',
         "U.inc": "class U { String x = STATUS_OK; }\n"},
        'C.inc:1:static final String STATUS_OK = "S";\n', "STATUS_OK")
    o = tmp_path / "o"
    main(["--input", str(inp), "--output", str(o), "--source-root", str(src),
          "--lang-map", ".inc=java"])
    a = (o / "STATUS_OK.tsv").read_text("utf-8-sig")
    cols = a.splitlines()[0].split("\t")
    rows = [dict(zip(cols, ln.split("\t"))) for ln in a.splitlines()[1:]]
    assert all(r["language"] == "java" for r in rows)
    assert any(r["ref_kind"] == "indirect:constant" for r in rows)
