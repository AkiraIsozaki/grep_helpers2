# Phase 3: encoding メモ（chardet をユニークファイル×1回へ）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** `decode_bytes` を純粋メモ化する `decode_with_memo` を導入し、`_read_meta` を「text-cache 上位 / enc-memo 下位」の階層にし、worker ローカル enc-memo を Pool 永続で hop 間共有することで、chardet（0.1MB/s）の呼び出しを「ユニークファイル×1回（worker 内）」へ削減する。**出力 TSV はバイト不変。**

**Architecture:** `encoding.decode_with_memo(memo, abspath, raw, fb)` は `decode_bytes` の純粋メモ化（同一 bytes→同一 `(text,enc,replaced)`、再 decode は保存 `replaced` で errors ポリシー一致、codec 名非等価は try/except で再計算降格）。`_read_meta` は `_FileCache` hit→即返し、miss→`decode_with_memo` で chardet 回避。`_worker_init` が worker ローカル enc-memo（LRU 予算）を生成。direct（pipeline）・finalize の再 read も memo 経由。

**Tech Stack:** Python 3.12 / pytest / multiprocessing。Phase 1/2 と独立に適用可（Phase 4 前でも後でも可）。

正本 spec: `docs/superpowers/specs/2026-05-30-perf-chardet-prefilter-design.md`（§4.2/§4.3/§6.1）。

---

## ファイル構成

- Modify: `src/grep_analyzer/encoding.py` — `decode_with_memo` 追加（`decode_bytes` 不変）。
- Create: `src/grep_analyzer/fixedpoint/_encmemo.py` — `EncMemo`（LRU 予算つき abspath→(enc,replaced)）。
- Modify: `src/grep_analyzer/fixedpoint/_scan.py` — `_read_meta` 階層化、`_worker_init`/`_scan_one`/`scan_hop` に enc-memo。
- Modify: `src/grep_analyzer/pipeline.py` — direct 経路（`pipeline.py:90`）を memo 経由。
- Modify: `src/grep_analyzer/fixedpoint/_finalize.py` — `file_meta` 再 read を memo 経由。
- Test: `tests/unit/test_encoding.py`、`tests/integration/test_enc_memo.py`。

---

## Task 1: `decode_with_memo`（decode_bytes の純粋メモ化）

**Files:** Modify `src/grep_analyzer/encoding.py` / Test `tests/unit/test_encoding.py`

- [ ] **Step 1: failing test**

```python
# tests/unit/test_encoding.py に追記
import pytest
from grep_analyzer.encoding import decode_bytes, decode_with_memo, DEFAULT_FALLBACK


@pytest.mark.parametrize("raw", [
    "abc".encode("utf-8"),
    "日本語".encode("cp932"),
    "日本語".encode("euc-jp"),
    b"\xff\xfe\x80",                     # latin-1 fallback(replace) 経路
])
def test_decode_with_memoはdecode_bytesとバイト同値(raw):
    memo = {}
    want = decode_bytes(raw, DEFAULT_FALLBACK)
    got1 = decode_with_memo(memo, "/p/x", raw, DEFAULT_FALLBACK)
    got2 = decode_with_memo(memo, "/p/x", raw, DEFAULT_FALLBACK)   # 2回目=memo hit
    assert got1 == want and got2 == want


def test_decode_with_memoはhit時chardetを呼ばない(monkeypatch):
    import grep_analyzer.encoding as enc
    calls = {"n": 0}
    real = enc.chardet.detect
    monkeypatch.setattr(enc.chardet, "detect",
                        lambda b: calls.__setitem__("n", calls["n"] + 1) or real(b))
    memo = {}
    raw = "あ".encode("euc-jp")          # utf-8 strict 失敗→chardet 経路
    decode_with_memo(memo, "/p/y", raw, DEFAULT_FALLBACK)
    decode_with_memo(memo, "/p/y", raw, DEFAULT_FALLBACK)
    assert calls["n"] == 1               # 2回目は memo hit で chardet 非実行
```

- [ ] **Step 2: run fail** — `python -m pytest tests/unit/test_encoding.py -k memo -q` → FAIL

- [ ] **Step 3: implement**（`encoding.py` 末尾に追加。`decode_bytes` は不変）

```python
def decode_with_memo(memo: dict, abspath: str, data: bytes, fallback_chain):
    """decode_bytes の純粋メモ化。memo[abspath]=(enc,replaced) を再利用し chardet を回避。"""
    hit = memo.get(abspath)
    if hit is not None:
        enc, replaced = hit
        try:
            return data.decode(enc, errors="replace" if replaced else "strict"), enc, replaced
        except (LookupError, UnicodeDecodeError):
            pass                              # codec名非等価等の保険＝再計算へ降格
    text, enc, replaced = decode_bytes(data, fallback_chain)
    memo[abspath] = (enc, replaced)
    return text, enc, replaced
```

- [ ] **Step 4: run pass** — PASS

- [ ] **Step 5: commit** — `git commit -am "feat(encoding): decode_with_memo（純粋メモ化）（Phase3 Task1）"`

---

## Task 2: `EncMemo`（LRU 予算つき enc-only メモ）

**Files:** Create `src/grep_analyzer/fixedpoint/_encmemo.py` / Test `tests/integration/test_enc_memo.py`

abspath→(enc,replaced) を件数上限つき OrderedDict で保持（無予算常駐を回避）。`get`/`put` は dict 互換（`decode_with_memo` が `memo.get`/`memo[k]=` で使えるよう `__getitem__`/`__setitem__`/`get`/`__contains__` を実装）。

- [ ] **Step 1: failing test**

```python
# tests/integration/test_enc_memo.py
from grep_analyzer.fixedpoint._encmemo import EncMemo


def test_EncMemoは件数上限で古いものを退避():
    m = EncMemo(max_entries=2)
    m["a"] = ("cp932", False); m["b"] = ("euc-jp", False)
    assert m.get("a") == ("cp932", False)
    m["c"] = ("utf-8", False)            # b を退避（a は直近 get で延命）
    assert m.get("b") is None and m.get("a") is not None and m.get("c") is not None
```

- [ ] **Step 2: run fail** — FAIL

- [ ] **Step 3: implement**

```python
# src/grep_analyzer/fixedpoint/_encmemo.py
"""worker ローカル enc-only メモ（LRU 件数予算）。値は (enc, replaced) の小タプル。"""
from collections import OrderedDict

_DEFAULT_MAX = 2_000_000        # 数百万ファイルを概ね収容しつつ常駐を有界化


class EncMemo:
    def __init__(self, max_entries: int = _DEFAULT_MAX):
        self.max = max_entries
        self._d: "OrderedDict[str, tuple]" = OrderedDict()

    def get(self, key, default=None):
        v = self._d.get(key)
        if v is not None:
            self._d.move_to_end(key)
        return v if v is not None else default

    def __contains__(self, key):
        return key in self._d

    def __getitem__(self, key):
        v = self._d[key]; self._d.move_to_end(key); return v

    def __setitem__(self, key, value):
        if key in self._d:
            del self._d[key]
        self._d[key] = value
        while len(self._d) > self.max:
            self._d.popitem(last=False)
```

- [ ] **Step 4: run pass** — PASS

- [ ] **Step 5: commit** — `git commit -am "feat(encmemo): LRU予算つき enc-only メモ（Phase3 Task2）"`

---

## Task 3: `_read_meta` 階層キャッシュ＋worker ローカル enc-memo

**Files:** Modify `src/grep_analyzer/fixedpoint/_scan.py` / Test `tests/integration/test_enc_memo.py`

`_read_meta(relpath, abspath, lang_map, fallback, cache, enc_memo=None)`: ① `cache`(text LRU) hit→即返す ② miss→`decode_with_memo(enc_memo, abspath, raw, fallback)` で chardet 回避→`detect_language`→`cache.put`。`enc_memo=None` なら従来どおり `file_meta` フル。`_worker_init` に `_WORKER_ENC = EncMemo()`、`_scan_file_worker` が `enc_memo=_WORKER_ENC` を渡す。直列 `_scan_one` は `scan_hop` から渡る enc-memo を使う。

- [ ] **Step 1: failing test**

```python
def test_read_metaはenc_memo経由でchardetを2回目回避(tmp_path, monkeypatch):
    import grep_analyzer.encoding as enc
    from grep_analyzer.fixedpoint._scan import _read_meta
    from grep_analyzer.fixedpoint._encmemo import EncMemo
    calls = {"n": 0}; real = enc.chardet.detect
    monkeypatch.setattr(enc.chardet, "detect",
                        lambda b: calls.__setitem__("n", calls["n"] + 1) or real(b))
    f = tmp_path / "a.c"; f.write_bytes("int x=1; // あ".encode("euc-jp") + b"\n")
    em = EncMemo()
    _read_meta("a.c", str(f), {}, ["cp932", "euc-jp", "latin-1"], cache=None, enc_memo=em)
    _read_meta("a.c", str(f), {}, ["cp932", "euc-jp", "latin-1"], cache=None, enc_memo=em)
    assert calls["n"] == 1
```

- [ ] **Step 2: run fail** — FAIL（`_read_meta` に `enc_memo` 引数なし）

- [ ] **Step 3: implement** — `_read_meta` を上記仕様に。`file_meta` の中身（decode→detect_language→detect_shell_dialect）を、decode 部のみ `decode_with_memo` に差し替えた経路を `_read_meta` 内に展開（`file_meta` 自体は seed/finalize 互換で温存）。`_worker_init`/`_scan_file_worker`/`_scan_one`/`scan_hop` に enc_memo を配線（直列は `make_file_cache` と同様 run 単位 EncMemo を `scan_hop` 引数で受ける）。

- [ ] **Step 4: run pass** — PASS

- [ ] **Step 5: commit** — `git commit -am "feat(scan): _read_meta 階層化と worker ローカル enc-memo（Phase3 Task3）"`

---

## Task 4: direct（pipeline）と finalize の memo 経由化

**Files:** Modify `pipeline.py`, `fixedpoint/_finalize.py` / Test `tests/integration/test_enc_memo.py`

- [ ] **Step 1: failing test**

```python
def test_direct経路は同一ファイル複数keywordでchardet1回(tmp_path, monkeypatch):
    """run 共有 enc-memo で direct の同一ファイル再 chardet を抑止。"""
    import grep_analyzer.encoding as e
    calls = {"n": 0}; real = e.chardet.detect
    monkeypatch.setattr(e.chardet, "detect",
                        lambda b: calls.__setitem__("n", calls["n"] + 1) or real(b))
    from grep_analyzer.pipeline import run, _default_opts
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_bytes("class A { int KCODE=1; } // あ".encode("euc-jp") + b"\n")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "K1.grep").write_text("A.java:1:KCODE\n", "utf-8")
    (inp / "K2.grep").write_text("A.java:1:KCODE\n", "utf-8")
    run(inp, tmp_path / "out", src, _default_opts())
    assert calls["n"] <= 1               # A.java の chardet は run 全体で 1 回
```

- [ ] **Step 2: run fail** — FAIL（現状 keyword ごとに decode_bytes ＝ 2 回）

- [ ] **Step 3: implement**
- `pipeline.run` に run 共有 `enc_memo = EncMemo()` を生成。direct の `decode_bytes(target.read_bytes(), fb)`（`pipeline.py:90`）を `decode_with_memo(enc_memo, str(target), target.read_bytes(), fb)` に。`run_fixedpoint(..., enc_memo=enc_memo)` で共有（並列 worker は別プロセスのため別メモ＝direct↔indirect 跨ぎは別物だが byte 不変、§4.2 N2）。
- `_finalize.build_indirect_hits` の `file_meta(...)`（`_finalize.py:40`）を、`state` に渡した enc_memo 経由の decode に差し替え（main プロセス実行ゆえ run 共有 memo を使える）。`encoding_of.setdefault` は不変。

- [ ] **Step 4: run pass** — PASS

- [ ] **Step 5: commit** — `git commit -am "feat(memo): direct/finalize を run 共有 enc-memo 経由に（Phase3 Task4）"`

---

## Task 5: chardet 回数の決定的ロック（cp932 コーパス・ゲート）＋ golden

**Files:** Test `tests/integration/test_enc_memo.py`, `tests/golden`

- [ ] **Step 1: chardet 回数 ≤ ユニークファイル数 の assert**

```python
def test_chardet回数はユニークファイル数以下_cp932(tmp_path, monkeypatch):
    import grep_analyzer.encoding as e
    seen = set(); real = e.chardet.detect
    monkeypatch.setattr(e.chardet, "detect", lambda b: seen.add(len(b)) or real(b))
    from grep_analyzer.pipeline import run, _default_opts
    src = tmp_path / "src"; src.mkdir()
    files = []
    for i in range(5):
        f = src / f"C{i}.java"
        f.write_bytes(f"class C{i} {{ int KCODE={i}; int r=KCODE; }} // 定数".encode("cp932") + b"\n")
        files.append(f)
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "K.grep").write_text("C0.java:1:KCODE\n", "utf-8")
    run(inp, tmp_path / "out", src, _default_opts())
    # 直列(jobs=1)＝in-process。chardet 呼び出しの「種類」はユニークファイル数(5)以下。
    assert len(seen) <= 5
```

> 直列限定（jobs=1）。並列の検証は Task で別途「worker 引数に enc が渡る配線 ＋ jobs1 とバイト一致（既存 jobs2 golden が担保）」で行う。

- [ ] **Step 2: golden 全件バイト一致＋全回帰** — `python -m pytest tests/golden -q`（不変）→ PASS。`python -m pytest -q` → PASS。

- [ ] **Step 3: commit** — `git commit -am "test(memo): chardet回数ロック(cp932)と golden 不変（Phase3 Task5）"`

---

## 自己レビュー

- **spec 被覆**: §4.2（decode_with_memo・worker ローカル・階層・LRU 予算）→ Task1/2/3。§4.3（direct/finalize memo）→ Task4。§6.1（byte 不変）→ golden（Task5）。chardet 回数ゲート（§7-8）→ Task5。✓
- **プレースホルダ**: なし（全 Task に実コード）。
- **型整合**: `decode_with_memo(memo, abspath, data, fallback_chain)`、`EncMemo(get/__setitem__/__contains__)`、`_read_meta(..., enc_memo=None)`、`run_fixedpoint(..., enc_memo=)` 一貫。
- **既知の限界（明記）**: 並列は direct↔indirect・worker 間で memo 非共有＝「ユニーク×1回」は直列性質、並列は「ファイルあたり最大 min(jobs,出現hop数)」（byte 不変・§4.2）。

## 実行ハンドオフ

Phase 3 完了後 → Phase 4（ロックステップ共有エンジン）。
