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
