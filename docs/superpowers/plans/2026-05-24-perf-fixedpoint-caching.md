# 不動点パス perf 改善（lazy parse / hop間キャッシュ / rg既定 / 並列再利用）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 不動点（indirect 追跡）パスの冗長な再読込・再復号・再 tree-sitter パース・プロセス再起動を排し、**出力 byte 不変（golden 一致）**のまま高速化する。

**Architecture:** 5 つの独立変更を優先度順に積む。(#2) `_scan_one` で symbol ヒットまで tree-sitter parse を遅延、(#1) abspath→復号メタの byte 予算つき LRU を hop 間で共有、(#3) `rg` を PATH 検出したら prefilter を既定 ON、(#6) direct パスで物理行分割と is_file を relpath 単位にキャッシュ、(#5) `multiprocessing.Pool` を run 単位で 1 回だけ生成して hop/chunk 間で再利用。各タスクは golden 全件 byte 一致を完了条件とする。

**Tech Stack:** Python 3.12 / pytest / tree-sitter 0.23 / pyahocorasick / ripgrep（任意）/ multiprocessing。

**不変条件（全タスク共通の完了条件）:**
- `pytest tests/golden -q` が全件 PASS（TSV/diagnostics の byte 一致）。
- `pytest tests/integration/test_perf_caching.py tests/integration/test_inv1_items_per_mb.py -q` が PASS。
- 変更は出力に影響しない純粋なメモ化／走査範囲の縮小のみ（ソースは run 中不変が前提）。

---

## File Structure

- `tests/perf/test_perf.py` — 不動点ベンチ追加（Task 0）。
- `src/grep_analyzer/fixedpoint/_scan.py` — lazy parse・LRU・worker 再利用の中心（Task 1,2,5）。
- `src/grep_analyzer/fixedpoint/__init__.py` — run 単位の file_cache / pool 生成・受け渡し（Task 2,5）。
- `src/grep_analyzer/cli.py` / `src/grep_analyzer/pipeline.py` — rg 既定解決（Task 3）。
- `src/grep_analyzer/pipeline.py` — direct パスの relpath 単位キャッシュ（Task 6）。
- `src/grep_analyzer/snippet/__init__.py` — `build_snippet(lines=...)` 受領口（Task 6）。
- `tests/integration/test_perf_caching.py` — 振る舞い回帰の追加先（Task 1,2,6,5）。

---

## Task 0: 不動点ベンチを追加（測定ギャップを埋める）

**Files:**
- Modify: `tests/perf/test_perf.py`

既存 `test_scale` は seed が最小形で不動点を起動しない（perf レポート注記）。多シンボル×多ホップの実測線を足し、以後の改善を可視化する。**本タスクは production コード非変更。**

- [ ] **Step 1: ベンチを追記**

`tests/perf/test_perf.py` 末尾に追加:

```python
@pytest.mark.perf
@pytest.mark.parametrize("n", [300, 600])
def test_fixedpoint_heavy(tmp_path, n):
    """不動点多ホップの実測。corpus は相互参照(u{i}=S{ref})で連鎖を作るため、
    実ファイル行を seed にすると extract_chase_symbols が連鎖を起動する
    (test_calibrate_items_per_mb と同じ起動条件)。"""
    from tests.perf.corpus_gen import generate
    src = tmp_path / "src"; generate(src, seed=7, n_files=n)
    c0_line = (src / "pkg0" / "C0.java").read_text("utf-8").splitlines()[0]
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "S0.grep").write_text(f"pkg0/C0.java:1:{c0_line}\n", "utf-8")
    out = tmp_path / "o"
    t0 = time.perf_counter()
    main(["--input", str(inp), "--output", str(out), "--source-root", str(src)])
    dt = time.perf_counter() - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(f"PERF fixedpoint n={n} dt={dt:.3f}s rss_kb={rss}")
```

- [ ] **Step 2: ベースライン取得**

Run: `python -m pytest tests/perf/test_perf.py::test_fixedpoint_heavy -m perf -s -q`
Expected: PASS。`PERF fixedpoint n=300 ...` / `n=600 ...` の dt/rss を控える（改善前基準）。

- [ ] **Step 3: golden ベースライン確認**

Run: `python -m pytest tests/golden tests/integration/test_perf_caching.py -q`
Expected: 全 PASS（着手前の緑を確認）。

- [ ] **Step 4: Commit**

```bash
git add tests/perf/test_perf.py
git commit -m "$(cat <<'EOF'
test(perf): 不動点多ホップの非ゲートベンチを追加（改善前基準の可視化）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 1: #2 tree-sitter parse の遅延（symbol ヒットまで）

**Files:**
- Modify: `src/grep_analyzer/fixedpoint/_scan.py:34-73`（`_scan_one`）
- Test: `tests/integration/test_perf_caching.py`

現状 `_scan_one` は AST 言語なら automaton 0 ヒットでも先頭で `parse_tree` 済み。最初の symbol ヒットまで遅延すれば、追跡シンボルを含まない大半のファイルでパースが消える。**出力ロジックは不変（順序・分岐そのまま、生成タイミングのみ後ろ倒し）。**

- [ ] **Step 1: 失敗するテストを書く**

`tests/integration/test_perf_caching.py` 末尾に追加:

```python
def test_scan_はsymbol非ヒットのファイルをparseしない(tmp_path, monkeypatch):
    """automaton 0 ヒットのファイルは tree-sitter parse されない（lazy parse）。
    rg prefilter で対象が絞られると区別不能になるため use_ripgrep=False で単離。"""
    import dataclasses
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text("class A { static final int KW = 1; }\n", "utf-8")
    n_noise = 12
    for i in range(n_noise):
        (src / f"N{i}.java").write_text(f"class N{i} {{ int z{i} = {i}; }}\n", "utf-8")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "KW.grep").write_text(
        "A.java:1:class A { static final int KW = 1; }\n", "utf-8")
    calls = _count_parses(monkeypatch)
    opts = dataclasses.replace(_default_opts(), use_ripgrep=False)
    rc = run(input_dir=inp, output_dir=tmp_path / "o", source_root=src, opts=opts)
    assert rc == 0
    # KW を含まない N*.java は parse されない（残るは A.java の direct/seed 数件のみ）。
    assert calls["n"] < n_noise
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest "tests/integration/test_perf_caching.py::test_scan_はsymbol非ヒットのファイルをparseしない" -q`
Expected: FAIL（現状は eager parse で `calls["n"] >= n_noise`）。

- [ ] **Step 3: `_scan_one` を lazy 化**

`src/grep_analyzer/fixedpoint/_scan.py` の `_scan_one` 本体を次に置換（`raw`/`file_meta` 行は維持）:

```python
def _scan_one(relpath, abspath, automaton_obj, lang_map, fallback):
    raw = Path(abspath).read_bytes()
    text, enc, replaced, language, dialect = file_meta(
        relpath, raw, lang_map, fallback_chain=fallback)
    found = []
    if automaton_obj is not None:
        is_ast = language in _AST_CHASERS
        ts_root = None
        ang_root = None
        spans = []
        parsed = False                      # 最初の symbol ヒットまで parse を遅延
        for i, line in enumerate(text.split("\n"), start=1):
            symbols = list(automaton.scan_line(automaton_obj, line))
            if not symbols:
                continue
            if is_ast and not parsed:
                parsed = True
                try:
                    ts_root = parse_tree(language, text)
                except Exception:
                    ts_root = None
                if ts_root is not None and language == "typescript":
                    spans = inline_template_spans(text)
            cs = None
            if ts_root is not None:
                if spans and any(s <= i - 1 <= e for s, e in spans):
                    if ang_root is None:
                        try:
                            ang_root = parse_tree("angular_inline", text)
                        except Exception:
                            ang_root = None
                    cs = (extract_chase_symbols_from_root("angular_inline", ang_root, i)
                          if ang_root is not None else None)
                else:
                    cs = extract_chase_symbols_from_root(language, ts_root, i)
            for symbol in symbols:
                found.append((symbol, i, line, cs))
    return relpath, enc, replaced, language, dialect, found
```

- [ ] **Step 4: テスト緑を確認**

Run: `python -m pytest "tests/integration/test_perf_caching.py::test_scan_はsymbol非ヒットのファイルをparseしない" -q`
Expected: PASS。

- [ ] **Step 5: 不変条件を確認**

Run: `python -m pytest tests/golden tests/integration/test_perf_caching.py -q`
Expected: 全 PASS（byte 不変）。

- [ ] **Step 6: Commit**

```bash
git add src/grep_analyzer/fixedpoint/_scan.py tests/integration/test_perf_caching.py
git commit -m "$(cat <<'EOF'
perf: _scan_one の tree-sitter parse を symbol ヒットまで遅延（出力不変）

automaton 0 ヒットのファイルを丸ごとパースしないことで、不動点 hop の
非マッチ多数ファイルのパースを排除。golden byte 一致・perf_caching 緑。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: #1 hop 間 LRU ファイルキャッシュ（byte 予算つき・O(1) 維持）

**Files:**
- Modify: `src/grep_analyzer/fixedpoint/_scan.py`（LRU・`_read_meta`・`_scan_one`/`scan_hop` 引数）
- Modify: `src/grep_analyzer/fixedpoint/__init__.py`（run 単位 cache 生成・受け渡し）
- Test: `tests/integration/test_perf_caching.py`

abspath→`(text,enc,replaced,language,dialect)` を **byte 予算つき LRU** で hop 間共有し、再読込・再 chardet・再言語判定を抑止する。**tree は容量が大きく予算管理困難なため意図的に保持しない**（再 parse は #2 lazy が大半を回避）。予算上限＝定数ゆえ常駐メモリは O(1)。

- [ ] **Step 1: 失敗する単体テストを書く**

`tests/integration/test_perf_caching.py` 末尾に追加:

```python
def test_FileCache_はLRUとbyte予算で退避する():
    from grep_analyzer.fixedpoint._scan import _FileCache
    c = _FileCache(budget=10)                  # text 長 10 文字ぶんのみ常駐可
    meta = lambda s: (s, "utf-8", False, "java", "bourne")
    c.put("a", meta("aaaaa"))                  # 5
    c.put("b", meta("bbbbb"))                  # +5 = 10（ちょうど）
    assert c.get("a") is not None and c.get("b") is not None
    c.put("c", meta("ccccc"))                  # +5 → 15 超過 → LRU(a) 退避
    assert c.get("a") is None                  # a は退避済み
    assert c.get("b") is not None and c.get("c") is not None


def test_read_meta_は同一abspathを2回読まない(tmp_path, monkeypatch):
    from grep_analyzer.fixedpoint import _scan
    f = tmp_path / "C.java"
    f.write_text("class C { int KW = 1; }\n", "utf-8")
    calls = {"n": 0}
    real = _scan.file_meta

    def spy(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(_scan, "file_meta", spy)
    cache = _scan._FileCache()
    a = _scan._read_meta("C.java", str(f), {}, ["cp932"], cache)
    b = _scan._read_meta("C.java", str(f), {}, ["cp932"], cache)
    assert a == b
    assert calls["n"] == 1                      # 2 回目はキャッシュ命中
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest "tests/integration/test_perf_caching.py::test_FileCache_はLRUとbyte予算で退避する" "tests/integration/test_perf_caching.py::test_read_meta_は同一abspathを2回読まない" -q`
Expected: FAIL（`_FileCache`/`_read_meta` 未定義）。

- [ ] **Step 3: `_scan.py` に LRU と `_read_meta` を追加**

`src/grep_analyzer/fixedpoint/_scan.py` の import 群に追加:

```python
from collections import OrderedDict
```

`file_meta` 定義の直後に追加:

```python
_FILE_CACHE_BUDGET = 64 * 1024 * 1024   # 復号テキスト常駐の上限（定数＝常駐 O(1)）


class _FileCache:
    """abspath→(text,enc,replaced,language,dialect) の byte 予算つき LRU。

    hop 間で再読込・再復号・再言語判定を抑止する。tree は保持しない
    （巨大ファイルで予算が破綻するため。再 parse は lazy parse が回避）。
    キーは abspath（run 内で一意・ソースは run 中不変前提でメモ化は出力不変）。
    """

    def __init__(self, budget: int = _FILE_CACHE_BUDGET):
        self.budget = budget
        self._d: "OrderedDict[str, tuple]" = OrderedDict()
        self._bytes = 0

    def get(self, key: str):
        v = self._d.get(key)
        if v is not None:
            self._d.move_to_end(key)
        return v

    def put(self, key: str, value: tuple) -> None:
        if key in self._d:
            self._bytes -= len(self._d[key][0])
            del self._d[key]
        self._d[key] = value
        self._bytes += len(value[0])
        while self._bytes > self.budget and len(self._d) > 1:
            _, old = self._d.popitem(last=False)
            self._bytes -= len(old[0])


def _read_meta(relpath, abspath, lang_map, fallback, cache):
    """file_meta 結果を cache 経由で取得（cache=None は従来どおり毎回読込）。"""
    if cache is not None:
        hit = cache.get(abspath)
        if hit is not None:
            return hit
    meta = file_meta(relpath, Path(abspath).read_bytes(), lang_map, fallback_chain=fallback)
    if cache is not None:
        cache.put(abspath, meta)
    return meta
```

`_scan_one` のシグネチャと先頭 2 行を変更:

```python
def _scan_one(relpath, abspath, automaton_obj, lang_map, fallback, cache=None):
    text, enc, replaced, language, dialect = _read_meta(
        relpath, abspath, lang_map, fallback, cache)
```
（`raw = Path(abspath).read_bytes()` と既存 `file_meta(...)` 行は削除。以降の本体は Task 1 のまま。）

- [ ] **Step 4: `scan_hop` 単一プロセス経路へ cache を結線**

`scan_hop` のシグネチャに `file_cache=None` を追加し、`jobs<=1` 経路の `_scan_one` 呼出へ渡す:

```python
def scan_hop(scan_symbols, scan_files, opts, nchunks, file_cache=None):
    ...
        else:
            automaton_obj = automaton.build(chunk)
            res = [_scan_one(relpath, str(abspath), automaton_obj,
                             opts.lang_map, fallback, cache=file_cache)
                   for relpath, abspath in scan_files]
```

- [ ] **Step 5: run 単位の cache を生成して渡す**

`src/grep_analyzer/fixedpoint/__init__.py` の import に追加:

```python
from grep_analyzer.fixedpoint._scan import scan_hop, make_file_cache
```
（`make_file_cache` を `_scan.py` に追加: ）

```python
def make_file_cache():
    """run 単位の hop 間ファイルキャッシュを生成する。"""
    return _FileCache()
```

`run_fixedpoint` 内、`progress.start(...)` の直後に:

```python
    file_cache = make_file_cache()
```
`scan_hop` 呼出を変更:

```python
            pass_results, n_actual_chunks = scan_hop(
                scan_symbols, scan_files, opts, nchunks, file_cache=file_cache)
```

- [ ] **Step 6: テスト緑を確認**

Run: `python -m pytest "tests/integration/test_perf_caching.py::test_FileCache_はLRUとbyte予算で退避する" "tests/integration/test_perf_caching.py::test_read_meta_は同一abspathを2回読まない" -q`
Expected: PASS。

- [ ] **Step 7: 不変条件を確認**

Run: `python -m pytest tests/golden tests/integration/test_perf_caching.py tests/integration/test_inv1_items_per_mb.py -q`
Expected: 全 PASS（byte 不変・memory 不変条件維持）。

- [ ] **Step 8: Commit**

```bash
git add src/grep_analyzer/fixedpoint/_scan.py src/grep_analyzer/fixedpoint/__init__.py tests/integration/test_perf_caching.py
git commit -m "$(cat <<'EOF'
perf: 不動点 hop 間の復号メタを byte 予算つき LRU でキャッシュ（出力不変）

abspath→(text,enc,lang,dialect) を 64MiB 予算 LRU で hop 間共有し、再読込・
再 chardet・再言語判定を排除。tree は非保持で常駐メモリ O(1) を維持。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: #3 ripgrep prefilter を既定 ON（rg 検出時）

**Files:**
- Modify: `src/grep_analyzer/cli.py:38`（`--use-ripgrep` を opt-out 可に）, `:54-70`（解決）
- Modify: `src/grep_analyzer/pipeline.py:28-32`（`_default_opts` の既定）
- Test: `tests/integration/test_cli.py`（新規ケース追記）

`rg` を PATH 検出したら prefilter 既定 ON。`--no-use-ripgrep` で明示 OFF を残す。prefilter は走査範囲の縮小のみ（除外 relpath は automaton 0 ヒット確定）で出力不変＝golden で保証。

- [ ] **Step 1: 失敗するテストを書く**

`tests/integration/test_cli.py` 末尾に追加:

```python
def test_use_ripgrep既定はrg検出で自動ON(monkeypatch):
    from grep_analyzer import ripgrep
    from grep_analyzer.cli import _build_opts
    monkeypatch.setattr(ripgrep, "available", lambda: True)
    assert _build_opts(["--input", "i", "--output", "o", "--source-root", "s"]).use_ripgrep is True
    monkeypatch.setattr(ripgrep, "available", lambda: False)
    assert _build_opts(["--input", "i", "--output", "o", "--source-root", "s"]).use_ripgrep is False


def test_no_use_ripgrepで明示OFF(monkeypatch):
    from grep_analyzer import ripgrep
    from grep_analyzer.cli import _build_opts
    monkeypatch.setattr(ripgrep, "available", lambda: True)
    o = _build_opts(["--input", "i", "--output", "o", "--source-root", "s", "--no-use-ripgrep"])
    assert o.use_ripgrep is False


def test_use_ripgrepで明示ON(monkeypatch):
    from grep_analyzer import ripgrep
    from grep_analyzer.cli import _build_opts
    monkeypatch.setattr(ripgrep, "available", lambda: False)
    o = _build_opts(["--input", "i", "--output", "o", "--source-root", "s", "--use-ripgrep"])
    assert o.use_ripgrep is True
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/integration/test_cli.py -k ripgrep -q`
Expected: FAIL（現状 `--use-ripgrep` は store_true で既定 False・`--no-use-ripgrep` 未定義）。

- [ ] **Step 3: cli.py を opt-out 対応＋自動解決に**

`src/grep_analyzer/cli.py` 冒頭 import に追加:

```python
from grep_analyzer import ripgrep
```
`--use-ripgrep` の行を置換:

```python
    parser.add_argument("--use-ripgrep", action=argparse.BooleanOptionalAction,
                        default=None, dest="use_ripgrep")
```
`_opts_from` の `use_ripgrep=args.use_ripgrep,` を置換:

```python
        use_ripgrep=(args.use_ripgrep if args.use_ripgrep is not None
                     else ripgrep.available()),
```

- [ ] **Step 4: `_default_opts` の既定も自動解決に**

`src/grep_analyzer/pipeline.py` の `_default_opts` を変更（import 済みの `ripgrep` を使う）。先頭 import に:

```python
from grep_analyzer import ripgrep
```
`_default_opts` の `return EngineOptions(...)` に `use_ripgrep=ripgrep.available(),` を追加:

```python
    return EngineOptions(
        max_depth=10, min_specificity=2, stoplist_path=None, lang_map={},
        include=[], exclude=list(DEFAULT_EXCLUDE), jobs=1, follow_symlinks=False,
        max_file_bytes=5_000_000, max_symbols=100_000, max_paths=1000,
        use_ripgrep=ripgrep.available())
```

- [ ] **Step 5: テスト緑を確認**

Run: `python -m pytest tests/integration/test_cli.py -k ripgrep -q`
Expected: PASS。

- [ ] **Step 6: 不変条件を確認（rg 在環境で golden が prefilter 経路を踏む）**

Run: `python -m pytest tests/golden tests/integration -q`
Expected: 全 PASS（rg 既定 ON でも TSV/diagnostics byte 一致）。

- [ ] **Step 7: Commit**

```bash
git add src/grep_analyzer/cli.py src/grep_analyzer/pipeline.py tests/integration/test_cli.py
git commit -m "$(cat <<'EOF'
perf: ripgrep prefilter を rg 検出時の既定 ON に（--no-use-ripgrep で opt-out）

走査範囲を symbol 部分文字列を含む relpath に限定（出力不変＝golden 保証）。
既定経路でも prefilter を踏むため hop あたりの I/O・parse を削減。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: #6 direct パスの relpath 単位キャッシュ（is_file / 物理行分割）

**Files:**
- Modify: `src/grep_analyzer/snippet/__init__.py:25-39`（`build_snippet(lines=...)`）
- Modify: `src/grep_analyzer/pipeline.py:70-113`（cur_ctx に物理行・is_file）
- Test: `tests/integration/test_perf_caching.py`

高ヒット密度（1 ファイルに多数ヒット）で、`target.is_file()` の毎ヒット stat と `build_snippet` 内 `_physical_lines` の毎ヒット再分割を relpath 単位 1 回に集約する。`missing_source` 診断は**毎ヒット発火を維持**（§10.3）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/integration/test_perf_caching.py` 末尾に追加:

```python
def test_direct_path_は同一ファイルへのヒット数に比例して物理行分割しない(tmp_path, monkeypatch):
    import grep_analyzer.snippet as snip
    calls = {"n": 0}
    real = snip._physical_lines

    def spy(text):
        calls["n"] += 1
        return real(text)

    monkeypatch.setattr(snip, "_physical_lines", spy)

    def run_hits(sub, n):
        s = tmp_path / sub / "src"; (s / "pkg").mkdir(parents=True)
        body = ["class C {"] + [f"  // KW {i}" for i in range(n)] + ["}"]
        (s / "pkg" / "C.java").write_text("\n".join(body) + "\n", "utf-8")
        i_ = tmp_path / sub / "in"; i_.mkdir(parents=True)
        (i_ / "KW.grep").write_text(
            "\n".join(f"pkg/C.java:{i + 2}:  // KW {i}" for i in range(n)) + "\n", "utf-8")
        calls["n"] = 0
        run(input_dir=i_, output_dir=tmp_path / sub / "o", source_root=s, opts=_default_opts())
        return calls["n"]

    assert run_hits("a", 1) == run_hits("b", 8)   # ヒット数に依らず一定


def test_missing_source_は欠落ファイルへのヒット数ぶん発火する(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "KW.grep").write_text(
        "no/such.java:1:KW\nno/such.java:2:KW\nno/such.java:3:KW\n", "utf-8")
    out = tmp_path / "o"
    run(input_dir=inp, output_dir=out, source_root=src, opts=_default_opts())
    diag = (out / "diagnostics.txt").read_text("utf-8")
    summary = {}
    in_sum = False
    for ln in diag.splitlines():
        if ln == "# summary":
            in_sum = True; continue
        if ln == "# detail":
            break
        if in_sum and "\t" in ln:
            k, v = ln.split("\t", 1); summary[k] = v
    assert summary.get("missing_source") == "3"
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest "tests/integration/test_perf_caching.py::test_direct_path_は同一ファイルへのヒット数に比例して物理行分割しない" "tests/integration/test_perf_caching.py::test_missing_source_は欠落ファイルへのヒット数ぶん発火する" -q`
Expected: 1 件目 FAIL（毎ヒット分割で one != many）、2 件目はベースラインで PASS（回帰ロック）。

- [ ] **Step 3: `build_snippet` に `lines` 受領口を追加**

`src/grep_analyzer/snippet/__init__.py` の `build_snippet` シグネチャと先頭を変更:

```python
def build_snippet(language: str, dialect: str, file_text: str,
                  lineno: int, cache: dict | None = None,
                  lines: list[str] | None = None) -> str:
    ...
    lines = lines if lines is not None else _physical_lines(file_text)
```
（以降の本体不変。`lines=None` の既存呼出＝従来挙動。）

- [ ] **Step 4: pipeline で relpath 単位に is_file / 物理行をキャッシュ**

`src/grep_analyzer/pipeline.py` の direct ループを変更。`_physical_lines` を import:

```python
from grep_analyzer.snippet._sanitize_line import _physical_lines
```
ループ内の is_file チェック〜cur_ctx 構築を次に置換（`cur_is_file` を relpath 単位で確定し、欠落は毎ヒット診断）:

```python
            relpath = os.fsdecode(path_bytes)
            content = content_bytes.decode(grep_enc, errors="replace")
            if relpath != cur_relpath:
                target = Path(source_root) / relpath
                cur_is_file = target.is_file()
                if cur_is_file:
                    file_text, enc, replaced = decode_bytes(target.read_bytes(), fb)
                    sample = file_text[:4096]
                    language = detect_language(relpath, sample, lang_map)
                    dialect = (detect_shell_dialect(relpath, sample)
                               if language == "shell" else "bourne")
                    unsupported = (
                        not extension_resolves_language(relpath, lang_map)
                        and shebang_dialect(sample) is not None
                        and shebang_language(sample) is None)
                    cur_ctx = (file_text, enc, replaced, language, dialect,
                               unsupported, {}, _physical_lines(file_text))
                cur_relpath = relpath
            if not cur_is_file:
                diag.add("missing_source", relpath)
                continue
            (file_text, enc, replaced, language, dialect,
             unsupported, tree_cache, phys_lines) = cur_ctx
```
`build_snippet` 呼出に `lines=phys_lines` を追加:

```python
                snippet=build_snippet(language, dialect, file_text, lineno,
                                      cache=tree_cache, lines=phys_lines),
```
また関数冒頭の初期化に `cur_is_file = False` を追加（`cur_relpath = None` の隣）。

- [ ] **Step 5: テスト緑を確認**

Run: `python -m pytest "tests/integration/test_perf_caching.py::test_direct_path_は同一ファイルへのヒット数に比例して物理行分割しない" "tests/integration/test_perf_caching.py::test_missing_source_は欠落ファイルへのヒット数ぶん発火する" -q`
Expected: PASS。

- [ ] **Step 6: 不変条件を確認**

Run: `python -m pytest tests/golden tests/integration -q`
Expected: 全 PASS（byte 不変・診断件数不変）。

- [ ] **Step 7: Commit**

```bash
git add src/grep_analyzer/snippet/__init__.py src/grep_analyzer/pipeline.py tests/integration/test_perf_caching.py
git commit -m "$(cat <<'EOF'
perf: direct パスの is_file/物理行分割を relpath 単位にキャッシュ（出力不変）

高ヒット密度で毎ヒットの stat と _physical_lines 再分割を 1 回化。missing_source
は毎ヒット発火を維持（§10.3 件数不変）。build_snippet に lines 受領口を追加。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: #5 multiprocessing.Pool を run 単位で再利用（jobs>1）

**Files:**
- Modify: `src/grep_analyzer/fixedpoint/_scan.py`（worker・`scan_hop`・`make_pool`）
- Modify: `src/grep_analyzer/fixedpoint/__init__.py`（pool ライフサイクル）
- Test: `tests/integration/test_perf_caching.py`

現状は chunk×hop ごとに Pool を生成・破棄。run 単位で 1 度だけ生成し、chunk の automaton は **worker 側で signature 変化時のみ再構築**（symbols は chunk ごと temp ファイル経由で軽量伝達）。worker は LRU cache を保持し、pool 永続化で hop 間キャッシュ（#1）が並列でも効く。**出力は jobs=1 と同値（決定性は既存の relpath 集約＋再ソートが担保）。**

- [ ] **Step 1: 失敗するテストを書く**

`tests/integration/test_perf_caching.py` 末尾に追加:

```python
def test_pool_はrun単位で1回だけ生成される(tmp_path, monkeypatch):
    """jobs>1 の複数 hop でも Pool 生成は 1 回（chunk×hop 再生成しない）。"""
    import dataclasses
    import multiprocessing
    from grep_analyzer.fixedpoint import _scan
    # 連鎖を生む corpus（S0→参照→…）。実ファイル行 seed で chase 起動。
    from tests.perf.corpus_gen import generate
    src = tmp_path / "src"; generate(src, seed=7, n_files=60)
    c0 = (src / "pkg0" / "C0.java").read_text("utf-8").splitlines()[0]
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "S0.grep").write_text(f"pkg0/C0.java:1:{c0}\n", "utf-8")

    n_pools = {"n": 0}
    real = _scan.make_pool

    def spy(opts):
        p = real(opts)
        if p is not None:
            n_pools["n"] += 1
        return p

    monkeypatch.setattr(_scan, "make_pool", spy)
    opts = dataclasses.replace(_default_opts(), jobs=2)
    rc = run(input_dir=inp, output_dir=tmp_path / "o", source_root=src, opts=opts)
    assert rc == 0
    assert n_pools["n"] == 1


def test_jobs2の出力はjobs1と同値(tmp_path):
    """並列でも TSV byte 一致（決定性）。"""
    import dataclasses
    from tests.perf.corpus_gen import generate

    def run_with(sub, jobs):
        src = tmp_path / sub / "src"; generate(src, seed=7, n_files=60)
        c0 = (src / "pkg0" / "C0.java").read_text("utf-8").splitlines()[0]
        i_ = tmp_path / sub / "in"; i_.mkdir(parents=True)
        (i_ / "S0.grep").write_text(f"pkg0/C0.java:1:{c0}\n", "utf-8")
        out = tmp_path / sub / "o"
        run(input_dir=i_, output_dir=out, source_root=src,
            opts=dataclasses.replace(_default_opts(), jobs=jobs))
        return (out / "S0.tsv").read_text("utf-8-sig")

    assert run_with("j1", 1) == run_with("j2", 2)
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest "tests/integration/test_perf_caching.py::test_pool_はrun単位で1回だけ生成される" -q`
Expected: FAIL（`_scan.make_pool` 未定義）。

- [ ] **Step 3: `_scan.py` の worker を pool 再利用形に**

`src/grep_analyzer/fixedpoint/_scan.py` の import に追加:

```python
import json
import tempfile
```
worker グローバルと init/worker 本体を次に置換（`_worker_init`/`_scan_file_worker` を差し替え、`make_pool` を追加）:

```python
_WORKER_LANG_MAP: dict[str, str] | None = None
_WORKER_FALLBACK: list[str] | None = None
_WORKER_AUTOMATON = None
_WORKER_SIG = None
_WORKER_CACHE: "_FileCache | None" = None


def _worker_init(lang_map, fallback) -> None:
    """Pool worker 初期化（run 単位 1 回）。automaton は chunk 到来時に遅延構築。"""
    global _WORKER_LANG_MAP, _WORKER_FALLBACK, _WORKER_CACHE, _WORKER_SIG, _WORKER_AUTOMATON
    _WORKER_LANG_MAP = lang_map
    _WORKER_FALLBACK = fallback
    _WORKER_CACHE = _FileCache()
    _WORKER_SIG = None
    _WORKER_AUTOMATON = None


def _scan_file_worker(args):
    """Pool worker 本体：signature 変化時のみ automaton を再構築して 1 ファイル走査。"""
    relpath, abspath, sig, sym_path = args
    global _WORKER_AUTOMATON, _WORKER_SIG
    if sig != _WORKER_SIG:
        with open(sym_path, encoding="utf-8") as f:
            _WORKER_AUTOMATON = automaton.build(json.load(f))
        _WORKER_SIG = sig
    return _scan_one(relpath, abspath, _WORKER_AUTOMATON,
                     _WORKER_LANG_MAP, _WORKER_FALLBACK, cache=_WORKER_CACHE)


def make_pool(opts):
    """jobs>1 のとき run 単位の Pool を 1 度だけ生成する（jobs<=1 は None）。"""
    if opts.jobs <= 1:
        return None
    return multiprocessing.Pool(
        opts.jobs, initializer=_worker_init,
        initargs=(opts.lang_map, list(opts.encoding_fallback)))
```
（旧 `_WORKER_AUTOMATON=None` 群・旧 `_worker_init`・旧 `_scan_file_worker` は上記で置換。互換 `_scan_file`/`_scan_one` は維持。）

- [ ] **Step 4: `scan_hop` を渡された pool で実行**

`scan_hop` のシグネチャに `pool=None` を追加し、並列経路を temp ファイル＋sig に変更:

```python
def scan_hop(scan_symbols, scan_files, opts, nchunks, file_cache=None, pool=None):
    ...
    for chunk in chunks:
        if opts.jobs > 1 and pool is not None:
            with tempfile.NamedTemporaryFile("w", suffix=".sym", delete=False,
                                             encoding="utf-8") as sf:
                json.dump(chunk, sf)
                sym_path = sf.name
            try:
                res = pool.map(
                    _scan_file_worker,
                    [(relpath, str(abspath), sym_path, sym_path)
                     for relpath, abspath in scan_files])
            finally:
                Path(sym_path).unlink(missing_ok=True)
        else:
            automaton_obj = automaton.build(chunk)
            res = [_scan_one(relpath, str(abspath), automaton_obj,
                             opts.lang_map, fallback, cache=file_cache)
                   for relpath, abspath in scan_files]
        ...
```
（sig＝sym_path：chunk ごと一意。pool.map は全タスク完了までブロックするため unlink 前に worker は読了。）

- [ ] **Step 5: run_fixedpoint で pool を 1 度だけ生成・破棄**

`src/grep_analyzer/fixedpoint/__init__.py` の import を更新:

```python
from grep_analyzer.fixedpoint._scan import scan_hop, make_file_cache, make_pool
```
`run_fixedpoint` の try ブロックを pool 管理で包む。`file_cache = make_file_cache()` の直後を変更:

```python
    file_cache = make_file_cache()
    pool = make_pool(opts)
    try:
        hop = 1
        while state.chase_active or state.terminal_active:
            ...
            pass_results, n_actual_chunks = scan_hop(
                scan_symbols, scan_files, opts, nchunks,
                file_cache=file_cache, pool=pool)
            ...
        indirect = build_indirect_hits(state)
        progress.done()
        return indirect
    finally:
        if pool is not None:
            pool.close()
            pool.join()
        state.edge_store.close()
```

- [ ] **Step 6: テスト緑を確認**

Run: `python -m pytest "tests/integration/test_perf_caching.py::test_pool_はrun単位で1回だけ生成される" "tests/integration/test_perf_caching.py::test_jobs2の出力はjobs1と同値" -q`
Expected: PASS。

- [ ] **Step 7: 不変条件を確認（jobs>1 既存テスト含む）**

Run: `python -m pytest tests/golden tests/integration tests/unit -q`
Expected: 全 PASS。

- [ ] **Step 8: Commit**

```bash
git add src/grep_analyzer/fixedpoint/_scan.py src/grep_analyzer/fixedpoint/__init__.py tests/integration/test_perf_caching.py
git commit -m "$(cat <<'EOF'
perf: multiprocessing.Pool を run 単位で再利用し worker キャッシュを永続化（出力不変）

chunk×hop ごとの Pool 再生成を排除。chunk の automaton は worker 側で signature
変化時のみ再構築（symbols は temp ファイル経由）。worker LRU が hop 間で効く。
jobs=1/2 で TSV byte 一致を機械保証。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: 最終ベンチ・全テスト・perf レポート追記

**Files:**
- Modify: `docs/superpowers/plans/phase3-perf-report.md`（改善後 dt/rss 追記）

- [ ] **Step 1: 全テスト**

Run: `python -m pytest -q`
Expected: 全 PASS（perf マーカは別途）。

- [ ] **Step 2: 改善後ベンチ**

Run: `python -m pytest tests/perf/test_perf.py -m perf -s -q`
Expected: PASS。Task 0 控え値と比較し `test_fixedpoint_heavy` の dt 改善を確認。

- [ ] **Step 3: レポート追記**

`docs/superpowers/plans/phase3-perf-report.md` 末尾に改善前後の `PERF fixedpoint n=300/600` dt/rss を表で追記し、適用した #1/#2/#3/#5/#6 を明記。

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/phase3-perf-report.md
git commit -m "$(cat <<'EOF'
docs(perf): 不動点パス改善（lazy parse/LRU/rg 既定/pool 再利用/direct cache）の前後計測を追記

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

- **#2 lazy parse**: Task 1。0 ヒットファイルの parse 排除を spy で検証＋golden 不変。✓
- **#1 LRU hop 間キャッシュ**: Task 2。byte 予算 LRU・`_read_meta` メモ化・run 単位 cache 結線。O(1) 維持（tree 非保持）。✓
- **#3 rg 既定 ON**: Task 3。BooleanOptionalAction で opt-out 維持、`available()` 解決を cli/_default_opts 両方に。golden で不変。✓
- **#6 direct cache**: Task 6。is_file/物理行を relpath 単位化、missing_source 毎ヒット維持。✓
- **#5 pool 再利用**: Task 5。run 単位 pool＋sig 駆動 automaton 再構築＋worker LRU。jobs1=jobs2 同値を検証。✓
- **型整合**: `make_file_cache`/`make_pool`/`_FileCache`/`_read_meta`/`scan_hop(..., file_cache, pool)`/`build_snippet(..., lines=)` を定義タスクと利用タスクで一致確認。✓
- **placeholder 無**: 全コードブロックに実体あり。✓
- **測定**: Task 0 で前、Task 7 で後。✓
