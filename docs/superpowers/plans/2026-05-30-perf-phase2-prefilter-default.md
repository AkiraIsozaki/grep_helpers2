# Phase 2: prefilter 既定ON ＋ 閾値 ＋ walk 総バイト/prefilter_unsafe 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** rg 解決可能かつコーパス総バイト ≥ 閾値（既定 1 GiB）のとき prefilter を既定 ON にし、非ASCII透過（UTF-16/32 BOM 等）ファイルは walk 段で検出して常に走査対象に残すことで、TSV 行を不変に保ったまま prefilter を安全に有効化する。

**Architecture:** `walk.collect_files` を `(files, total_bytes, unsafe_rels)` を返すよう拡張。`_is_binary` を BOM 検査つきに拡張し非ASCII透過を `unsafe_rels` へ。`EngineOptions.use_ripgrep` を tri-state（`None`=閾値判定/`True`/`False`=明示）化し `ripgrep_threshold_bytes` を追加。`pipeline.run` が総バイト＋rg可否＋明示から effective を決め、prefilter 走査集合を `keep_rels ∪ unsafe_rels` にする。**本体の分類・スニペット・順序は不変＝golden は小規模 OFF 据置で完全不変、prefilter ON でも TSV 行バイト一致。**

**Tech Stack:** Python 3.12 / pytest（古典学派TDD・日本語名）。

正本 spec: `docs/superpowers/specs/2026-05-30-perf-chardet-prefilter-design.md`（§4.4/§5/§6）。Phase 1（rg 解決）完了が前提。

---

## ファイル構成

- Modify: `src/grep_analyzer/walk.py` — `_is_binary`→`_classify_bytes`（binary/unsafe 判定）、`walk_files`/`collect_files` の戻りに `total_bytes`・`unsafe_rels`。
- Modify: `src/grep_analyzer/fixedpoint/_options.py` — `use_ripgrep: bool | None`、`ripgrep_threshold_bytes: int`。
- Modify: `src/grep_analyzer/cli.py` — `--no-use-ripgrep`、`--ripgrep-threshold-bytes`、tri-state 配線。
- Modify: `src/grep_analyzer/pipeline.py` — effective prefilter 決定＋`collect_files` 新戻り＋`run_fixedpoint` への `unsafe_rels` 受け渡し。
- Modify: `src/grep_analyzer/fixedpoint/__init__.py` — prefilter 走査集合 `keep_rels ∪ unsafe_rels`、`run_fixedpoint(..., unsafe_rels=...)`。
- Test: `tests/unit/test_walk.py`、`tests/unit/test_cli_phase3.py`、`tests/integration/test_prefilter_default.py`。

---

## Task 1: `walk._classify_bytes` で binary/非ASCII透過(unsafe)を判定

**Files:** Modify `src/grep_analyzer/walk.py` / Test `tests/unit/test_walk.py`

非ASCII透過 = UTF-16/32 BOM を持つ（NUL 持ちは従来どおり binary skip）。先頭プレフィクスを 64KiB に拡張。

- [ ] **Step 1: failing test**

```python
# tests/unit/test_walk.py に追記
from grep_analyzer.walk import _classify_bytes  # ("ok"|"binary"|"unsafe")


def test_classify_NUL含みはbinary():
    assert _classify_bytes(b"abc\x00def") == "binary"


def test_classify_utf16BOMはunsafe():
    assert _classify_bytes(b"\xff\xfe" + "漢字".encode("utf-16-le")) == "unsafe"
    assert _classify_bytes(b"\xfe\xff") == "unsafe"            # UTF-16-BE BOM
    assert _classify_bytes(b"\xff\xfe\x00\x00") == "unsafe"    # UTF-32-LE BOM


def test_classify_純ASCIIはok():
    assert _classify_bytes(b"int CODE = 1;\n") == "ok"
```

- [ ] **Step 2: run fail** — `python -m pytest tests/unit/test_walk.py -k classify -q` → FAIL（`_classify_bytes` 未定義）

- [ ] **Step 3: implement**

`walk.py` の `_is_binary` を残しつつ（後方互換）新関数を追加:

```python
_PREFIX = 64 * 1024
# UTF-32 BOM を先に判定（UTF-16 BOM は UTF-32-LE の接頭辞のため順序重要）。
_BOMS = (b"\x00\x00\xfe\xff", b"\xff\xfe\x00\x00", b"\xff\xfe", b"\xfe\xff")


def _classify_bytes(head: bytes) -> str:
    """先頭バイト列を 'binary'(NUL) / 'unsafe'(UTF-16/32 BOM=非ASCII透過) / 'ok' に分類。"""
    for bom in _BOMS:
        if head.startswith(bom):
            return "unsafe"
    if b"\x00" in head:
        return "binary"
    return "ok"
```

`_is_binary(path)` は `_classify_bytes(open(path,'rb').read(_PREFIX)) == "binary"` に内部委譲（既存呼出互換）。

- [ ] **Step 4: run pass** — `python -m pytest tests/unit/test_walk.py -k classify -q` → PASS

- [ ] **Step 5: commit** — `git add -A && git commit -m "feat(walk): 非ASCII透過(unsafe)判定を追加（Phase2 Task1）"`

---

## Task 2: `walk_files`/`collect_files` を total_bytes・unsafe_rels つきに

**Files:** Modify `src/grep_analyzer/walk.py` / Test `tests/unit/test_walk.py`

`walk_files` の2段目で `_classify_bytes` を1回使い、binary は skip（診断 `walk_skipped_binary`）、unsafe は yield しつつ unsafe 集合へ。`collect_files` は `(files, total_bytes, unsafe_rels)` を返す。

- [ ] **Step 1: failing test**

```python
def test_collect_filesはtotalbytesとunsafeを返す(tmp_path):
    from grep_analyzer.walk import collect_files
    from grep_analyzer.diagnostics import Diagnostics
    (tmp_path / "a.c").write_text("int CODE=1;\n", "utf-8")          # ok
    (tmp_path / "u.c").write_bytes(b"\xff\xfe" + "漢=1".encode("utf-16-le"))  # unsafe
    (tmp_path / "b.bin").write_bytes(b"x\x00y")                       # binary skip
    files, total, unsafe = collect_files(
        tmp_path, include=[], exclude=[], follow_symlinks=False,
        max_file_bytes=5_000_000, diag=Diagnostics())
    rels = {r for r, _ in files}
    assert "a.c" in rels and "u.c" in rels and "b.bin" not in rels
    assert "u.c" in unsafe and "a.c" not in unsafe
    assert total == (tmp_path / "a.c").stat().st_size + (tmp_path / "u.c").stat().st_size
```

- [ ] **Step 2: run fail** — FAIL（戻り値 3-tuple でない＝unpack error）

- [ ] **Step 3: implement**

`walk_files` の2段目ループ（現 `walk.py:99-115`）を改修。`_is_binary` 呼出を `_classify_bytes` に置換し、`total_bytes` 累算・`unsafe` 収集。`walk_files` は `(relpath, abspath, kind)` を yield（kind∈{"ok","unsafe"}）、`collect_files` が集約:

```python
def walk_files(root, *, include, exclude, follow_symlinks, max_file_bytes, diag):
    # ...（1段目は不変）...
    for relpath, abspath in sorted(candidates):
        try:
            if abspath.stat().st_size > max_file_bytes:
                diag.add("walk_skipped_large", relpath); continue
            head = open(abspath, "rb").read(_PREFIX)
            kind = _classify_bytes(head)
            if kind == "binary":
                diag.add("walk_skipped_binary", relpath); continue
            real = os.path.realpath(abspath)
        except OSError:
            diag.add("walk_unreadable", relpath); continue
        if real in seen_real:
            diag.add("symlink_dedup", f"{relpath} -> {seen_real[real]}"); continue
        seen_real[real] = relpath
        yield relpath, abspath, kind


def collect_files(root, *, include, exclude, follow_symlinks, max_file_bytes, diag):
    files, unsafe, total = [], set(), 0
    for relpath, abspath, kind in walk_files(
            root, include=include, exclude=exclude, follow_symlinks=follow_symlinks,
            max_file_bytes=max_file_bytes, diag=diag):
        files.append((relpath, abspath))
        total += abspath.stat().st_size
        if kind == "unsafe":
            unsafe.add(relpath)
    return files, total, unsafe
```

> 注: `total += stat()` は yield 済みのみ（max/binary/dedup 除外後）＝spec §5 の確定スナップショット。`open().read` のファイルハンドルは `with` で閉じる（実装時に `with open(...) as f: head = f.read(_PREFIX)`）。

- [ ] **Step 4: callers 追従** — `pipeline.py:46` の `files = collect_files(...)` を `files, total_bytes, unsafe_rels = collect_files(...)` に。`fixedpoint/__init__.py:48` の内部 `walk.walk_files(...)` 利用箇所（`files=None` 経路）も 3-tuple yield に追従（`[(r,a) for r,a,_ in walk.walk_files(...)]`）。

- [ ] **Step 5: run pass + 既存 walk テスト緑** — `python -m pytest tests/unit/test_walk.py -q` → PASS（既存テストが 2-tuple 前提なら追従修正）

- [ ] **Step 6: commit** — `git commit -am "feat(walk): collect_files に total_bytes/unsafe_rels を追加（Phase2 Task2）"`

---

## Task 3: `EngineOptions` tri-state ＋ 閾値、CLI 配線

**Files:** Modify `_options.py`, `cli.py` / Test `tests/unit/test_cli_phase3.py`

- [ ] **Step 1: failing test**

```python
# tests/unit/test_cli_phase3.py に追記
def test_use_ripgrep既定はNone_明示でTrueFalse():
    from grep_analyzer.cli import _build_opts
    base = ["--input", "i", "--output", "o", "--source-root", "s"]
    assert _build_opts(base).use_ripgrep is None
    assert _build_opts(base + ["--use-ripgrep"]).use_ripgrep is True
    assert _build_opts(base + ["--no-use-ripgrep"]).use_ripgrep is False


def test_閾値既定は1GiB_可変():
    from grep_analyzer.cli import _build_opts
    base = ["--input", "i", "--output", "o", "--source-root", "s"]
    assert _build_opts(base).ripgrep_threshold_bytes == 1 << 30
    assert _build_opts(base + ["--ripgrep-threshold-bytes", "100"]).ripgrep_threshold_bytes == 100
```

- [ ] **Step 2: run fail** — FAIL（`use_ripgrep` が bool・属性 `ripgrep_threshold_bytes` 無し）

- [ ] **Step 3: implement**

`_options.py`: `use_ripgrep: bool | None = None`、`ripgrep_threshold_bytes: int = 1 << 30` 追加。
`cli.py`: `--use-ripgrep` を `store_const const=True`、`--no-use-ripgrep` を `store_const const=False`、同一 dest `use_ripgrep` default `None`。`--ripgrep-threshold-bytes type=int default=1<<30`。`_opts_from` で両者を渡す。

```python
# cli.py _make_parser 内（既存 --use-ripgrep 行を置換）
g = parser.add_mutually_exclusive_group()
g.add_argument("--use-ripgrep", dest="use_ripgrep", action="store_const", const=True, default=None)
g.add_argument("--no-use-ripgrep", dest="use_ripgrep", action="store_const", const=False)
parser.add_argument("--ripgrep-threshold-bytes", type=int, default=1 << 30,
                    dest="ripgrep_threshold_bytes")
```

- [ ] **Step 4: run pass** — PASS

- [ ] **Step 5: commit** — `git commit -am "feat(cli): use_ripgrep tri-state と閾値オプション（Phase2 Task3）"`

---

## Task 4: `pipeline.run` で effective prefilter を決定し配線

**Files:** Modify `pipeline.py`, `fixedpoint/__init__.py` / Test `tests/integration/test_prefilter_default.py`

effective ルール: `use_ripgrep is True` → ON / `is False` → OFF / `None` → `ripgrep.available() and total_bytes >= threshold`。

- [ ] **Step 1: failing test**

```python
# tests/integration/test_prefilter_default.py
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
```

- [ ] **Step 2: run fail** — FAIL（`_effective_use_ripgrep` 未定義）

- [ ] **Step 3: implement**

`pipeline.py`:

```python
from grep_analyzer import ripgrep


def _effective_use_ripgrep(explicit, total_bytes, threshold) -> bool:
    if explicit is not None:
        return explicit
    return ripgrep.available() and total_bytes >= threshold
```

`run()` 内: `files, total_bytes, unsafe_rels = collect_files(...)` に変更。effective を算出し、`opts` を `dataclasses.replace(opts, use_ripgrep=effective)` して `run_fixedpoint(..., files=files, unsafe_rels=unsafe_rels)` に渡す（`run_fixedpoint` 内の `opts.use_ripgrep` は bool 前提のまま機能）。

- [ ] **Step 4: `run_fixedpoint` の prefilter 走査集合**

`fixedpoint/__init__.py` の `run_fixedpoint(..., files=None, unsafe_rels=None)` を追加。prefilter 経路（現 `:73-76`）を:

```python
scan_files = files
if opts.use_ripgrep:
    keep_rels = _rg.prefilter(source_root, state.rel_to_abs, scan_symbols)
    if keep_rels is not None:
        safe_keep = keep_rels | (unsafe_rels or set())   # 非ASCII透過は常に走査対象に残す
        scan_files = [(r, a) for r, a in files if r in safe_keep]
```

- [ ] **Step 5: run pass** — PASS

- [ ] **Step 6: commit** — `git commit -am "feat(prefilter): 閾値ベース既定ON と unsafe 常走査を配線（Phase2 Task4）"`

---

## Task 5: 不変条件テスト（prefilter on/off で TSV 行一致・unsafe 常走査）

**Files:** Test `tests/integration/test_prefilter_default.py`

- [ ] **Step 1: failing/regression test（requires_ripgrep）**

```python
import dataclasses
import pytest
from pathlib import Path
from grep_analyzer.pipeline import run, _default_opts


@pytest.mark.requires_ripgrep
def test_prefilter_onoffでTSV行バイト一致(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text("class A { static final int KCODE = 1; int x = KCODE; }\n", "utf-8")
    (src / "B.java").write_text("class B { int y = 0; }\n", "utf-8")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "K.grep").write_text("A.java:1:    static final int KCODE = 1;\n", "utf-8")

    def runit(flag):
        out = tmp_path / f"out_{flag}"; 
        opts = dataclasses.replace(_default_opts(), use_ripgrep=flag)
        run(inp, out, src, opts)
        return (out / "KCODE.tsv").read_bytes()
    assert runit(True) == runit(False)        # 行は prefilter 有無で不変


@pytest.mark.requires_ripgrep
def test_unsafe_utf16BOMファイルはprefilterで脱落しない(tmp_path):
    """BOM 付き UTF-16・先頭 CJK・後方 ASCII 識別子が prefilter ON でも走査される。"""
    src = tmp_path / "src"; src.mkdir()
    body = ("漢" * 5000 + "\nint KCODE = 1;\n")
    (src / "U.java").write_bytes(b"\xff\xfe" + body.encode("utf-16-le"))
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "K.grep").write_text("dummy.java:1:KCODE\n", "utf-8")  # seed は別途
    # 期待: U.java が unsafe 判定で scan_files に残り、ON/OFF で出力一致（前テストと同枠）
```

> 注: 2 つ目の具体 assert は実装時に「ON/OFF の TSV バイト一致」に揃える（unsafe 集合経由で U.java が落ちないことの e2e 確認）。

- [ ] **Step 2-4: run / 確認** — `python -m pytest tests/integration/test_prefilter_default.py -q`（dev 機 rg あり）→ PASS

- [ ] **Step 5: commit** — `git commit -am "test(prefilter): on/off TSV一致と unsafe 常走査の不変条件（Phase2 Task5）"`

---

## Task 6: golden 不変＋閾値番兵＋全回帰

**Files:** Test `tests/golden`（実行のみ）, `tests/integration/test_prefilter_default.py`

- [ ] **Step 1: golden 最大ケース総バイト < 閾値の番兵**

```python
def test_golden最大ケース総バイトは閾値未満():
    """既定閾値 1GiB により golden は全て OFF 据置＝診断含め完全不変であることの番兵。"""
    import os
    root = Path("tests/golden/cases")
    biggest = max((sum(f.stat().st_size for f in (c / "src").rglob("*") if f.is_file())
                   for c in root.iterdir() if (c / "src").is_dir()), default=0)
    assert biggest < (1 << 30)
```

- [ ] **Step 2: golden 全件＋全回帰** — `python -m pytest tests/golden -q` → PASS（バイト一致不変）。`python -m pytest -q` → PASS。

- [ ] **Step 3: commit** — `git commit -am "test(prefilter): golden不変番兵と全回帰（Phase2 Task6）"`

---

## 自己レビュー

- **spec 被覆**: §5（tri-state・閾値・総バイト確定スナップショット）→ Task3/4。§4.4（unsafe を walk 段検出・常走査）→ Task1/2/4/5。§6（on/off TSV 一致・golden 不変）→ Task5/6。✓
- **プレースホルダ**: Task5 の2つ目テストの具体 assert は実装時に「ON/OFF バイト一致」へ確定（注記済）。他は実コード。
- **型整合**: `collect_files`→`(files, total_bytes, unsafe_rels)` を全 caller（pipeline・fixedpoint）で追従。`use_ripgrep: bool|None`、`_effective_use_ripgrep(explicit,total_bytes,threshold)->bool`、`run_fixedpoint(...,unsafe_rels=)` 一貫。

---

## rev.2 補遺（計画レビュー第1R反映・上記タスクへの確定上書き）

### C1/C2: 既存契約を壊さない最小破壊設計に変更

`walk_files` の **公開 2-tuple yield（`relpath, abspath`）は不変**に保つ（`test_walk.py:15/40/96`・`test_ripgrep.py:69`・`fixedpoint/__init__.py:48` の 2-tuple unpack を壊さない）。`collect_files`（既存・`list[tuple]` 返し）も**不変**に温存（`test_fixedpoint.py:176` の `files=collect_files(...)` 直渡しを壊さない）。

代わりに **新 API `collect_files_ex(...) -> (files, total_bytes, unsafe_rels)` を追加**し、`pipeline.run` のみがこれを使う。`collect_files_ex` は内部生成器 `_walk_classified`（3-tuple `relpath, abspath, kind` を yield・本 Phase 専用）を回して total/unsafe を集約する。Task2 のファイル構成・Step を「`collect_files`/`walk_files` 改変」から「`collect_files_ex`/`_walk_classified` 新設（既存非改変）」に置換。Task2 Step4 の caller 追従は **`pipeline.py:46` の1箇所のみ**（`collect_files`→`collect_files_ex`）になり、他テストは無改変で緑。

### C3: 既存 CLI テストの追従

`tests/integration/test_cli.py:27` の `assert o.use_ripgrep is False` を **`assert o.use_ripgrep is None`** に更新（tri-state 既定）。テスト名/docstring の「既定OFF」も「既定=閾値判定(None)」に改訂。Task3 のファイル構成に `tests/integration/test_cli.py` を追加。

### H2: `files=None` 内部 walk 経路の unsafe

`run_fixedpoint`（`files=None` 経路）は本番 pipeline からは常に `files`＋`unsafe_rels` 付きで呼ばれる。`files=None` 直接呼び出し（テスト等）は **unsafe 保護外＝呼出側責任**と明記（spec §4.4 の主経路は pipeline 経由で保証）。C1 回帰テスト（Phase4 でなく本 Phase の Task5）は必ず `pipeline.run` 経由にする。

### H1: golden 回帰の前倒し

Task4 Step6 の直後に **`pytest tests/golden -q`（バイト一致）を必須**化（閾値ロジック実装直後に早期検知）。Task6 まで待たない。

### H3: Task5 二つ目テストの確定（プレースホルダ排除）

`U.java`（BOM 付き UTF-16・先頭 CJK 5000字・末尾 `int KCODE = 1;`）を **seed 直接ヒット元**にし、別ファイル不要にする。grep は `U.java:5001:int KCODE = 1;`（実 lineno に合わせる）。assert は **ON/OFF で `KCODE.tsv` がバイト一致**（unsafe 判定で U.java が prefilter ON でも scan に残ることを e2e 固定）。`detect_language` が UTF-16 復号後テキストで java と判定されることも前提に含める。

### 確定事項まとめ（実装者向け）

- 変更ファイルは `collect_files_ex`/`_walk_classified` 新設・`_classify_bytes` 追加（`walk.py`）、`_options.py`、`cli.py`、`pipeline.py`、`fixedpoint/__init__.py`（prefilter 集合のみ）。**既存 `walk_files`/`collect_files` は無改変**。
- `_BOMS` の並びは UTF-32 を UTF-16 より先（接頭辞衝突回避）＝レビュー確認済で正しい。

## 実行ハンドオフ

Phase 2 完了後 → Phase 3（encoding メモ）。
