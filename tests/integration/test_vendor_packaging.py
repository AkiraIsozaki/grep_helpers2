import glob
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


def test_vendorバイナリが存在すればwheelに同梱される(tmp_path):
    """vendor に rg があるときのみ実行（無ければ skip）。build→wheel 展開で同梱を確認。"""
    if not glob.glob("src/grep_analyzer/vendor/ripgrep/*/rg"):
        pytest.skip("vendor バイナリ未配置（fetch_ripgrep 未実行）")
    subprocess.run([sys.executable, "-m", "build", "--wheel", "-o", str(tmp_path)],
                   check=True)
    whl = sorted(tmp_path.glob("*.whl"))[-1]
    with zipfile.ZipFile(whl) as z:
        names = z.namelist()
    assert any(n.endswith("/rg") and "vendor/ripgrep/" in n for n in names)
    assert any(n.endswith("/rg.sha256") for n in names)


def test_配備プロファイル_rg不在かつvendor空ならprefilter無効を検知(monkeypatch, tmp_path):
    """配備機(rg 不在)で vendor 空だと prefilter が恒久無効＝目標未達に静かに転落する。
    この『静かな無効化』を検知する番兵（vendor 配置忘れの早期警告）。
    _vendored_rg_path を直接モックせず、空 vendor ディレクトリを実際に走らせる。"""
    from grep_analyzer import ripgrep
    monkeypatch.setattr(ripgrep, "_VENDOR_ROOT", tmp_path)        # 実在する空ディレクトリ
    monkeypatch.setattr(ripgrep.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(ripgrep.shutil, "which", lambda _: None)
    monkeypatch.delenv("GREP_ANALYZER_RG", raising=False)
    assert ripgrep.available() is False
