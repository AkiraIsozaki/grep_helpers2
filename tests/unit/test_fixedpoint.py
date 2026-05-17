"""不動点エンジンの仕様（spec §8.1/§8.2/§8.3）。外部I/O境界＝実FS本物。"""

from pathlib import Path

from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.fixedpoint import EngineOptions, run_fixedpoint
from grep_analyzer.model import Hit


def _opts(**kw):
    base = dict(max_depth=5, min_specificity=2, stoplist_path=None, lang_map={},
                include=[], exclude=[], jobs=1, follow_symlinks=False,
                max_file_bytes=1_000_000, max_symbols=1000, max_paths=100)
    base.update(kw)
    return EngineOptions(**base)


def _seed(keyword, language, rel, lineno, content):
    return Hit(keyword=keyword, language=language, file=rel, lineno=lineno,
               ref_kind="direct", category="宣言", category_sub="",
               usage_summary=f"宣言 ({language})", via_symbol="",
               chain=f"{keyword}@{rel}:{lineno}", snippet=content,
               encoding="utf-8", confidence="high")


def _mk(tmp_path, files):
    src = tmp_path / "src"
    src.mkdir()
    for rel, body in files.items():
        f = src / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, "utf-8")
    return src


def test_seed定数の他ファイル出現をindirect_constantで報告し単一ホップ(tmp_path):
    src = _mk(tmp_path, {"C.java": 'class C { static final String STATUS_OK = "S"; }\n',
                         "U.java": "class U { String x = STATUS_OK; }\n"})
    seed = _seed("STATUS_OK", "java", "C.java", 1, 'static final String STATUS_OK = "S";')
    hits = run_fixedpoint([seed], src, _opts(max_depth=1), Diagnostics())
    u = [h for h in hits if h.file == "U.java"]
    assert u and u[0].ref_kind == "indirect:constant" and u[0].via_symbol == "STATUS_OK"
    assert u[0].chain == "STATUS_OK@C.java:1 -> STATUS_OK@U.java:1"
    assert all(h.file != "C.java" for h in hits)  # seed 物理行は間接再出力しない


def test_多ホップ定数連鎖を不動点まで追い偽直結を生まない(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ static final int K1 = 1; }\n",
                         "B.java": "class B{ static final int K2 = K1; }\n",
                         "C.java": "class C{ int z2 = K2; }\n"})
    seed = _seed("K1", "java", "A.java", 1, "static final int K1 = 1;")
    hits = run_fixedpoint([seed], src, _opts(), Diagnostics())
    chains = {(h.file, h.via_symbol): h.chain for h in hits}
    assert chains[("B.java", "K1")] == "K1@A.java:1 -> K1@B.java:1"
    assert chains[("C.java", "K2")] == "K1@A.java:1 -> K1@B.java:1 -> K2@C.java:1"
    # 偽直結 K1@A.java:1 -> K2@C.java:1 は intro ベースで生成されない
    assert all(h.chain != "K1@A.java:1 -> K2@C.java:1" for h in hits)


def test_複数seedで無関係seedからの偽chainを生まない(tmp_path):
    # oracle_direct 相当: seed 2件、片方のみ v_code を導入
    src = _mk(tmp_path, {"o.sql": "v_code VARCHAR2(10);\nv_code := 'X';\n"
                                   "SELECT DECODE(st,1,'OK','NG') FROM dual;\n"})
    seeds = [_seed("X", "sql", "o.sql", 2, "v_code := 'X';"),
             _seed("X", "sql", "o.sql", 3, "SELECT DECODE(st,1,'OK','NG') FROM dual;")]
    hits = run_fixedpoint(seeds, src, _opts(), Diagnostics())
    h1 = [h for h in hits if h.file == "o.sql" and h.lineno == 1]
    assert len(h1) == 1 and h1[0].chain == "X@o.sql:2 -> v_code@o.sql:1"
    assert all("o.sql:3 -> v_code" not in h.chain for h in hits)


def test_相互参照でも有限母集合で飽和し停止する(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ static final int PP = QQ; }\n",
                         "B.java": "class B{ static final int QQ = PP; }\n"})
    seed = _seed("PP", "java", "A.java", 1, "static final int PP = QQ;")
    hits = run_fixedpoint([seed], src, _opts(max_depth=10), Diagnostics())
    assert hits and all(h.ref_kind.startswith("indirect:") for h in hits)


def test_getterは横展開せず全反復全件lowで報告し抑止記録(tmp_path):
    src = _mk(tmp_path, {
        "S.java": "class S { int count = a.getName(); }\n",
        "U.java": "class U { int v2 = count; String t2 = b.getStatus(); }\n",
        "T.java": "class T { String n = c.getName();\n String s = d.getStatus(); }\n"})
    seed = _seed("count", "java", "S.java", 1, "int count = a.getName();")
    diag = Diagnostics()
    hits = run_fixedpoint([seed], src, _opts(), diag)
    g = [h for h in hits if h.via_symbol in ("getName", "getStatus")]
    assert g and all(h.ref_kind == "indirect:getter" and h.confidence == "low" for h in g)
    assert any(h.via_symbol == "getStatus" and h.file == "T.java" for h in hits)
    d = diag.render()
    assert "getter_setter_no_expand\tgetName" in d and "getter_setter_no_expand\tgetStatus" in d


def test_jobs1とjobsNでindirectキーが完全一致し非空(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ static final int KK = 1; }\n",
                         **{f"{n}.java": f"class {n}{{ int v3 = KK; }}\n" for n in "BCDE"}})
    seed = _seed("KK", "java", "A.java", 1, "static final int KK = 1;")
    key = lambda h: (h.file, h.lineno, h.ref_kind, h.via_symbol, h.chain)
    h1 = run_fixedpoint([seed], src, _opts(jobs=1), Diagnostics())
    hN = run_fixedpoint([seed], src, _opts(jobs=4), Diagnostics())
    assert h1 and sorted(map(key, h1)) == sorted(map(key, hN))


def test_大域集合上限超過は決定的に切り捨て診断記録する(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ int aa=bb; int bb=cc; int cc=dd; int dd=1; }\n",
                         "B.java": "class B{ int zz = aa; }\n"})
    seed = _seed("aa", "java", "A.java", 1, "int aa=bb;")
    diag = Diagnostics()
    run_fixedpoint([seed], src, _opts(min_specificity=1, max_symbols=2), diag)
    assert "symbol_rejected\tcapped" in diag.render()


def test_max_depth0は間接を出さずprov_max_depthを記録(tmp_path):
    src = _mk(tmp_path, {"C.java": 'class C { static final String KK = "S"; }\n',
                         "U.java": "class U { String x = KK; }\n"})
    seed = _seed("KK", "java", "C.java", 1, 'static final String KK = "S";')
    diag = Diagnostics()
    assert run_fixedpoint([seed], src, _opts(max_depth=0), diag) == []
    assert "prov_max_depth" in diag.render()


def test_ストリーミング化後も多ホップ出力はPhase2aと同一(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ static final int K1 = 1; }\n",
                         "B.java": "class B{ static final int K2 = K1; }\n",
                         "C.java": "class C{ int z2 = K2; }\n"})
    seed = _seed("K1", "java", "A.java", 1, "static final int K1 = 1;")
    chains = {(h.file, h.via_symbol): h.chain
              for h in run_fixedpoint([seed], src, _opts(), Diagnostics())}
    assert chains[("B.java", "K1")] == "K1@A.java:1 -> K1@B.java:1"
    assert chains[("C.java", "K2")] == "K1@A.java:1 -> K1@B.java:1 -> K2@C.java:1"


def test_多行構文の分類が確定全文読みでPhase2aと同一(tmp_path):
    src = _mk(tmp_path, {
        "A.java": "class A{ static final int K1 = 1; }\n",
        "B.java": "class B {\n  void m(int s) {\n    if (s ==\n        K1) {\n"
                  "      return;\n    }\n  }\n}\n"})
    seed = _seed("K1", "java", "A.java", 1, "static final int K1 = 1;")
    hits = run_fixedpoint([seed], src, _opts(), Diagnostics())
    b = next(h for h in hits if h.file == "B.java")
    assert b.category == "比較" and b.confidence == "high"


def test_事前収集filesでも内部walkと同一(tmp_path):
    from grep_analyzer.walk import DEFAULT_EXCLUDE, collect_files
    src = _mk(tmp_path, {"C.java": 'class C { static final String S_OK = "x"; }\n',
                         "U.java": "class U { String x = S_OK; }\n"})
    seed = _seed("S_OK", "java", "C.java", 1, 'static final String S_OK = "x";')
    a = run_fixedpoint([seed], src, _opts(), Diagnostics())
    files = collect_files(src, include=[], exclude=list(DEFAULT_EXCLUDE),
                          follow_symlinks=False, max_file_bytes=1_000_000,
                          diag=Diagnostics())
    b = run_fixedpoint([seed], src, _opts(), Diagnostics(), files=files)
    k = lambda h: (h.file, h.lineno, h.ref_kind, h.via_symbol, h.chain)
    assert a and sorted(map(k, a)) == sorted(map(k, b))
