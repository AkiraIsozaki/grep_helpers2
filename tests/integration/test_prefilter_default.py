from grep_analyzer.pipeline import _effective_use_ripgrep


def test_effective_明示優先(monkeypatch):
    from grep_analyzer import ripgrep
    monkeypatch.setattr(ripgrep, "available", lambda: True)
    assert _effective_use_ripgrep(True, total_bytes=0, threshold=1 << 30) is True
    assert _effective_use_ripgrep(False, total_bytes=10**12, threshold=1 << 30) is False


def test_effective_既定は閾値とrg可否(monkeypatch):
    from grep_analyzer import ripgrep
    monkeypatch.setattr(ripgrep, "available", lambda: True)
    assert _effective_use_ripgrep(None, total_bytes=(1 << 30), threshold=1 << 30) is True
    assert _effective_use_ripgrep(None, total_bytes=(1 << 30) - 1, threshold=1 << 30) is False
    monkeypatch.setattr(ripgrep, "available", lambda: False)
    assert _effective_use_ripgrep(None, total_bytes=10**12, threshold=1 << 30) is False
