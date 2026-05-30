"""rg バイナリ解決機構（env→同梱→which / sha256 照合 / 副作用境界）の仕様。"""

from grep_analyzer.ripgrep import _normalize_machine


def test_machine正規化はaarch64系をaarch64に():
    assert _normalize_machine("aarch64") == "aarch64"
    assert _normalize_machine("arm64") == "aarch64"


def test_machine正規化はx86系をx86_64に():
    assert _normalize_machine("x86_64") == "x86_64"
    assert _normalize_machine("amd64") == "x86_64"
    assert _normalize_machine("AMD64") == "x86_64"


def test_machine正規化は未知archでNone():
    assert _normalize_machine("riscv64") is None


def test_vendored_pathは未知archでNone(monkeypatch):
    from grep_analyzer import ripgrep
    monkeypatch.setattr(ripgrep.platform, "machine", lambda: "riscv64")
    assert ripgrep._vendored_rg_path() is None


def test_vendored_pathは存在する同梱を返す(tmp_path, monkeypatch):
    from grep_analyzer import ripgrep
    vroot = tmp_path / "vendor" / "ripgrep" / "aarch64"
    vroot.mkdir(parents=True)
    (vroot / "rg").write_bytes(b"#!/bin/sh\n")
    monkeypatch.setattr(ripgrep.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(ripgrep, "_VENDOR_ROOT", tmp_path / "vendor" / "ripgrep")
    assert ripgrep._vendored_rg_path() == vroot / "rg"


def test_sha256照合は一致でTrue_不一致でFalse(tmp_path):
    from grep_analyzer.ripgrep import _verify_sha256
    import hashlib
    binp = tmp_path / "rg"; binp.write_bytes(b"hello")
    (tmp_path / "rg.sha256").write_text(hashlib.sha256(b"hello").hexdigest() + "\n")
    assert _verify_sha256(binp) is True
    (tmp_path / "rg.sha256").write_text("deadbeef\n")
    assert _verify_sha256(binp) is False


def test_sha256照合はsidecar不在でFalse(tmp_path):
    from grep_analyzer.ripgrep import _verify_sha256
    binp = tmp_path / "rg"; binp.write_bytes(b"x")
    assert _verify_sha256(binp) is False


def test_resolve優先順位はenv_vendor_which():
    from grep_analyzer.ripgrep import _resolve_rg_impl
    assert _resolve_rg_impl(env="/x/rg", vendored="/v/rg", which="/w/rg") == "/x/rg"
    assert _resolve_rg_impl(env=None, vendored="/v/rg", which="/w/rg") == "/v/rg"
    assert _resolve_rg_impl(env=None, vendored=None, which="/w/rg") == "/w/rg"
    assert _resolve_rg_impl(env=None, vendored=None, which=None) is None


def test_resolve_sha256不一致で同梱を捨てwhichへ(tmp_path, monkeypatch):
    from grep_analyzer import ripgrep
    monkeypatch.setattr(ripgrep, "_RG_RESOLVED", False)
    v = tmp_path / "aarch64" / "rg"; v.parent.mkdir(parents=True)
    v.write_bytes(b"#!/bin/sh\nexit 0\n"); v.chmod(0o755)
    (tmp_path / "aarch64" / "rg.sha256").write_text("deadbeef\n")
    monkeypatch.setattr(ripgrep, "_VENDOR_ROOT", tmp_path)
    monkeypatch.setattr(ripgrep.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(ripgrep.shutil, "which", lambda _: "/usr/bin/rg")
    monkeypatch.setattr(ripgrep, "_smoke_ok", lambda p: p == "/usr/bin/rg")
    assert ripgrep._resolve_rg(force=True) == "/usr/bin/rg"


def test_resolve_smoke失格で次候補へ(tmp_path, monkeypatch):
    from grep_analyzer import ripgrep
    monkeypatch.setattr(ripgrep, "_RG_RESOLVED", False)
    monkeypatch.setattr(ripgrep, "_vendored_rg_path", lambda: None)
    monkeypatch.setenv("GREP_ANALYZER_RG", "/broken/rg")
    monkeypatch.setattr(ripgrep.shutil, "which", lambda _: "/usr/bin/rg")
    monkeypatch.setattr(ripgrep, "_smoke_ok", lambda p: p == "/usr/bin/rg")
    assert ripgrep._resolve_rg(force=True) == "/usr/bin/rg"


def test_sha256_sidecar破損はFalse(tmp_path):
    from grep_analyzer.ripgrep import _verify_sha256
    b = tmp_path / "rg"; b.write_bytes(b"x")
    (tmp_path / "rg.sha256").write_text("")
    assert _verify_sha256(b) is False


def test_available副作用フリー_smokeを呼ばない(monkeypatch, tmp_path):
    from grep_analyzer import ripgrep
    called = {"smoke": 0}
    monkeypatch.setattr(ripgrep, "_smoke_ok",
                        lambda p: called.__setitem__("smoke", called["smoke"] + 1) or True)
    monkeypatch.setenv("GREP_ANALYZER_RG", "/x/rg")
    assert ripgrep.available() is True
    assert called["smoke"] == 0
