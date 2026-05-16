"""言語ディスパッチの決定的規則（spec §5.1）。"""

from grep_analyzer.dispatch import detect_language


def test_拡張子で言語を判定する():
    assert detect_language("a/B.java", "", {}) == "java"
    assert detect_language("a/q.sql", "", {}) == "sql"
    assert detect_language("a/run.sh", "", {}) == "shell"
    assert detect_language("a/m.c", "", {}) == "c"


def test_EXEC_SQLを含むcはProCと判定する():
    assert detect_language("a/m.c", "  EXEC SQL SELECT 1;", {}) == "proc"


def test_pc拡張子はProCである():
    assert detect_language("a/m.pc", "", {}) == "proc"


def test_lang_map上書きが効く():
    assert detect_language("a/x.inc", "", {".inc": "shell"}) == "shell"


def test_判定不能はcにフォールバックする():
    assert detect_language("a/unknown.xyz", "no exec sql here", {}) == "c"


from grep_analyzer.dispatch import shebang_dialect


def test_bourne系シェバンはbourneを返す():
    assert shebang_dialect("#!/bin/sh\nCODE=1\n") == "bourne"
    assert shebang_dialect("#!/bin/bash -e\n") == "bourne"
    assert shebang_dialect("#!/usr/bin/env ksh\n") == "bourne"


def test_C系シェバンはcshellを返す():
    assert shebang_dialect("#!/bin/csh\n") == "cshell"
    assert shebang_dialect("#!/usr/bin/env tcsh\n") == "cshell"


def test_非シェルシェバンはotherを返す():
    assert shebang_dialect("#!/usr/bin/perl\n") == "other"
    assert shebang_dialect("#!/usr/bin/env python3\n") == "other"


def test_シェバン無しはNoneを返す():
    assert shebang_dialect("CODE=1\n") is None
    assert shebang_dialect("  #!/bin/sh\n") is None  # 1列目以外の #! は無効
