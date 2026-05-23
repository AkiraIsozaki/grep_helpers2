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
    # 注: 入力は EXEC SQL を含まない文字列であること（spec §5.1 手順4 が未知拡張子にも
    # 適用されるため。旧フィクスチャ "no exec sql here" は \bEXEC\s+SQL\b に誤マッチした）
    assert detect_language("a/unknown.xyz", "plain text only", {}) == "c"


from grep_analyzer.dispatch import shebang_dialect
from grep_analyzer.dispatch import shebang_language


def test_shebang_languageは対応言語かNoneを返す():
    assert shebang_language("#!/bin/sh\n") == "shell"
    assert shebang_language("#!/usr/bin/perl\n") == "perl"
    assert shebang_language("#!/usr/bin/env groovy\n") == "groovy"
    assert shebang_language("#!/usr/bin/python3\n") == "python"   # track A で追加
    assert shebang_language("#!/usr/bin/env node\n") == "javascript"   # track A で追加
    assert shebang_language("X=1\n") is None                  # シェバン無し


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


from grep_analyzer.dispatch import extension_resolves_language


def test_csh拡張子はshellと判定する():
    assert detect_language("a/run.csh", "", {}) == "shell"
    assert detect_language("a/run.tcsh", "", {}) == "shell"


def test_拡張子なしでもシェル系シェバンならshellと判定する():
    assert detect_language("bin/deploy", "#!/bin/csh\nset X = 1\n", {}) == "shell"
    assert detect_language("bin/backup", "#!/bin/sh\nX=1\n", {}) == "shell"


def test_拡張子なしperlシェバンはperlと判定する():
    # v2(track B): perl は新 language。版番号付き basename も剥がして解決(I-6)。
    assert detect_language("bin/tool", "#!/usr/bin/perl\nmy $x=1;\n", {}) == "perl"
    assert detect_language("bin/t2", "#!/usr/bin/perl5.36\n", {}) == "perl"
    assert detect_language("bin/t3", "#!/usr/bin/env groovy\n", {}) == "groovy"


def test_拡張子なしpythonシェバンはpythonと判定する():
    # python は track A で追加済み（dispatch Task 4）
    assert detect_language("bin/p", "#!/usr/bin/python3\nx=1\n", {}) == "python"


def test_新拡張子の言語判定():
    assert detect_language("a/pkg.pkb", "", {}) == "sql"
    assert detect_language("a/spec.pks", "", {}) == "sql"
    assert detect_language("a/s.pl", "", {}) == "perl"
    assert detect_language("a/M.pm", "", {}) == "perl"
    assert detect_language("a/b.groovy", "", {}) == "groovy"
    assert detect_language("a/build.gradle", "", {}) == "groovy"


def test_拡張子なしEXEC_SQLはProCにフォールバックする():
    # spec §5.1 手順4: 未知拡張子でも EXEC SQL を含めば Pro*C（新仕様の明示回帰）
    assert detect_language("x/embedded", "void f(){ EXEC SQL SELECT 1; }", {}) == "proc"


def test_拡張子で言語が確定するかを判定できる():
    # Task 7 の unsupported_shebang を spec §5.1 手順3 の範囲に限定するための述語
    assert extension_resolves_language("a/m.c", {}) is True
    assert extension_resolves_language("a/q.sql", {}) is True
    assert extension_resolves_language("a/r.csh", {}) is True
    assert extension_resolves_language("bin/tool", {}) is False          # 拡張子なし
    assert extension_resolves_language("a/x.inc", {".inc": "shell"}) is True  # lang_map
    assert extension_resolves_language("a/unknown.xyz", {}) is False


from grep_analyzer.dispatch import detect_shell_dialect


def test_csh拡張子はcshell方言():
    assert detect_shell_dialect("a/run.csh", "set X = 1\n") == "cshell"
    assert detect_shell_dialect("a/run.tcsh", "") == "cshell"


def test_sh系拡張子はbourne方言():
    assert detect_shell_dialect("a/run.sh", "X=1\n") == "bourne"
    assert detect_shell_dialect("a/run.ksh", "") == "bourne"


def test_シェバンは拡張子より優先される():
    # 既知シェル拡張子でもシェバンが方言を上書きする（spec §5.1「言語判定と独立」）
    assert detect_shell_dialect("a/run.sh", "#!/bin/csh\nset X = 1\n") == "cshell"
    assert detect_shell_dialect("a/run.csh", "#!/bin/sh\nX=1\n") == "bourne"


def test_拡張子なしシェバンなしはbourne既定():
    assert detect_shell_dialect("bin/deploy", "X=1\n") == "bourne"


def test_ts_tsx_js_py拡張子を解決する():
    from grep_analyzer.dispatch import detect_language
    assert detect_language("a.ts", "", {}) == "typescript"
    assert detect_language("a.tsx", "", {}) == "tsx"
    assert detect_language("a.js", "", {}) == "javascript"
    assert detect_language("a.mjs", "", {}) == "javascript"
    assert detect_language("a.jsx", "", {}) == "javascript"
    assert detect_language("a.py", "", {}) == "python"


def test_shebang_node_python_を解決する():
    from grep_analyzer.dispatch import detect_language, shebang_language
    assert detect_language("noext", "#!/usr/bin/env node\n", {}) == "javascript"
    assert detect_language("noext2", "#!/usr/bin/python3\n", {}) == "python"
    assert shebang_language("#!/usr/bin/env node\n") == "javascript"
    assert shebang_language("#!/usr/bin/python3\n") == "python"
