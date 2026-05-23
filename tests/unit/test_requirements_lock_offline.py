"""オフライン再現スモーク（非ゲート＝@pytest.mark.perf・spec §11/WS5）。"""

import subprocess
import sys
import venv
import pytest


@pytest.mark.perf
def test_クリーンvenvで_require_hashes_install成功(tmp_path):
    v = tmp_path / "v"
    venv.create(v, with_pip=True)
    pip = v / "bin" / "pip"
    r = subprocess.run(
        [str(pip), "install", "--no-index", "--find-links", "wheelhouse",
         "--require-hashes", "-r", "requirements.lock"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    py = v / "bin" / "python"
    imp = subprocess.run(
        [str(py), "-c", "import tree_sitter,tree_sitter_java,tree_sitter_c,"
         "tree_sitter_python,tree_sitter_javascript,tree_sitter_typescript,"
         "ahocorasick,chardet,pytest"], capture_output=True, text=True)
    assert imp.returncode == 0, imp.stderr
