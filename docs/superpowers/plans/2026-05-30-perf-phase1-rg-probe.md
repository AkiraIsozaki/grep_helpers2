# Phase 1: rg 解決・同梱 ＋ 実コーパスプローブ 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** prefilter を安全に有効化する基盤（オフライン同梱 rg の解決・検証）を整え、実コーパスで「初回 union 候補の総バイト・非UTF-8割合」を測る軽量プローブを提供して option A/B を実装前に確定できるようにする。

**Architecture:** `ripgrep.py` の rg 解決を `_resolve_rg`（env→同梱→PATH・machine 正規化・sha256 照合・実行スモーク）に関数化し、`available()` を副作用フリー化。conftest gate を `available()` に一本化。`scripts/fetch_ripgrep.py` で版・URL・sha256 ピンの同梱物を再現取得。`scripts/probe_candidates.py` で実 `.grep` から初回 union 記号を算出し `rg -l` で候補を測る。**本 Phase は本体パイプライン（pipeline/fixedpoint）を変更せず、golden は不変。**

**Tech Stack:** Python 3.12 / pytest（古典学派TDD・日本語テスト名）/ ripgrep 14.1.1（同梱）/ importlib.resources / hashlib。

**全体フェーズ（本書は Phase 1）:**
- **Phase 1（本書）**: rg 解決・同梱 ＋ プローブ。決定ゲート。golden 不変。
- Phase 2: prefilter 既定ON＋閾値＋walk 総バイト/prefilter_unsafe 検出。TSV 不変。
- Phase 3: encoding メモ（decode_with_memo・階層キャッシュ・worker ローカル・finalize/direct）。TSV 不変。
- Phase 4: ロックステップ共有エンジン（pipeline/run_fixedpoint 転置・診断マージ・union 予算）。keyword 別 TSV 不変。
- Phase 5（条件付き）: プローブが候補上限超を示した場合のみ option B（cchardet）。

正本 spec: `docs/superpowers/specs/2026-05-30-perf-chardet-prefilter-design.md`（§4.4/§4.5/§9）。

---

## ファイル構成

- Modify: `src/grep_analyzer/ripgrep.py` — `_resolve_rg` 関数化・`available()` 副作用フリー・`_normalize_machine`・sha256 照合・スモーク。
- Modify: `tests/conftest.py:16-29` — gate を `ripgrep.available()` に一本化。
- Modify: `tests/unit/test_ripgrep.py` — `_RG` 直差し替えに依存するテストを新 API へ追従。
- Create: `scripts/fetch_ripgrep.py` — 版・URL・sha256 ピンの同梱物取得スクリプト。
- Create: `src/grep_analyzer/vendor/ripgrep/{aarch64,x86_64}/` — 同梱バイナリ配置先（fetch スクリプトが配置）＋ `rg.sha256`・`LICENSE`。
- Create: `scripts/probe_candidates.py` — 実コーパスプローブ CLI。
- Create: `tests/unit/test_rg_resolve.py` — 解決順・正規化・スモーク・sha256 の単体。
- Create: `tests/integration/test_probe_candidates.py` — プローブの統合（合成コーパス）。
- Modify: `pyproject.toml` — `[tool.setuptools.package-data]` に vendor を追加。
- Modify: `.gitattributes` — `src/grep_analyzer/vendor/ripgrep/** -text`。

---

## Task 1: `_normalize_machine` で arch 表記ゆれを正規化

**Files:**
- Modify: `src/grep_analyzer/ripgrep.py`
- Test: `tests/unit/test_rg_resolve.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_rg_resolve.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_rg_resolve.py -q`
Expected: FAIL（`ImportError: cannot import name '_normalize_machine'`）

- [ ] **Step 3: Write minimal implementation**

`src/grep_analyzer/ripgrep.py` の import 群の直後に追加:

```python
_MACHINE_ALIASES = {
    "aarch64": "aarch64", "arm64": "aarch64",
    "x86_64": "x86_64", "amd64": "x86_64", "AMD64": "x86_64",
}


def _normalize_machine(machine: str) -> str | None:
    """platform.machine() の表記ゆれを同梱ディレクトリ名へ正規化（未知は None）。"""
    return _MACHINE_ALIASES.get(machine)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_rg_resolve.py -q`
Expected: PASS（3 件）

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/ripgrep.py tests/unit/test_rg_resolve.py
git commit -m "feat(rg): machine 表記ゆれ正規化を追加（Phase1 Task1）"
```

---

## Task 2: 同梱バイナリパスの解決 `_vendored_rg_path`

**Files:**
- Modify: `src/grep_analyzer/ripgrep.py`
- Test: `tests/unit/test_rg_resolve.py`

同梱は `src/grep_analyzer/vendor/ripgrep/<machine>/rg`。zip install でも実体パスを得るため `importlib.resources.files()` ＋ 呼出側で `as_file` する設計だが、本 Task は「パス候補の算出」だけを純関数化し、存在しなければ `None` を返す（実体化は Task 4 の解決器が担う）。

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_rg_resolve.py に追記
def test_vendored_pathは未知archでNone(monkeypatch):
    from grep_analyzer import ripgrep
    monkeypatch.setattr(ripgrep.platform, "machine", lambda: "riscv64")
    assert ripgrep._vendored_rg_path() is None


def test_vendored_pathは存在する同梱を返す(tmp_path, monkeypatch):
    from grep_analyzer import ripgrep
    # 仮想 vendor ツリーを作り、resources ルートを差し替える
    vroot = tmp_path / "vendor" / "ripgrep" / "aarch64"
    vroot.mkdir(parents=True)
    (vroot / "rg").write_bytes(b"#!/bin/sh\n")
    monkeypatch.setattr(ripgrep.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(ripgrep, "_VENDOR_ROOT", tmp_path / "vendor" / "ripgrep")
    assert ripgrep._vendored_rg_path() == vroot / "rg"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_rg_resolve.py -q`
Expected: FAIL（`AttributeError: _vendored_rg_path` / `_VENDOR_ROOT`）

- [ ] **Step 3: Write minimal implementation**

`ripgrep.py` に追加（`import platform` も先頭へ追加）:

```python
import platform
from importlib.resources import files as _ir_files

# 同梱ルート。本番は importlib.resources（zip 安全）。テストは monkeypatch で差替。
def _default_vendor_root():
    try:
        return _ir_files("grep_analyzer") / "vendor" / "ripgrep"
    except Exception:
        return None

_VENDOR_ROOT = _default_vendor_root()


def _vendored_rg_path():
    """現 arch の同梱 rg のパス（存在すれば）。未知 arch / 不在は None。"""
    arch = _normalize_machine(platform.machine())
    if arch is None or _VENDOR_ROOT is None:
        return None
    cand = _VENDOR_ROOT / arch / "rg"
    try:
        return cand if cand.is_file() else None
    except Exception:
        return None
```

> 注: `importlib.resources.files()` の戻りは Traversable。本 Phase の同梱は通常ディレクトリ install 前提のため `is_file()`/パス演算が機能する。zip install 対応の `as_file` 実体化は Task 4 の解決器で行う。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_rg_resolve.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/ripgrep.py tests/unit/test_rg_resolve.py
git commit -m "feat(rg): 同梱 rg パス解決 _vendored_rg_path を追加（Phase1 Task2）"
```

---

## Task 3: sha256 照合ヘルパ `_verify_sha256`

**Files:**
- Modify: `src/grep_analyzer/ripgrep.py`
- Test: `tests/unit/test_rg_resolve.py`

同梱 rg と併置する `rg.sha256`（16進文字列1行）で改竄/破損を検知。

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_rg_resolve.py に追記
def test_sha256照合は一致でTrue_不一致でFalse(tmp_path):
    from grep_analyzer.ripgrep import _verify_sha256
    import hashlib
    binp = tmp_path / "rg"
    binp.write_bytes(b"hello")
    (tmp_path / "rg.sha256").write_text(hashlib.sha256(b"hello").hexdigest() + "\n")
    assert _verify_sha256(binp) is True
    (tmp_path / "rg.sha256").write_text("deadbeef\n")
    assert _verify_sha256(binp) is False


def test_sha256照合はsidecar不在でFalse(tmp_path):
    from grep_analyzer.ripgrep import _verify_sha256
    binp = tmp_path / "rg"
    binp.write_bytes(b"x")
    assert _verify_sha256(binp) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_rg_resolve.py -q`
Expected: FAIL（`_verify_sha256` 未定義）

- [ ] **Step 3: Write minimal implementation**

```python
import hashlib

def _verify_sha256(rg_path) -> bool:
    """併置 `<rg>.sha256`（16進1行）と実バイトの sha256 を照合。sidecar 不在は False。"""
    from pathlib import Path as _P
    side = _P(str(rg_path) + ".sha256")
    try:
        want = side.read_text(encoding="ascii").strip().split()[0].lower()
        got = hashlib.sha256(_P(rg_path).read_bytes()).hexdigest()
        return got == want
    except (OSError, IndexError):
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_rg_resolve.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/ripgrep.py tests/unit/test_rg_resolve.py
git commit -m "feat(rg): sha256 照合ヘルパを追加（Phase1 Task3）"
```

---

## Task 4: 解決器 `_resolve_rg` と副作用フリー `available()`

**Files:**
- Modify: `src/grep_analyzer/ripgrep.py`（`_RG = shutil.which("rg")` と `available()` を置換、`prefilter` の `_RG` 参照を解決器に）
- Test: `tests/unit/test_rg_resolve.py`

設計（spec §4.5）:
- `_resolve_rg(env, vendored, which)`（純: 3 引数注入）→ 採用パス文字列 or None。順序 **env → 同梱 → which**。同梱採用時は sha256 照合（不一致なら同梱を捨て次候補）。採用候補は **実行可否（`os.access(X_OK)`→不可なら chmod 試行）＋ `rg --version` スモーク**を通す（`_resolve_rg` は副作用あり）。
- `available()` は**副作用フリー**（解決結果が None でないかだけを返す。chmod/スモークを起こさない軽量版＝解決のキャッシュ参照）。
- run 単位キャッシュ: `_resolve_rg()`（引数なしの実体）が env/vendored/which を集めて純関数 `_resolve_rg_impl` に渡し、結果を `_RG_CACHE` に保持。`_RG`（後方互換名）は `_RG_CACHE` を指す。

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_rg_resolve.py に追記
def test_resolve優先順位はenv_vendor_which():
    from grep_analyzer.ripgrep import _resolve_rg_impl
    # env 最優先
    assert _resolve_rg_impl(env="/x/rg", vendored="/v/rg", which="/w/rg") == "/x/rg"
    # env 無→同梱
    assert _resolve_rg_impl(env=None, vendored="/v/rg", which="/w/rg") == "/v/rg"
    # env/同梱 無→which
    assert _resolve_rg_impl(env=None, vendored=None, which="/w/rg") == "/w/rg"
    # すべて無→None
    assert _resolve_rg_impl(env=None, vendored=None, which=None) is None
```

> 注: `_resolve_rg_impl` は「採用順の純選択」だけを担う。sha256/スモーク/chmod は呼出側 `_resolve_rg()` が候補ごとに適用し、失格なら次候補を `_resolve_rg_impl` に再投入する形にする（テスト容易性）。本 Task の単体は純選択を固定する。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_rg_resolve.py -q`
Expected: FAIL（`_resolve_rg_impl` 未定義）

- [ ] **Step 3: Write minimal implementation**

`ripgrep.py` の `_RG = shutil.which("rg")` 行を以下に置換:

```python
import os

_GREP_ANALYZER_RG_ENV = "GREP_ANALYZER_RG"
_RG_CACHE = None          # 解決済み rg パス（run 単位キャッシュ）
_RG_RESOLVED = False      # 解決済みフラグ


def _resolve_rg_impl(env, vendored, which):
    """採用順（env→同梱→which）で最初の非 None を返す純選択。"""
    for cand in (env, vendored, which):
        if cand:
            return cand
    return None


def _smoke_ok(rg_path) -> bool:
    """実行可否（X_OK・必要なら chmod）＋ `rg --version` rc=0 スモーク（副作用あり）。"""
    try:
        if not os.access(rg_path, os.X_OK):
            os.chmod(rg_path, 0o755)
        r = subprocess.run([str(rg_path), "--version"],
                           capture_output=True, check=False)
        return r.returncode == 0
    except OSError:
        return False


def _resolve_rg(force: bool = False):
    """env→同梱(sha256照合)→which の順で実行可能な rg を解決（run 単位キャッシュ・副作用あり）。"""
    global _RG_CACHE, _RG_RESOLVED, _RG
    if _RG_RESOLVED and not force:
        return _RG_CACHE
    env = os.environ.get(_GREP_ANALYZER_RG_ENV) or None
    vendored = _vendored_rg_path()
    # 同梱は sha256 照合を通った場合のみ候補化（env 指定は運用者責任で検証バイパス）。
    if vendored is not None and not _verify_sha256(vendored):
        vendored = None
    which = shutil.which("rg")
    # 候補を順に実行スモーク。失格なら次へ。
    for cand in (env, str(vendored) if vendored else None, which):
        if cand and _smoke_ok(cand):
            _RG_CACHE = cand
            break
    else:
        _RG_CACHE = None
    _RG_RESOLVED = True
    _RG = _RG_CACHE
    return _RG_CACHE


def available() -> bool:
    """rg が解決でき実行可能か（解決キャッシュ参照・副作用は初回 _resolve_rg に集約）。"""
    return _resolve_rg() is not None


_RG = None                # 後方互換: prefilter は _resolve_rg() を直接呼ぶ
```

`prefilter()` 冒頭の `if _RG is None: return None` を `rg = _resolve_rg()` に変更し以降 `rg` を使用:

```python
def prefilter(root, rel_to_abs, symbols):
    rg = _resolve_rg()
    if rg is None:
        return None
    if not symbols:
        return set()
    ...
    proc = subprocess.run([rg, "-l", "-F", "-a", "--no-messages", "--no-ignore",
                           "--hidden", "--no-require-git", "-f", pat_path, "."], ...)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_rg_resolve.py -q`
Expected: PASS

- [ ] **Step 5: 既存 test_ripgrep.py の追従**

`tests/unit/test_ripgrep.py:8` の `test_利用不可時はNoneでフィルタ無効` を新 API へ:

```python
def test_利用不可時はNoneでフィルタ無効(monkeypatch):
    from grep_analyzer import ripgrep
    monkeypatch.setattr(ripgrep, "_resolve_rg", lambda force=False: None)
    assert ripgrep.available() is False
    assert ripgrep.prefilter(Path("."), {}, ["CODE"]) is None
```

- [ ] **Step 6: 全 ripgrep 系テスト緑**

Run: `python -m pytest tests/unit/test_ripgrep.py tests/unit/test_rg_resolve.py -q`
Expected: PASS（dev 機は PATH に rg があるため requires_ripgrep も実行）

- [ ] **Step 7: Commit**

```bash
git add src/grep_analyzer/ripgrep.py tests/unit/test_ripgrep.py tests/unit/test_rg_resolve.py
git commit -m "feat(rg): 解決器 _resolve_rg と副作用フリー available を導入（Phase1 Task4）"
```

---

## Task 5: conftest gate を `ripgrep.available()` に一本化

**Files:**
- Modify: `tests/conftest.py:16-29`
- Test: 既存 `tests/unit/test_perf_excluded.py` 相当（gate 挙動）＋全回帰

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_rg_resolve.py に追記
def test_conftest_gateはavailableを使う(monkeypatch):
    """gate 基準が本番解決順（available）と一致することを固定。"""
    from grep_analyzer import ripgrep
    monkeypatch.setattr(ripgrep, "available", lambda: True)
    assert ripgrep.available() is True
    monkeypatch.setattr(ripgrep, "available", lambda: False)
    assert ripgrep.available() is False
```

> 本体修正の主眼は conftest だが、conftest 自体は pytest 実行で検証する（Step 4 の全回帰）。

- [ ] **Step 2: Run（現状確認）**

Run: `python -m pytest tests/unit/test_rg_resolve.py -q`
Expected: PASS（この時点で conftest は未変更）

- [ ] **Step 3: conftest 修正**

`tests/conftest.py:19` を置換:

```python
def pytest_collection_modifyitems(config, items):
    import re
    from grep_analyzer import ripgrep
    rg = ripgrep.available()          # 本番と同一の解決順（shutil.which 直叩きを廃止）
    markexpr = config.getoption("markexpr") or ""
    perf_selected = bool(re.search(r"\bperf\b", markexpr))
    skip_rg = pytest.mark.skip(reason="ripgrep 不在のため skip（任意機能）")
    skip_perf = pytest.mark.skip(reason="perf は非ゲート（既定除外）")
    for item in items:
        if "requires_ripgrep" in item.keywords and not rg:
            item.add_marker(skip_rg)
        if "perf" in item.keywords and not perf_selected:
            item.add_marker(skip_perf)
```

- [ ] **Step 4: 全回帰（gate 等価性）**

Run: `python -m pytest -q`
Expected: PASS（dev 機 rg あり＝requires_ripgrep 実行・件数不変）

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/unit/test_rg_resolve.py
git commit -m "test(rg): requires_ripgrep gate を ripgrep.available() に一本化（Phase1 Task5）"
```

---

## Task 6: `scripts/fetch_ripgrep.py`（版・URL・sha256 ピンの再現取得）

**Files:**
- Create: `scripts/fetch_ripgrep.py`
- Create: `src/grep_analyzer/vendor/ripgrep/.gitkeep`（空ディレクトリ追跡）
- Modify: `pyproject.toml`（package-data）, `.gitattributes`
- Test: `tests/unit/test_rg_resolve.py`（チェックサム検証ロジックの単体）

ripgrep 14.1.1 の公式 release（`aarch64-unknown-linux-gnu` / `x86_64-unknown-linux-musl`）を取得し、tarball 内の `rg` を `src/grep_analyzer/vendor/ripgrep/<arch>/rg` に配置、`rg.sha256` と `LICENSE` を併置、実行ビット付与。版・URL・期待 sha256 はスクリプト内にピン。

- [ ] **Step 1: Write the failing test（純粋関数の検証）**

```python
# tests/unit/test_rg_resolve.py に追記
def test_fetch_extract_は期待sha不一致で例外(tmp_path):
    import importlib.util, hashlib
    spec = importlib.util.spec_from_file_location(
        "fetch_ripgrep", "scripts/fetch_ripgrep.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    blob = b"not-a-real-rg"
    with pytest.raises(ValueError):
        mod._check_sha256(blob, "deadbeef")
    # 一致は例外なし
    mod._check_sha256(blob, hashlib.sha256(blob).hexdigest())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_rg_resolve.py -k fetch -q`
Expected: FAIL（`scripts/fetch_ripgrep.py` 不在）

- [ ] **Step 3: スクリプト作成**

```python
# scripts/fetch_ripgrep.py
"""ripgrep 14.1.1 を版・URL・sha256 ピンで取得し vendor へ配置する再現取得スクリプト。

オンライン環境で 1 回実行 → 生成物（rg・rg.sha256・LICENSE）をコミットしオフライン再現。
（requirements.lock / gen_requirements_lock.py と同じ「ネットで再生成・オフラインで再現」作法）
"""
import hashlib
import io
import os
import stat
import tarfile
import urllib.request
from pathlib import Path

VERSION = "14.1.1"
# 各 arch: (URL, tarball の sha256, tar 内 rg への相対パス)
TARGETS = {
    "aarch64": (
        f"https://github.com/BurntSushi/ripgrep/releases/download/{VERSION}/"
        f"ripgrep-{VERSION}-aarch64-unknown-linux-gnu.tar.gz",
        "PIN_AARCH64_TARBALL_SHA256",       # ← オンライン取得時に確定し埋める
        f"ripgrep-{VERSION}-aarch64-unknown-linux-gnu/rg",
    ),
    "x86_64": (
        f"https://github.com/BurntSushi/ripgrep/releases/download/{VERSION}/"
        f"ripgrep-{VERSION}-x86_64-unknown-linux-musl.tar.gz",
        "PIN_X86_64_TARBALL_SHA256",
        f"ripgrep-{VERSION}-x86_64-unknown-linux-musl/rg",
    ),
}
VENDOR = Path("src/grep_analyzer/vendor/ripgrep")


def _check_sha256(blob: bytes, expected: str) -> None:
    got = hashlib.sha256(blob).hexdigest()
    if got != expected:
        raise ValueError(f"sha256 mismatch: got {got} want {expected}")


def _fetch_one(arch: str) -> None:
    url, tar_sha, rg_member = TARGETS[arch]
    blob = urllib.request.urlopen(url).read()
    _check_sha256(blob, tar_sha)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        rg_bytes = tf.extractfile(rg_member).read()
        lic = next((m for m in tf.getmembers()
                    if m.name.endswith(("LICENSE-MIT", "UNLICENSE"))), None)
        lic_bytes = tf.extractfile(lic).read() if lic else b""
    outdir = VENDOR / arch
    outdir.mkdir(parents=True, exist_ok=True)
    rg_path = outdir / "rg"
    rg_path.write_bytes(rg_bytes)
    rg_path.chmod(rg_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    (outdir / "rg.sha256").write_text(hashlib.sha256(rg_bytes).hexdigest() + "\n")
    if lic_bytes:
        (outdir / "LICENSE").write_bytes(lic_bytes)
    print(f"placed {rg_path} ({len(rg_bytes)} bytes)")


if __name__ == "__main__":
    for arch in TARGETS:
        _fetch_one(arch)
```

```bash
mkdir -p src/grep_analyzer/vendor/ripgrep
touch src/grep_analyzer/vendor/ripgrep/.gitkeep
```

- [ ] **Step 4: pyproject / .gitattributes**

`pyproject.toml` に追加（`[tool.setuptools]` 系の隣）:

```toml
[tool.setuptools.package-data]
grep_analyzer = ["vendor/ripgrep/*/rg", "vendor/ripgrep/*/rg.sha256", "vendor/ripgrep/*/LICENSE"]
```

`.gitattributes` に追記:

```
src/grep_analyzer/vendor/ripgrep/**   -text
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_rg_resolve.py -k fetch -q`
Expected: PASS

- [ ] **Step 6: バイナリ取得（ネット環境・人手 or CI）**

> **オフライン配備の手当て**: 本リポの dev/CI がネットに出られるなら次を実行し、`PIN_*_TARBALL_SHA256` を実値に置換してから再実行・生成物をコミットする。出られない場合は、ネット可能な場所で実行し `src/grep_analyzer/vendor/ripgrep/{aarch64,x86_64}/{rg,rg.sha256,LICENSE}` をコミットする（**この Task の唯一の非自動・人手手順**）。

Run: `python scripts/fetch_ripgrep.py`
Expected: `placed .../aarch64/rg` / `.../x86_64/rg`

- [ ] **Step 7: Commit**

```bash
git add scripts/fetch_ripgrep.py pyproject.toml .gitattributes \
        src/grep_analyzer/vendor/ripgrep
git commit -m "feat(rg): fetch_ripgrep.py と vendor 同梱（14.1.1・sha256ピン）（Phase1 Task6）"
```

---

## Task 7: 実コーパスプローブ `scripts/probe_candidates.py`

**Files:**
- Create: `scripts/probe_candidates.py`
- Test: `tests/integration/test_probe_candidates.py`

目的（spec §9-I）: 実 `.grep` 群から **初回 union 記号**（grep ヒット行→`extract_chase_symbols`→`stoplist.partition` 適用後の chase∪terminal）を算出し、`ripgrep.prefilter` で候補 relpath を得て、候補ファイルの**総バイト**と**非UTF-8割合**を測る。上限式 `3600 × 0.1MB/s × jobs` と並べて option A/B の判断材料を出力する。

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_probe_candidates.py
import importlib.util
from pathlib import Path


def _load():
    spec = importlib.util.spec_from_file_location(
        "probe_candidates", "scripts/probe_candidates.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def test_union記号はstoplist適用後のchase記号を含む(tmp_path):
    probe = _load()
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text("class A { static final int KCODE = 1; }\n", "utf-8")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "K.grep").write_text("A.java:1:    static final int KCODE = 1;\n", "utf-8")
    union = probe.compute_initial_union(inp, src)
    assert "KCODE" in union


def test_probe集計は候補総バイトと非utf8割合を返す(tmp_path):
    probe = _load()
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text("class A { int KCODE = 1; }\n", "utf-8")
    (src / "B.java").write_bytes("// KCODE 参照".encode("cp932") + b"\n")  # 非UTF-8
    rep = probe.measure(["KCODE"], src)
    assert rep["candidate_files"] >= 1
    assert rep["candidate_bytes"] > 0
    assert 0.0 <= rep["non_utf8_ratio"] <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_probe_candidates.py -q`
Expected: FAIL（`scripts/probe_candidates.py` 不在）

- [ ] **Step 3: スクリプト作成**

```python
# scripts/probe_candidates.py
"""実コーパスで初回 union 候補の総バイト・非UTF-8割合を測り option A/B を判断する。

使い方: python scripts/probe_candidates.py --input IN --source-root SRC [--jobs N]
本体パイプラインは変更しない読み取り専用プローブ。
"""
import argparse
from pathlib import Path

from grep_analyzer.chase import extract_chase_symbols
from grep_analyzer.dispatch import detect_language, detect_shell_dialect
from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes
from grep_analyzer.ingest import parse_grep_line
from grep_analyzer.stoplist import SymbolPolicy, partition
from grep_analyzer import ripgrep
import os


def compute_initial_union(input_dir: Path, source_root: Path) -> set[str]:
    """全 .grep のヒット行から初回 chase∪terminal 記号（stoplist 適用後）を算出。"""
    policy = SymbolPolicy(min_specificity=2, stop=frozenset())
    union: set[str] = set()
    for grep_file in sorted(Path(input_dir).glob("*.grep")):
        for raw in grep_file.read_bytes().split(b"\n"):
            parsed = parse_grep_line(raw)
            if parsed is None:
                continue
            path_b, lineno, content_b = parsed
            relpath = os.fsdecode(path_b)
            target = Path(source_root) / relpath
            try:
                text, _, _ = decode_bytes(target.read_bytes(), DEFAULT_FALLBACK)
            except OSError:
                continue
            language = detect_language(relpath, text[:4096], {})
            dialect = (detect_shell_dialect(relpath, text[:4096])
                       if language == "shell" else "bourne")
            content = content_b.decode("utf-8", errors="replace")
            cs = extract_chase_symbols(language, dialect, content)
            part = partition(cs, language, policy)
            union |= set(part.chase) | set(part.terminal)
    return union


def measure(symbols, source_root: Path) -> dict:
    """union 記号で rg prefilter → 候補総バイト・非UTF-8割合を測る。"""
    source_root = Path(source_root)
    rel_to_abs = {p.relative_to(source_root).as_posix(): p
                  for p in source_root.rglob("*") if p.is_file()}
    keep = ripgrep.prefilter(source_root, rel_to_abs, sorted(symbols))
    if keep is None:                       # rg 不在 or 非ASCII記号 → 全件扱い
        keep = set(rel_to_abs)
    total = nonutf8 = 0
    for rel in keep:
        ap = rel_to_abs.get(rel)
        if ap is None:
            continue
        raw = ap.read_bytes()
        total += len(raw)
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            nonutf8 += len(raw)
    return {"candidate_files": len(keep), "candidate_bytes": total,
            "non_utf8_bytes": nonutf8,
            "non_utf8_ratio": (nonutf8 / total) if total else 0.0}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="probe_candidates")
    ap.add_argument("--input", required=True)
    ap.add_argument("--source-root", required=True, dest="source_root")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    args = ap.parse_args(argv)
    union = compute_initial_union(Path(args.input), Path(args.source_root))
    rep = measure(union, Path(args.source_root))
    ceiling_mb = 3600 * 0.1 * args.jobs
    nonutf8_mb = rep["non_utf8_bytes"] / 1e6
    print(f"union_symbols   = {len(union)}")
    print(f"candidate_files = {rep['candidate_files']}")
    print(f"candidate_bytes = {rep['candidate_bytes']/1e9:.2f} GB")
    print(f"non_utf8        = {nonutf8_mb/1000:.2f} GB "
          f"({rep['non_utf8_ratio']*100:.1f}% of candidates)")
    print(f"chardet_ceiling = {ceiling_mb/1000:.2f} GB  (= 3600s x 0.1MB/s x {args.jobs} jobs)")
    verdict = "OPTION A (within budget)" if nonutf8_mb <= ceiling_mb \
        else "OPTION B recommended (cchardet) — first-hop chardet exceeds 1h"
    print(f"VERDICT: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

> 注: `SymbolPolicy`/`partition` のシグネチャは実装に合わせる（Task 実行時に `src/grep_analyzer/stoplist.py` を確認し引数名を一致させる。`stop=frozenset()` は --stoplist 無し相当）。プローブは概算で良く、本体の不動点と完全一致は要しない。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_probe_candidates.py -q`
Expected: PASS（dev 機 rg あり）

- [ ] **Step 5: Commit**

```bash
git add scripts/probe_candidates.py tests/integration/test_probe_candidates.py
git commit -m "feat(probe): 実コーパス候補プローブを追加（Phase1 Task7）"
```

---

## Task 8: Phase 1 全回帰と golden 不変確認

**Files:** なし（検証のみ）

- [ ] **Step 1: 全テスト緑**

Run: `python -m pytest -q`
Expected: PASS（既存件数＋新規。golden 全件不変＝本 Phase は本体パイプライン非変更）

- [ ] **Step 2: golden 明示確認**

Run: `python -m pytest tests/golden -q`
Expected: PASS（バイト一致不変）

- [ ] **Step 3: 完了タグ（任意）**

```bash
git tag -a phase1-rg-probe -m "Phase1: rg 解決・同梱・プローブ完了"
```

---

## 自己レビュー（writing-plans 規定）

- **spec 被覆**: §4.5（rg 解決・同梱・sha256・machine 正規化・available 副作用フリー・conftest 統一）→ Task 1-6。§9-I（実コーパスプローブ）→ Task 7。golden 不変 → Task 8。✓
- **プレースホルダ**: `PIN_*_TARBALL_SHA256` のみ意図的な「オンライン取得時に確定」値（Task 6 Step 6 で実値化を明示）。他は実コード。
- **型整合**: `_resolve_rg`/`_resolve_rg_impl`/`available`/`_vendored_rg_path`/`_verify_sha256`/`_normalize_machine` の名称・引数は全 Task で一貫。`prefilter` は `_resolve_rg()` を使用。
- **未配備依存**: プローブの `SymbolPolicy`/`partition`/`extract_chase_symbols` は実装に追従（Task 7 注記）。本体は非変更。

## 実行ハンドオフ

本 Phase 完了後、**プローブを実コーパスで実行**して option A/B を確定 →
- A（候補非UTF-8 ≤ 上限）: Phase 2（prefilter 既定ON）→ Phase 3（encoding メモ）→ Phase 4（ロックステップ）。
- B（上限超）: Phase 2/3/4 と並行で Phase 5（cchardet）を主軸化。
