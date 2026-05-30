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
