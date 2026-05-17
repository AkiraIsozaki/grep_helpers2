# grep_analyzer Phase 3（規模・運用）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 既定起動で Phase 2b と 1 バイト不変を保ちつつ、大規模 kw の Excel 互換 part 分割・kw 単位 resume の原子性＋再生成同値保証・診断 §10.3 縮約（§8.4 全件性免除）・出力/フォールバック encoding 配線・ハッシュ固定オフライン再現ビルド・非ゲート perf ベースラインを実装し、v1 出荷可能にする。

**Architecture:** 出力確定を単一モジュール `output_writer` に集約（安定ソート→`_canonical_data_blob` 正規化→part 分割→各 part 原子書込→manifest 原子確定→孤児クリーンアップ）。完了判定は `resume.is_complete`（manifest存在∧全part実在∧行数∧data_sha256∧版/定数の5条件）。決定的コア（fixedpoint/model/budget 関数/encoding.decode_bytes）は不変。`budget._ITEMS_PER_MB` のみ perf 証跡と共に一度だけ較正。

**Tech Stack:** Python 3.12 / pytest>=8（実環境 pytest 9）/ 標準ライブラリ（tempfile, os, json, hashlib, math.ceil）/ chardet（既存・不変）。

**設計入力（source of truth 従属）:** `docs/superpowers/specs/2026-05-17-grep-analyzer-phase3-design.md`（v4・3軸レビュー収束済）。マスター spec `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`。

**不変条件（最重要）:** Inv-1＝既定オプション（`--memory-limit` 無 / `--resume` 無 / 既定 encoding）で既存 golden 14・既存 167 が **byte 完全不変**。manifest は追加生成物で TSV/diagnostics バイトに無影響。

**ファイル構成:**

| ファイル | 役割 | 区分 |
|---|---|---|
| `src/grep_analyzer/output_writer.py` | `_canonical_data_blob` / part 分割 / 原子書込 / manifest / 孤児クリーン | Create |
| `src/grep_analyzer/resume.py` | `is_complete`（完了判定5条件） | Create |
| `tests/perf/corpus_gen.py` | 決定的合成ソース木生成 | Create |
| `tests/perf/test_perf.py` | `@pytest.mark.perf` 非ゲート計測 | Create |
| `tests/perf/__init__.py` / `tests/perf/conftest.py` | perf パッケージ化（不要なら省略） | Create |
| `scripts/gen_requirements_lock.py` | wheelhouse から lock 生成 | Create |
| `requirements.lock` | 版＋ハッシュ固定（生成物） | Create |
| `src/grep_analyzer/fixedpoint.py` | `EngineOptions` 末尾既定追加・`_file_meta` に fallback 引数・3 呼出元伝播 | Modify |
| `src/grep_analyzer/cli.py` | 新 CLI フラグ5本 | Modify |
| `src/grep_analyzer/pipeline.py` | resume スキップ＋`output_writer.finalize`＋decode 鎖注入＋render 引数 | Modify |
| `src/grep_analyzer/diagnostics.py` | `render(detail_limit, exempt)` 縮約 | Modify |
| `tests/conftest.py` | `pytest_collection_modifyitems` に perf 除外分岐 | Modify |
| `docs/superpowers/plans/phase0-gate-result.md` | Phase 3 完了記録追記 | Modify |

---

## Task 1: EngineOptions 末尾既定追加 ＋ CLI フラグ5本（後方互換の土台）

新オプションは `EngineOptions`（実体 `fixedpoint.py:33`）末尾に既定付きで追加（既存呼び出し・既存 167 を壊さない）。CLI に5フラグ追加。**この時点では挙動を変えない**（配線は後続 Task）。

**Files:**
- Modify: `src/grep_analyzer/fixedpoint.py:32-52`（`EngineOptions`）
- Modify: `src/grep_analyzer/cli.py:22-54`
- Test: `tests/unit/test_cli_phase3.py`（Create）, `tests/integration/test_cli.py`（既存・回帰）

- [ ] **Step 1: 失敗するテストを書く**

Create `tests/unit/test_cli_phase3.py`:

```python
"""Phase 3 CLI フラグの EngineOptions 反映（spec §10.4 / WS1-4-6）。"""

from pathlib import Path

from grep_analyzer.cli import _build_opts


def test_phase3フラグ既定値():
    o = _build_opts([
        "--input", "i", "--output", "o", "--source-root", "s"])
    assert o.resume is False
    assert o.output_encoding == "utf-8-sig"
    assert list(o.encoding_fallback) == ["cp932", "euc-jp", "latin-1"]
    assert o.max_rows_per_part == 1_048_575
    assert o.diagnostics_detail_limit == 1000


def test_phase3フラグ明示指定():
    o = _build_opts([
        "--input", "i", "--output", "o", "--source-root", "s",
        "--resume", "--output-encoding", "cp932",
        "--encoding-fallback", "euc-jp,latin-1",
        "--max-rows-per-part", "5", "--diagnostics-detail-limit", "0"])
    assert o.resume is True
    assert o.output_encoding == "cp932"
    assert list(o.encoding_fallback) == ["euc-jp", "latin-1"]
    assert o.max_rows_per_part == 5
    assert o.diagnostics_detail_limit == 0
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_cli_phase3.py -q`
Expected: FAIL（`ImportError: cannot import name '_build_opts'` / `EngineOptions` に新属性なし）

- [ ] **Step 3: 最小実装 — EngineOptions 末尾追加**

`src/grep_analyzer/fixedpoint.py` の `EngineOptions` 末尾（`force_chunks: int = 0` の直後）に追加:

```python
    resume: bool = False
    output_encoding: str = "utf-8-sig"
    encoding_fallback: tuple[str, ...] = ("cp932", "euc-jp", "latin-1")
    max_rows_per_part: int = 1_048_575
    diagnostics_detail_limit: int = 1000
```

注: `frozen=True` dataclass ゆえ mutable 既定不可。`encoding_fallback` は `tuple` 既定にし、テスト/利用側は `list(opts.encoding_fallback)` で鎖化する。

- [ ] **Step 4: 最小実装 — CLI フラグ＋`_build_opts` 抽出**

`src/grep_analyzer/cli.py` の `main` から opts 構築を `_build_opts(argv)` 関数へ抽出し、5フラグを追加。`argparse` 追加（`p.add_argument` 群の末尾、`--progress` の後）:

```python
    p.add_argument("--resume", action="store_true")
    p.add_argument("--output-encoding", default="utf-8-sig", dest="output_encoding")
    p.add_argument("--encoding-fallback", default="cp932,euc-jp,latin-1",
                   dest="encoding_fallback")
    p.add_argument("--max-rows-per-part", type=int, default=1_048_575,
                   dest="max_rows_per_part")
    p.add_argument("--diagnostics-detail-limit", type=int, default=1000,
                   dest="diagnostics_detail_limit")
```

`EngineOptions(...)` 構築に追加（末尾）:

```python
        resume=args.resume,
        output_encoding=args.output_encoding,
        encoding_fallback=tuple(
            s for s in args.encoding_fallback.split(",") if s),
        max_rows_per_part=args.max_rows_per_part,
        diagnostics_detail_limit=args.diagnostics_detail_limit,
```

`_build_opts(argv)` は `p`/`args`/`opts` を構築し `opts` を返す。`main(argv)` は `opts = _build_opts(argv)` → `return run(...)`。Step1 のテストは既に `list(o.encoding_fallback) == [...]` 形（tuple 既定と整合）＝**テスト書換不要・RED は `_build_opts` の ImportError で一意**。

- [ ] **Step 5: テストが通ることを確認＋全回帰**

Run: `python -m pytest tests/unit/test_cli_phase3.py tests/integration/test_cli.py -q`
Expected: PASS
Run: `python -m pytest -q`
Expected: **167 passed**（既存不変＝挙動未変更）

- [ ] **Step 6: コミット**

```bash
git add src/grep_analyzer/fixedpoint.py src/grep_analyzer/cli.py tests/unit/test_cli_phase3.py
git commit -m "feat(phase3): EngineOptions 末尾既定追加＋CLIフラグ5本（挙動不変・後方互換）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `output_writer._canonical_data_blob`（正規化の唯一関数）

書込側・完了判定・Inv-5・テストが共有する正規形を 1 関数に閉じる（spec v4 §3 手順1）。`split("\n")` 固定（`splitlines()` 不使用）。

**Files:**
- Create: `src/grep_analyzer/output_writer.py`
- Test: `tests/unit/test_output_writer.py`（Create）

- [ ] **Step 1: 失敗するテストを書く**

Create `tests/unit/test_output_writer.py`:

```python
"""output_writer の正規化関数（spec v4 §3 手順1・Inv-5）。"""

from grep_analyzer.model import Hit
from grep_analyzer.output_writer import (
    _blob_from_data_rows, _canonical_data_blob, _data_line,
    _rows_from_part_text)


def _hit(file, lineno, snippet):
    return Hit(keyword="K", language="java", file=file, lineno=lineno,
               ref_kind="direct", category="c", category_sub="",
               usage_summary="u", via_symbol="", chain="ch",
               snippet=snippet, encoding="utf-8", confidence="low")


def test_canonical_blob_は_split改行で安定_特殊行区切りを水増ししない():
    # U+2028 は _sanitize 非対象だが splitlines は分割する → split("\n") 固定で水増し無
    # snippet に U+2028（_sanitize 非対象）＋タブ（_sanitize 発火）を含める。
    h = _hit("a.java", 1, "x y\tz")
    blob = _canonical_data_blob([h])
    assert blob.count(b"\n") == 0          # 1 データ行（U+2028 で割れない）
    assert blob == _data_line(h).encode("utf-8")          # sanitize 適用形と一致
    assert "\t" not in _data_line(h).split("\t", 12)[-1]  # snippet タブ空白化


def test_canonical_blob_末尾改行を含めない_空はゼロ長():
    assert _canonical_data_blob([]) == b""
    one = _canonical_data_blob([_hit("a", 1, "s")])
    assert not one.endswith(b"\n")


def test_書込側と完了判定側が同一関数_blob_from_data_rows_を共有():
    rows = [_hit("a", 1, "p"), _hit("b", 2, "q\tr")]
    blob = _canonical_data_blob(rows)
    from grep_analyzer.model import TSV_COLUMNS
    # 先頭BOM＋ヘッダ＋sanitize後データ＋末尾改行（単一 part 相当）
    body = "\ufeff" + "\t".join(TSV_COLUMNS) + "\n" + "\n".join(
        _data_line(r) for r in rows) + "\n"
    data_rows = _rows_from_part_text(body)         # BOM/ヘッダ除去込み
    assert _blob_from_data_rows(data_rows) == blob  # 書込側と同一関数で一致
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_output_writer.py -q`
Expected: FAIL（`ModuleNotFoundError: grep_analyzer.output_writer`）

- [ ] **Step 3: 最小実装**

Create `src/grep_analyzer/output_writer.py`:

```python
"""出力確定モジュール（spec v4 §2/§3）。

安定ソート→正規化→part分割→各part原子書込→manifest原子確定→孤児クリーン。
正規形は _canonical_data_blob に一元化（書込側=完了判定=Inv-5=テストが共有）。
"""

from grep_analyzer.model import TSV_COLUMNS, Hit, sort_key
from grep_analyzer.tsv import _sanitize


def _data_line(h: Hit) -> str:
    """1 データ行＝tsv.py:22 と同一バイト列（サニタイズ後タブ結合）。"""
    return "\t".join(_sanitize(c) for c in h.to_row())


def _blob_from_data_rows(data_rows: list[str]) -> bytes:
    """データ行列→正規バイト列（唯一の正規化終端）。書込側・完了判定側が共有。

    末尾改行無・LF 連結・"utf-8"（BOM 無 codec）。spec v4 §3 手順1。
    """
    return "\n".join(data_rows).encode("utf-8")


def _canonical_data_blob(ordered: list[Hit]) -> bytes:
    """ソート済 Hit→正規バイト列。書込側経路（_blob_from_data_rows を共有）。"""
    return _blob_from_data_rows([_data_line(h) for h in ordered])


def _rows_from_part_text(text: str) -> list[str]:
    """part 1 本のデコード済テキストからデータ行列を取り出す。

    書込時 `"\\n".join(lines)+"\\n"` の厳密逆＝先頭 BOM 除去 → rstrip("\\n")
    → split("\\n") → 先頭ヘッダ 1 行除去。splitlines() は使わない
    （_sanitize 非対象の U+2028/U+0085 等で水増しするため＝spec v4 §3 手順1）。
    decode 済 utf-8-sig は BOM 自動除去だが、防御的に先頭 U+FEFF も剥がす。
    """
    if text and text[0] == "\ufeff":   # 防御的 BOM 除去（明示）
        text = text[1:]
    lines = text.rstrip("\n").split("\n")
    return lines[1:]  # 先頭はヘッダ
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_output_writer.py -q`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/output_writer.py tests/unit/test_output_writer.py
git commit -m "feat(phase3): _canonical_data_blob 正規化の唯一関数（split改行固定・Inv-5基盤）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `output_writer.finalize` — part 分割＋manifest 原子確定＋孤児クリーン（WS1/WS2）

**Files:**
- Modify: `src/grep_analyzer/output_writer.py`
- Test: `tests/unit/test_output_writer.py`（追記）

- [ ] **Step 1: 失敗するテストを書く（part 境界・命名・manifest・BOM・孤児）**

`tests/unit/test_output_writer.py` に追記:

```python
import json
from grep_analyzer.fixedpoint import EngineOptions
from grep_analyzer.output_writer import finalize


def _opts(**kw):
    base = dict(max_depth=10, min_specificity=2, stoplist_path=None,
                lang_map={}, include=[], exclude=[], jobs=1,
                follow_symlinks=False, max_file_bytes=5_000_000,
                max_symbols=100_000, max_paths=1000)
    base.update(kw)
    return EngineOptions(**base)


def _mk(n):
    return [_hit(f"f{i:05d}.java", i, f"s{i}") for i in range(n)]


def test_n0は単一ファイル_ヘッダのみ(tmp_path):
    finalize(tmp_path, "K", [], _opts())
    assert (tmp_path / "K.tsv").exists()
    assert not list(tmp_path.glob("K.part*"))
    m = json.loads((tmp_path / "K.manifest.json").read_text("utf-8"))
    assert m["total_rows"] == 0
    assert m["parts"] == [{"name": "K.tsv", "rows": 0}]


def test_n等しいLは単一_Lプラス1で2part_ゼロ詰め(tmp_path):
    finalize(tmp_path, "A", _mk(3), _opts(max_rows_per_part=3))
    assert (tmp_path / "A.tsv").exists()              # n==L → 単一
    finalize(tmp_path, "B", _mk(4), _opts(max_rows_per_part=3))
    names = sorted(p.name for p in tmp_path.glob("B.part*"))
    assert names == ["B.part01.tsv", "B.part02.tsv"]  # nparts=2 width=2
    assert not (tmp_path / "B.tsv").exists()


def test_part9はwidth2_part09(tmp_path):
    finalize(tmp_path, "N", _mk(9), _opts(max_rows_per_part=1))
    names = sorted(p.name for p in tmp_path.glob("N.part*"))
    assert names[0] == "N.part01.tsv" and names[-1] == "N.part09.tsv"
    assert "N.part9.tsv" not in names and len(names) == 9   # width=max(2,..)


def test_part100はwidth3_part001(tmp_path):
    finalize(tmp_path, "C", _mk(100), _opts(max_rows_per_part=1))
    names = sorted(p.name for p in tmp_path.glob("C.part*"))
    assert names[0] == "C.part001.tsv" and names[-1] == "C.part100.tsv"
    assert len(names) == 100


def test_連結データ_単一同値_Inv5(tmp_path):
    rows = _mk(7)
    finalize(tmp_path, "S", rows, _opts(max_rows_per_part=1000))   # 単一
    finalize(tmp_path, "M", rows, _opts(max_rows_per_part=3))      # 3 part
    single = _rows_from_part_text((tmp_path / "S.tsv").read_text("utf-8-sig"))
    multi = []
    for p in sorted(tmp_path.glob("M.part*")):
        multi += _rows_from_part_text(p.read_text("utf-8-sig"))
    assert single == multi
    assert "\n".join(multi).encode("utf-8") == _canonical_data_blob(
        sorted(rows, key=__import__("grep_analyzer.model",
               fromlist=["sort_key"]).sort_key))


def test_BOMはutf8sigのみ(tmp_path):
    finalize(tmp_path, "U", _mk(1), _opts(output_encoding="utf-8-sig"))
    assert (tmp_path / "U.tsv").read_bytes().startswith(b"\xef\xbb\xbf")
    finalize(tmp_path, "P", _mk(1), _opts(output_encoding="utf-8"))
    assert not (tmp_path / "P.tsv").read_bytes().startswith(b"\xef\xbb\xbf")


def test_孤児partクリーンアップ(tmp_path):
    finalize(tmp_path, "O", _mk(100), _opts(max_rows_per_part=1))  # 100 part(3桁)
    finalize(tmp_path, "O", _mk(2), _opts(max_rows_per_part=1))    # 2 part(2桁)
    remaining = sorted(p.name for p in tmp_path.glob("O.*"))
    assert remaining == ["O.manifest.json", "O.part01.tsv", "O.part02.tsv"]
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_output_writer.py -q`
Expected: FAIL（`finalize` 未定義）

- [ ] **Step 3: 最小実装 — `finalize` ＋原子プリミティブ再利用**

`src/grep_analyzer/output_writer.py` に追記:

```python
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

from grep_analyzer import __version__


def _atomic_write(path: Path, data: bytes) -> None:
    """tsv.py:26-36 と同一の原子プリミティブ（mkstemp→fsync→os.replace）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                               prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _fsync_dir(d: Path) -> None:
    fd = os.open(str(d), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _part_bytes(header: str, data_rows: list[str], encoding: str) -> bytes:
    return ("\n".join([header] + data_rows) + "\n").encode(
        encoding, errors="replace")


def _write_manifest(out_dir: Path, keyword: str, manifest: dict) -> None:
    """manifest を原子確定（②フェーズ・テストの monkeypatch フック点）。"""
    blob = json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":")).encode("utf-8")
    _atomic_write(out_dir / f"{keyword}.manifest.json", blob)


def finalize(out_dir: Path, keyword: str, rows: list[Hit], opts) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=sort_key)
    n = len(ordered)
    L = opts.max_rows_per_part
    nparts = 1 if n <= L else math.ceil(n / L)
    width = max(2, len(str(nparts)))
    header = "\t".join(TSV_COLUMNS)
    enc = opts.output_encoding
    data_sha = hashlib.sha256(_canonical_data_blob(ordered)).hexdigest()

    parts_meta = []
    if nparts == 1:
        name = f"{keyword}.tsv"
        rows_lines = [_data_line(h) for h in ordered]
        _atomic_write(out_dir / name, _part_bytes(header, rows_lines, enc))
        parts_meta.append({"name": name, "rows": n})
    else:
        for i in range(nparts):
            chunk = ordered[i * L:(i + 1) * L]
            name = f"{keyword}.part{i + 1:0{width}d}.tsv"
            _atomic_write(out_dir / name,
                          _part_bytes(header, [_data_line(h) for h in chunk], enc))
            parts_meta.append({"name": name, "rows": len(chunk)})

    manifest = {
        "schema_version": 1, "keyword": keyword, "encoding": enc,
        "total_rows": n, "data_sha256": data_sha,
        "tool_version": __version__,
        "items_per_mb": __import__(
            "grep_analyzer.budget", fromlist=["_ITEMS_PER_MB"])._ITEMS_PER_MB,
        "parts": parts_meta, "tool": "grep_analyzer", "spec_phase": "3",
    }
    _write_manifest(out_dir, keyword, manifest)   # ②フェーズ
    _fsync_dir(out_dir)

    # 手順5: manifest 確定後に孤児削除（有効出力を新出力出現前に破壊しない）
    keep = {p["name"] for p in parts_meta} | {f"{keyword}.manifest.json"}
    for p in list(out_dir.glob(f"{keyword}.tsv")) + \
            list(out_dir.glob(f"{keyword}.part*.tsv")):
        if p.name not in keep:
            p.unlink()
```

注: `nparts > 1` 時に `_canonical_data_blob` と part 連結が一致することは Step 1 の `test_連結データ_単一同値_Inv5` が機械保証する。

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_output_writer.py -q`
Expected: PASS（全 7 テスト）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/output_writer.py tests/unit/test_output_writer.py
git commit -m "feat(phase3): output_writer.finalize part分割＋manifest原子確定＋孤児クリーン（WS1/WS2・Inv-5）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `resume.is_complete` — 完了判定5条件（WS1）

**Files:**
- Create: `src/grep_analyzer/resume.py`
- Test: `tests/unit/test_resume.py`（Create）

- [ ] **Step 1: 失敗するテストを書く**

Create `tests/unit/test_resume.py`:

```python
"""resume 完了判定5条件（spec v4 §4 WS1）。"""

import json

from grep_analyzer.output_writer import finalize
from grep_analyzer import resume
from tests.unit.test_output_writer import _hit, _mk, _opts


def test_正常完了は完了判定真(tmp_path):
    finalize(tmp_path, "K", _mk(5), _opts(max_rows_per_part=2))
    assert resume.is_complete(tmp_path, "K", _opts()) is True


def test_manifest不在は未完了(tmp_path):
    finalize(tmp_path, "K", _mk(2), _opts())
    (tmp_path / "K.manifest.json").unlink()
    assert resume.is_complete(tmp_path, "K", _opts()) is False


def test_part欠落は未完了(tmp_path):
    finalize(tmp_path, "K", _mk(4), _opts(max_rows_per_part=1))
    next(tmp_path.glob("K.part01.tsv")).unlink()
    assert resume.is_complete(tmp_path, "K", _opts()) is False


def test_行数保存_1文字改竄でsha不一致は未完了(tmp_path):
    finalize(tmp_path, "K", _mk(3), _opts())
    p = tmp_path / "K.tsv"
    b = p.read_bytes().replace(b"s0", b"sX", 1)   # 行数不変・内容変化
    p.write_bytes(b)
    assert resume.is_complete(tmp_path, "K", _opts()) is False


def test_items_per_mb不一致は未完了(tmp_path):
    finalize(tmp_path, "K", _mk(2), _opts())
    m = json.loads((tmp_path / "K.manifest.json").read_text("utf-8"))
    m["items_per_mb"] = m["items_per_mb"] + 1
    (tmp_path / "K.manifest.json").write_text(
        json.dumps(m, sort_keys=True, separators=(",", ":")), "utf-8")
    assert resume.is_complete(tmp_path, "K", _opts()) is False


def test_破損manifestは未完了(tmp_path):
    finalize(tmp_path, "K", _mk(1), _opts())
    (tmp_path / "K.manifest.json").write_text("{not json", "utf-8")
    assert resume.is_complete(tmp_path, "K", _opts()) is False


def test_utf8sig_複数part_行数保存改竄で未完了_BOM再構成経路(tmp_path):
    # utf-8-sig × 2part の再構成（各 part BOM/ヘッダ除去）が data_sha256 と
    # 同一関数で照合されること＝書込側/完了判定側の正規形一致を踏む。
    finalize(tmp_path, "K", _mk(4), _opts(max_rows_per_part=2,
                                          output_encoding="utf-8-sig"))
    assert resume.is_complete(tmp_path, "K", _opts()) is True
    p = tmp_path / "K.part02.tsv"
    p.write_bytes(p.read_bytes().replace(b"s3", b"sZ", 1))  # 行数不変
    assert resume.is_complete(tmp_path, "K", _opts()) is False
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_resume.py -q`
Expected: FAIL（`ModuleNotFoundError: grep_analyzer.resume`）

- [ ] **Step 3: 最小実装**

Create `src/grep_analyzer/resume.py`:

```python
"""kw 単位 resume の完了判定（spec v4 §4 WS1・完了判定1〜5）。"""

import hashlib
import json
from pathlib import Path

from grep_analyzer import __version__
from grep_analyzer.output_writer import _blob_from_data_rows, _rows_from_part_text


def is_complete(out_dir: Path, keyword: str, opts) -> bool:
    out_dir = Path(out_dir)
    mpath = out_dir / f"{keyword}.manifest.json"
    if not mpath.is_file():                                   # 条件1
        return False
    try:
        m = json.loads(mpath.read_text("utf-8"))
    except (ValueError, OSError):
        return False
    enc = m.get("encoding", "utf-8-sig")
    data_rows: list[str] = []
    for part in m.get("parts", []):
        f = out_dir / part["name"]
        if not f.is_file():                                   # 条件2
            return False
        rows = _rows_from_part_text(f.read_text(enc))
        if len(rows) != part.get("rows"):                     # 条件3
            return False
        data_rows += rows
    sha = hashlib.sha256(_blob_from_data_rows(data_rows)).hexdigest()
    if sha != m.get("data_sha256"):                           # 条件4（書込側と同一関数）
        return False
    from grep_analyzer.budget import _ITEMS_PER_MB
    if m.get("tool_version") != __version__:                  # 条件5
        return False
    if m.get("items_per_mb") != _ITEMS_PER_MB:                # 条件5
        return False
    return True
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_resume.py -q`
Expected: PASS（全 6 テスト）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/resume.py tests/unit/test_resume.py
git commit -m "feat(phase3): resume.is_complete 完了判定5条件（WS1・data_sha256/版/定数照合）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: クラッシュ注入テスト — manifest 確定直前で落ちる（WS1 耐クラッシュ）

`finalize` は Task 3 で「① 全 part 原子確定 → ② `_write_manifest` → 親 fsync」の 2 フェーズ構造。②直前を `monkeypatch` で例外注入し、part は残るが manifest 不在 → `is_complete False` → 再処理で無故障時と同値（Inv-7）。OS rename 永続性は検証範囲外（spec v4 §7 スコープ線引き）。

**Files:**
- Test: `tests/unit/test_resume.py`（追記）

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_resume.py` に追記:

```python
import hashlib
import pytest
from grep_analyzer import output_writer
from grep_analyzer import resume


def test_manifest確定直前クラッシュ_未完了かつ再処理で同値(tmp_path, monkeypatch):
    rows = _mk(5)
    # まず無故障で生成し基準 sha を取得
    ref = tmp_path / "ref"
    output_writer.finalize(ref, "K", rows, _opts(max_rows_per_part=2))
    ref_sha = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(ref.glob("K.part*.tsv"))}

    out = tmp_path / "out"
    monkeypatch.setattr(output_writer, "_write_manifest",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("crash")))
    with pytest.raises(RuntimeError):
        output_writer.finalize(out, "K", rows, _opts(max_rows_per_part=2))
    assert list(out.glob("K.part*.tsv"))               # part は残る
    assert not (out / "K.manifest.json").exists()      # manifest 不在
    assert resume.is_complete(out, "K", _opts()) is False

    monkeypatch.undo()
    output_writer.finalize(out, "K", rows, _opts(max_rows_per_part=2))
    assert resume.is_complete(out, "K", _opts()) is True
    out_sha = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(out.glob("K.part*.tsv"))}
    assert out_sha == ref_sha                          # Inv-7 再生成同値
```

- [ ] **Step 2: テストが失敗 or 通ることを確認**

Run: `python -m pytest tests/unit/test_resume.py::test_manifest確定直前クラッシュ_未完了かつ再処理で同値 -q`
Expected: PASS（Task 3 の `_write_manifest` フック点が既に存在＝設計通りなら GREEN。FAIL の場合は `finalize` が `_write_manifest` をモジュール関数として呼ぶよう Task 3 実装を修正）

- [ ] **Step 3: 必要なら最小修正**

`finalize` 内の manifest 確定が `_write_manifest(out_dir, keyword, manifest)` という**モジュール関数呼び出し**であることを確認（monkeypatch 可能な束縛）。直書きしていたらこの関数経由に切り出す。

- [ ] **Step 4: 全 resume テスト緑**

Run: `python -m pytest tests/unit/test_resume.py -q`
Expected: PASS（全 7 テスト）

- [ ] **Step 5: コミット**

```bash
git add tests/unit/test_resume.py src/grep_analyzer/output_writer.py
git commit -m "test(phase3): manifest確定直前クラッシュ注入＝未完了→再処理同値（WS1耐クラッシュ・Inv-7）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: diagnostics §10.3 縮約 ＋ §8.4 全件免除（WS3）

`render(detail_limit=0, exempt=...)` は既存 `render()` と完全同一（既存 `tests/unit/test_diagnostics.py` がアンカー）。`detail_limit>0` のみ縮約分岐。

**Files:**
- Modify: `src/grep_analyzer/diagnostics.py:18-27`
- Test: `tests/unit/test_diagnostics_phase3.py`（Create）, `tests/unit/test_diagnostics.py`（既存・回帰アンカー）

- [ ] **Step 1: 失敗するテストを書く**

Create `tests/unit/test_diagnostics_phase3.py`:

```python
"""§10.3 縮約・§8.4 全件免除（spec v4 §4 WS3・Inv-6）。"""

from grep_analyzer.diagnostics import (
    Diagnostics, SECTION_8_4_CATEGORIES, _is_exempt)


def test_detail_limit0は現行と完全同一():
    d = Diagnostics()
    for i in range(5):
        d.add("walk_skipped_large", f"f{i}")
    assert d.render(detail_limit=0, exempt=SECTION_8_4_CATEGORIES) == d.render()


def test_非84カテゴリは縮約_集約行():
    d = Diagnostics()
    for i in range(5):
        d.add("walk_skipped_large", f"f{i}")
    out = d.render(detail_limit=2, exempt=SECTION_8_4_CATEGORIES)
    assert "walk_skipped_large\tf0" in out and "walk_skipped_large\tf1" in out
    assert "walk_skipped_large\tf2" not in out
    assert "walk_skipped_large\t(... 3 more, 5 total)" in out
    assert "walk_skipped_large\t5" in out                # summary は真総数


def test_84カテゴリは縮約しない_全件():
    d = Diagnostics()
    for i in range(5):
        d.add("symbol_rejected", f"s{i}")
        d.add("prov_max_depth", f"p{i}")
    out = d.render(detail_limit=2, exempt=SECTION_8_4_CATEGORIES)
    for i in range(5):
        assert f"symbol_rejected\ts{i}" in out
        assert f"prov_max_depth\tp{i}" in out
    assert "more, 5 total" not in out


def test_is_exempt_prov_プレフィックスと完全一致集合():
    assert _is_exempt("prov_anything")            # prov_ プレフィックス
    assert _is_exempt("symbol_rejected")          # 完全一致
    assert _is_exempt("getter_setter_no_expand")  # 完全一致
    assert not _is_exempt("walk_skipped_large")   # 非 §8.4
```

注: `_is_exempt` / `SECTION_8_4_CATEGORIES` は Step 3 で新規定義。Step 1 のテストは**最終形**（書換不要）。RED は `ImportError: cannot import name '_is_exempt'` で一意。

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_diagnostics_phase3.py -q`
Expected: FAIL（`ImportError: cannot import name '_is_exempt'`／`SECTION_8_4_CATEGORIES`）

- [ ] **Step 3: 最小実装**

`src/grep_analyzer/diagnostics.py` を書き換え（`render` を引数付きに・既存 `render()` 同値を保持）:

```python
SECTION_8_4_CATEGORIES = frozenset({"symbol_rejected", "getter_setter_no_expand"})


def _is_exempt(cat: str, exempt=SECTION_8_4_CATEGORIES) -> bool:
    """§8.4 全件性カテゴリ（縮約免除）。prov_ プレフィックス一致を含む。

    縮約免除判定の**唯一の実装**（render はこれに委譲＝prov_ ロジック非重複）。
    """
    return cat in exempt or cat.startswith("prov_")
```

`Diagnostics.render` を置換:

```python
    def render(self, detail_limit: int = 0, exempt=None) -> str:
        """spec §10.3 スキーマ。detail_limit=0 は無制限＝現行と完全同一。"""
        is_exempt = (lambda c: _is_exempt(c, exempt)) \
            if exempt is not None else (lambda c: False)  # prov_ ロジック単一源
        out = ["# summary"]
        for cat in sorted(self._counts):
            out.append(f"{cat}\t{self._counts[cat]}")   # 常に真総数
        out.append("# detail")
        for cat in sorted(self._detail):
            msgs = self._detail[cat]
            if detail_limit > 0 and not is_exempt(cat) and len(msgs) > detail_limit:
                for msg in msgs[:detail_limit]:
                    out.append(f"{cat}\t{msg}")
                extra = len(msgs) - detail_limit
                out.append(f"{cat}\t(... {extra} more, {len(msgs)} total)")
            else:
                for msg in msgs:
                    out.append(f"{cat}\t{msg}")
        return "\n".join(out) + "\n"
```

`render` は `_is_exempt` に委譲し `prov_` プレフィックス判定を単一源化（spec v4 §4 WS3「順序/ロジックの出所を一意化」）。Step 1 テストは最終形ゆえ書換不要。

- [ ] **Step 4: テストが通ることを確認＋既存アンカー回帰**

Run: `python -m pytest tests/unit/test_diagnostics_phase3.py tests/unit/test_diagnostics.py tests/integration/test_diagnostics_phase2.py -q`
Expected: PASS（既存 `render()` 引数なし呼び出しが従来通り＝アンカー不変）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/diagnostics.py tests/unit/test_diagnostics_phase3.py
git commit -m "feat(phase3): diagnostics §10.3縮約＋§8.4全件免除（WS3・detail_limit=0は現行同値・Inv-6）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: pipeline 配線 — resume スキップ＋`output_writer.finalize`＋render 引数（WS1/WS3 統合・Inv-1）

`write_tsv` 直呼びを `output_writer.finalize` に差し替え。**既定（`--resume` 無・既定 encoding）で既存 golden 14・既存 167 が byte 完全不変**であることが本タスクの合否。

**Files:**
- Modify: `src/grep_analyzer/pipeline.py:43-83`
- Test: `tests/integration/test_pipeline_phase3.py`（Create）, 既存 golden/167（回帰）

- [ ] **Step 1: 失敗するテストを書く（resume スキップ＋既定不変）**

Create `tests/integration/test_pipeline_phase3.py`:

```python
"""pipeline の resume スキップ＋既定 byte 不変（spec v4 §3・Inv-1/Inv-7）。"""

import hashlib
from grep_analyzer.cli import main


def _setup(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text("class A{ static final int K1=1; }\n", "utf-8")
    inp = tmp_path / "input"; inp.mkdir()
    (inp / "K1.grep").write_text("A.java:1:static final int K1=1;\n", "utf-8")
    return src, inp


def test_既定でmanifest生成されTSVは従来と同名(tmp_path):
    src, inp = _setup(tmp_path)
    out = tmp_path / "o"
    assert main(["--input", str(inp), "--output", str(out),
                 "--source-root", str(src)]) == 0
    assert (out / "K1.tsv").exists()
    assert (out / "K1.manifest.json").exists()


def test_resumeで完了kwをスキップ_バイト不変(tmp_path):
    src, inp = _setup(tmp_path)
    out = tmp_path / "o"
    a = ["--input", str(inp), "--output", str(out), "--source-root", str(src)]
    assert main(a) == 0
    sha1 = hashlib.sha256((out / "K1.tsv").read_bytes()).hexdigest()
    assert main(a + ["--resume"]) == 0
    assert hashlib.sha256((out / "K1.tsv").read_bytes()).hexdigest() == sha1
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/integration/test_pipeline_phase3.py -q`
Expected: FAIL（manifest 未生成）

- [ ] **Step 3: 最小実装 — pipeline 差し替え**

`src/grep_analyzer/pipeline.py` の kw ループと末尾を変更:

```python
    from grep_analyzer import output_writer, resume
    for grep_file in sorted(Path(input_dir).glob("*.grep")):
        keyword = grep_file.stem
        if opts.resume and resume.is_complete(output_dir, keyword, opts):
            diag.add("resume_skipped", keyword)
            continue
        text, _, _ = decode_bytes(grep_file.read_bytes(), DEFAULT_FALLBACK)
        hits: list[Hit] = []
        # ...（既存 direct 抽出ループは不変）...
        indirect = run_fixedpoint(hits, Path(source_root), opts, diag, files=files)
        output_writer.finalize(output_dir, keyword, hits + indirect, opts)

    (output_dir / "diagnostics.txt").write_text(
        diag.render(detail_limit=opts.diagnostics_detail_limit,
                    exempt=SECTION_8_4_CATEGORIES),
        encoding="utf-8")
    return 0
```

`from grep_analyzer.diagnostics import Diagnostics, SECTION_8_4_CATEGORIES` を import。`opts` が None の既定経路（`_default_opts()`）でも `resume`/`output_encoding`/`max_rows_per_part`/`diagnostics_detail_limit` が EngineOptions 既定で埋まる（Task 1 で末尾既定追加済）。spec v4 §3 データフロー通り `render(detail_limit=opts.diagnostics_detail_limit, exempt=SECTION_8_4_CATEGORIES)` を渡す（既定 1000）。**Inv-1 の前提＝golden 14・既存 167 の単一カテゴリ診断件数が 1000 未満**。この前提は仮定でなく Step 4 で実証し、かつ golden 14 byte 回帰が「縮約が万一発火したら即赤化」する安全網となる（spec v4 Inv-1 は『診断 ≤ 上限』を明示条件とする）。

- [ ] **Step 4: Inv-1 前提の実証＋回帰（最重要）**

前提実証（golden の最大単一カテゴリ件数 < 1000）:
Run: `python -c "import subprocess,glob,collections,re,sys; [None]"`（手順: 各 golden ケースを `grep_analyzer.cli.main` で実行し生成 `diagnostics.txt` の `# detail` 各カテゴリ行数の最大を集計、`< 1000` を確認）。簡便には:
Run: `python -m pytest tests/golden -q` → **golden 14 PASS（byte 完全不変＝縮約未発火の事実証跡）**
Run: `python -m pytest tests/integration/test_pipeline_phase3.py -q`
Expected: PASS
Run: `python -m pytest -q`
Expected: **既存 167 + 追加分 passed**（既存が 1 件も赤化しないこと＝Inv-1。golden が割れたら縮約発火＝前提不成立として原因調査）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/pipeline.py tests/integration/test_pipeline_phase3.py
git commit -m "feat(phase3): pipeline を output_writer.finalize＋resume スキップへ配線（WS1/WS3・Inv-1 byte不変維持）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: encoding 配線 WS4 — `_file_meta` fallback 引数＋3 decode 経路＋output_encoding

3 decode 経路（入力 `.grep` / direct ソース / indirect ＝`fixedpoint._file_meta`）に `opts.encoding_fallback` を注入。`output_writer` は `opts.output_encoding` で書込（Task 3 で既に対応済）。観測は行番号でなく挙動。

**Files:**
- Modify: `src/grep_analyzer/fixedpoint.py:59-64`（`_file_meta`）, `:75`/`:170`/`:313`（呼出元）
- Modify: `src/grep_analyzer/pipeline.py`（`.grep`・direct の `decode_bytes` 引数）
- Test: `tests/integration/test_encoding_wiring.py`（Create）

- [ ] **Step 1: 失敗するテストを書く（観測挙動・行番号非依存）**

Create `tests/integration/test_encoding_wiring.py`:

```python
"""encoding 配線（spec v4 §4 WS4・3 decode 経路）。

検出原理の前提: `encoding.decode_bytes` は ① utf-8 厳格 → ② chardet 検出
→ ③ fallback 鎖 → ④ 末尾+replace（encoding.py:19-38）。短いソースは
chardet が高確信で確定し ③ に到達しないため、`--encoding-fallback` の
効果を観測するには **chardet を None 固定**して ③ を決定的に踏ませる
（spec §10.4「② フォールバック候補鎖のみ置換／① chardet は常に最初」
の挙動自体は不変利用＝テスト都合で ② を中立化するだけ・本番挙動不変）。
jobs 既定 1 ＝ pipeline/_scan_file は in-process ゆえ monkeypatch 伝播。
"""

from grep_analyzer.cli import main


def _no_chardet(monkeypatch):
    # ② chardet を None 固定 → ③ fallback 鎖を決定的に経由させる。
    monkeypatch.setattr("grep_analyzer.encoding.chardet.detect",
                        lambda data: {"encoding": None})


def _run(tmp_path, src_bytes, fallback):
    src = tmp_path / "src"; src.mkdir(parents=True, exist_ok=True)
    (src / "A.java").write_bytes(b"class A{ String s=\"" + src_bytes + b"\"; }\n")
    inp = tmp_path / "input"; inp.mkdir(parents=True, exist_ok=True)
    (inp / "K.grep").write_text("A.java:1:String s\n", "utf-8")
    out = tmp_path / "o"
    main(["--input", str(inp), "--output", str(out), "--source-root", str(src),
          "--encoding-fallback", fallback])
    return (out / "K.tsv").read_text("utf-8-sig")


def test_fallback鎖差し替えが入力grepとdirectソースの出力を変える(
        tmp_path, monkeypatch):
    _no_chardet(monkeypatch)
    b = b"\x83\x65"                       # cp932「テ」/ latin-1 では別字
    a = _run(tmp_path / "a", b, "cp932,latin-1")   # cp932 厳格成功
    c = _run(tmp_path / "c", b, "latin-1")         # 末尾 latin-1+replace
    assert a != c   # 鎖が .grep/direct decode に届く（未配線なら両者
                    # DEFAULT(cp932..) で同一＝RED→配線で GREEN）


def test_indirect走査ソースのfallback鎖も届く(tmp_path, monkeypatch):
    _no_chardet(monkeypatch)
    # K は A.java で定義（非utf8バイト混入）、B.java から間接参照。
    # indirect hit の encoding は _file_meta（fixedpoint）走査側 decode 由来。
    def run1(root, fb):
        src = root / "src"; src.mkdir(parents=True, exist_ok=True)
        (src / "A.java").write_bytes(
            b"class A{ static final int K=1; String s=\"\x83\x65\"; }\n")
        (src / "B.java").write_bytes(b"class B{ int z=K; }\n")
        inp = root / "in"; inp.mkdir(parents=True, exist_ok=True)
        (inp / "K.grep").write_text("A.java:1:static final int K\n", "utf-8")
        out = root / "o"
        main(["--input", str(inp), "--output", str(out),
              "--source-root", str(src), "--encoding-fallback", fb])
        return (out / "K.tsv").read_text("utf-8-sig")
    assert run1(tmp_path / "p", "cp932,latin-1") != run1(tmp_path / "q", "latin-1")


def test_direct_indirectが同一鎖で一貫_かつ配線感応(tmp_path, monkeypatch):
    # 非DEFAULT結果になる鎖 "latin-1" を使う＝未配線(DEFAULT=cp932先頭)なら
    # encoding は cp932 となり expected{"latin-1 要確認"} と不一致＝RED、
    # 配線後は direct/indirect とも latin-1 で一貫＝GREEN（配線感応＋一貫性）。
    _no_chardet(monkeypatch)
    src = tmp_path / "src"; src.mkdir(parents=True, exist_ok=True)
    (src / "A.java").write_bytes(
        b"class A{ static final int K=1; String s=\"\x83\x65\"; }\n")
    (src / "B.java").write_bytes(b"class B{ int z=K; }\n")
    inp = tmp_path / "input"; inp.mkdir(parents=True, exist_ok=True)
    (inp / "K.grep").write_text("A.java:1:static final int K\n", "utf-8")
    out = tmp_path / "o"
    main(["--input", str(inp), "--output", str(out), "--source-root", str(src),
          "--encoding-fallback", "latin-1"])
    rows = [r for r in (out / "K.tsv").read_text("utf-8-sig").splitlines()[1:]
            if r]
    encs = {r.split("\t")[11] for r in rows}         # encoding 列
    # " 要確認" 接尾辞の有無に依存しない頑健形: 全行が latin-1 系で 1 種
    # （direct/indirect 一貫）かつ cp932 でない（＝未配線 DEFAULT と区別）。
    assert len(encs) == 1 and next(iter(encs)).startswith("latin-1")
    assert "cp932" not in encs                        # 未配線なら cp932＝RED


def _split_fixture(root):
    # test_fixedpoint.py:212 と同型の「実際に automaton 分割が発火する」構成。
    # F.java（被走査ファイル）に非utf8バイト \x83\x65 を仕込む。
    root.mkdir(parents=True, exist_ok=True)
    (root / "A.java").write_bytes(b"class A{ static final int ZED=1; }\n")
    (root / "T.java").write_bytes(b"class T{ static final int ABE=2; }\n")
    (root / "F.java").write_bytes(
        b"class F{ static final int G1=ZED; static final int G2=ABE;"
        b" int u=G1; int w=G2; String s=\"\x83\x65\"; }\n")
    return root


def _run_split(tmp_path, fallback):
    src = _split_fixture(tmp_path / "src")
    inp = tmp_path / "input"; inp.mkdir(parents=True, exist_ok=True)
    (inp / "ZED.grep").write_text("A.java:1:static final int ZED=1;\n", "utf-8")
    (inp / "ABE.grep").write_text("T.java:1:static final int ABE=2;\n", "utf-8")
    from grep_analyzer.cli import _build_opts
    from grep_analyzer.pipeline import run
    import dataclasses
    o = _build_opts(["--input", "i", "--output", "o", "--source-root", "s",
                     "--encoding-fallback", fallback])
    o = dataclasses.replace(o, force_chunks=3)   # 実際に automaton_split 発火
    out = tmp_path / "o"
    run(input_dir=inp, output_dir=out, source_root=src, opts=o)
    return (out / "ZED.tsv").read_text("utf-8-sig")


def test_automaton分割発火構成でfallback鎖が届く(tmp_path, monkeypatch):
    # chardet 中立化で ③ 強制。force_chunks=3 で automaton_split を実発火
    # させた構成（test_fixedpoint.py:212 同型）で F.java を走査し、鎖が
    # decode 経路へ届けば 2 鎖で ZED.tsv が変わる。
    # 【検出範囲の明示・実測知見】本テストは「全 decode 経路が DEFAULT 化
    # （Task1 のみ＝未配線）か否か」を RED→GREEN で駆動する wiring スモーク
    # であり、`:248` 配線済で `:264` のみ漏れた状態を単独分離検出はしない
    # （F.java の最終 encoding/snippet は実コード上 :313 の indirect 再構成
    # ＋_scan_file enc_of 由来で表面化し :264 単独では不変なため）。
    # `:264` 配線必須は Step 3 で別途規定し、`pytest -q` 全緑＋分割 fixture
    # が分割経路を実行する事実で担保する（本テストは網羅保証でなく駆動用）。
    _no_chardet(monkeypatch)
    a = _run_split(tmp_path / "a", "cp932,latin-1")
    b = _run_split(tmp_path / "b", "latin-1")
    assert a != b   # 鎖が decode 経路へ届く（未配線=全DEFAULTなら同一＝RED）
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/integration/test_encoding_wiring.py -q`
Expected: FAIL（chardet を None 固定し ③ 強制下でも `--encoding-fallback` が `decode_bytes` に届かず＝鎖を変えても全経路 DEFAULT 復号で出力不変＝`assert a != *` が RED。配線後に GREEN）

- [ ] **Step 3: 最小実装 — `_file_meta` 引数化＋呼出元伝播＋pipeline**

`fixedpoint.py` `_file_meta` に鎖引数追加:

```python
def _file_meta(rel, raw, lang_map, fallback_chain=None):
    chain = list(fallback_chain) if fallback_chain else DEFAULT_FALLBACK
    text, enc, replaced = decode_bytes(raw, chain)
    ...
```

3 decode 経路（`_file_meta` 呼出元 `fixedpoint.py:75` `_scan_file` 内、`:170` seed ループ、`:313` indirect 再構成）へ `opts.encoding_fallback` を伝播:

- `_scan_file` 経由（:75）: `args` タプルを `(rel, abspath, syms, lang_map)` → `(rel, abspath, syms, lang_map, fallback)` に拡張し `_scan_file` の unpack（`fixedpoint.py:73`）を更新。**args 構築は実コードで 2 箇所あり両方に追加必須**:
  - `fixedpoint.py:248`（`nchunks <= 1` 経路）の `args = [(rel, str(abspath), scan_syms, opts.lang_map) ...]`
  - `fixedpoint.py:264`（automaton 分割 `nchunks > 1` 経路）の `args = [(rel, str(abspath), chunk, opts.lang_map) ...]`
  両方に `, list(opts.encoding_fallback)` を末尾追加（片方漏れると automaton 分割発火時のみ鎖が `DEFAULT_FALLBACK` に化け direct/indirect 不一致＝spec §10.1 一貫性違反）。
- `:170` / `:313` は直接 `_file_meta(..., fallback_chain=list(opts.encoding_fallback))`。

`pipeline.py` の 2 箇所:

```python
    fb = list(opts.encoding_fallback)
    text, _, _ = decode_bytes(grep_file.read_bytes(), fb)            # .grep
    ...
    file_text, enc, replaced = decode_bytes(target.read_bytes(), fb)  # direct
```

- [ ] **Step 4: テスト＋Inv-1 回帰**

Run: `python -m pytest tests/integration/test_encoding_wiring.py -q`
Expected: PASS
Run: `python -m pytest tests/golden -q`
Expected: **golden 14 PASS（byte 完全不変）**（既定 `encoding_fallback` は `DEFAULT_FALLBACK` と要素同値ゆえ既定経路 decode 不変）
Run: `python -m pytest -q`
Expected: **既存 167 + 追加分 passed**（既定 fallback 同値＝Inv-1 byte 不変）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/fixedpoint.py src/grep_analyzer/pipeline.py tests/integration/test_encoding_wiring.py
git commit -m "feat(phase3): encoding-fallback を3 decode経路に配線（WS4・既定同値でInv-1不変）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: conftest perf 除外分岐 ＋ `test_perf_excluded_by_default`（WS6 インフラ）

`pyproject.toml:24-26` の marker は既登録。追加は `conftest.pytest_collection_modifyitems` の perf 分岐のみ。skip reason に `perf` を含める（実装契約）。

**Files:**
- Modify: `tests/conftest.py:16-23`
- Create: `tests/perf/__init__.py`, `tests/perf/test_perf.py`（最小スタブ）
- Test: `tests/unit/test_perf_excluded.py`（Create）

- [ ] **Step 1: 失敗するテストを書く**

Create `tests/unit/test_perf_excluded.py`:

```python
"""perf 非ゲート機構の自己検証（spec v4 §4 WS6・I-B）。"""

pytest_plugins = ["pytester"]


def test_perfは既定でskip_reasonにperfを含む(pytester):
    pytester.makeini("[pytest]\nmarkers =\n    perf: 非ゲート\n"
                     "    requires_ripgrep: rg")          # 内側 marker 登録
    pytester.makeconftest(open("tests/conftest.py").read())
    pytester.makepyfile(test_p="""
import pytest
@pytest.mark.perf
def test_heavy():
    assert True
""")
    r = pytester.runpytest("-rs")                          # 既定（-m 無指定）
    r.assert_outcomes(skipped=1, passed=0)                  # skip 注入（deselect 非）
    r.stdout.fnmatch_lines(["*perf*"])                      # reason に perf
```

注: 内側 conftest は外側を丸ごと写すが `test_p` は grep_analyzer を import せず、conftest の `sys.path` 行（pytester tmpdir 基準でズレる）も無害（Reviewer 実証済）。`makeini` で内側に perf/requires_ripgrep marker を登録し `PytestUnknownMarkWarning` を抑止。

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_perf_excluded.py -q`
Expected: FAIL（perf 分岐不在＝skip されず passed=1）

- [ ] **Step 3: 最小実装 — conftest perf 分岐**

`tests/conftest.py` の `pytest_collection_modifyitems` を拡張:

```python
def pytest_collection_modifyitems(config, items):
    import re
    import shutil
    rg = shutil.which("rg") is not None
    markexpr = config.getoption("markexpr") or ""        # -m の式（"-m" でなく markexpr）
    # "perf" がトークンとして式に現れるか（"not perf" 等の部分文字列誤判定回避）。
    perf_selected = bool(re.search(r"\bperf\b", markexpr))
    skip_rg = pytest.mark.skip(reason="ripgrep 不在のため skip（任意機能）")
    skip_perf = pytest.mark.skip(reason="perf は非ゲート（既定除外）")
    for item in items:
        if "requires_ripgrep" in item.keywords and not rg:
            item.add_marker(skip_rg)
        if "perf" in item.keywords and not perf_selected:
            item.add_marker(skip_perf)
```

注（現行挙動の保全）: 現 `conftest.py:18-19` は「rg 在れば即 `return`」。本置換は早期 return を廃し毎回両 marker を走査するが、rg 在環境では `not rg` が偽ゆえ `requires_ripgrep` に skip を付けない＝**現行 rg 4 passed と等価**。Step 4 の全回帰でこの等価性（rg 環境 167 不変）を確認する。`pytest_configure` の marker 登録（`conftest.py:11-13`）は触らない（`pyproject.toml:24-26` 二重登録は no-op）。

Create `tests/perf/__init__.py`（空）, `tests/perf/test_perf.py`:

```python
"""非ゲート perf 計測（spec §11・@pytest.mark.perf）。Task 11 で計測本体追加。"""

import pytest


@pytest.mark.perf
def test_perf_placeholder():
    assert True
```

- [ ] **Step 4: テスト＋全回帰（perf が既定で走らないこと）**

Run: `python -m pytest tests/unit/test_perf_excluded.py -q`
Expected: PASS
Run: `python -m pytest -q`
Expected: 既存 167 + 追加分 passed、**perf は skipped 表示（実行されない）**

- [ ] **Step 5: コミット**

```bash
git add tests/conftest.py tests/perf/__init__.py tests/perf/test_perf.py tests/unit/test_perf_excluded.py
git commit -m "feat(phase3): conftest に perf 除外分岐＋自己検証メタテスト（WS6・非ゲート機構）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: `corpus_gen` 決定的合成木 ＋ `requirements.lock`（WS6/WS5）

**Files:**
- Create: `tests/perf/corpus_gen.py`, `scripts/gen_requirements_lock.py`, `requirements.lock`
- Test: `tests/unit/test_corpus_gen.py`, `tests/unit/test_requirements_lock.py`（Create）

- [ ] **Step 1: 失敗するテストを書く**

Create `tests/unit/test_corpus_gen.py`:

```python
"""corpus_gen 決定性（同一シード同一木・spec v4 §4 WS6・既定ゲート非perf）。"""

import hashlib
from tests.perf.corpus_gen import generate


def _digest(root):
    items = sorted(p.relative_to(root).as_posix()
                   for p in root.rglob("*") if p.is_file())
    h = hashlib.sha256()
    for rel in items:
        h.update(rel.encode()); h.update((root / rel).read_bytes())
    return h.hexdigest()


def test_同一シードで同一木(tmp_path):
    a = tmp_path / "a"; b = tmp_path / "b"
    generate(a, seed=42, n_files=20)
    generate(b, seed=42, n_files=20)
    assert _digest(a) == _digest(b)
    c = tmp_path / "c"; generate(c, seed=43, n_files=20)
    assert _digest(c) != _digest(a)
```

Create `tests/unit/test_requirements_lock.py`:

```python
"""requirements.lock 整合（ゲート・高速・spec §4.1/WS5）。"""

import hashlib
import re
from pathlib import Path

LOCK = Path("requirements.lock")
WH = Path("wheelhouse")


# spec §4.1 の必須依存（pyproject の dependencies ではなく spec 名で固定。
# pyproject.toml の dependencies は pyahocorasick を欠くため §4.1 名で照合）。
SPEC_4_1_REQUIRED = {
    "tree-sitter", "tree-sitter-java", "tree-sitter-c",
    "pyahocorasick", "chardet"}


def _norm(pkg: str) -> str:
    return pkg.lower().replace("_", "-")


def test_lock各行のhashがwheelhouse実ファイルと一致():
    assert LOCK.is_file(), "requirements.lock 未生成（Step 3 で生成）"
    text = LOCK.read_text("utf-8")
    pairs = re.findall(r"(\S+)==(\S+) --hash=sha256:([0-9a-f]+)", text)
    assert pairs, "lock 形式不正"
    by_hash = {}
    for whl in WH.glob("*.whl"):
        by_hash[hashlib.sha256(whl.read_bytes()).hexdigest()] = whl.name
    for pkg, ver, sha in pairs:
        assert sha in by_hash, f"{pkg}=={ver} のhashがwheelhouseに無い"


def test_lockがspec_4_1必須依存を網羅():
    """spec §4.1/WS5: lock の pkg 集合 ⊇ §4.1 必須依存。"""
    text = LOCK.read_text("utf-8")
    locked = {_norm(p) for p, _, _ in
              re.findall(r"(\S+)==(\S+) --hash=sha256:([0-9a-f]+)", text)}
    missing = {r for r in SPEC_4_1_REQUIRED if _norm(r) not in locked}
    assert not missing, f"spec §4.1 必須依存が lock に欠落: {missing}"
```

注: `pyproject.toml` の `dependencies` は `pyahocorasick` を列挙しない（spec §4.1 は必須と規定・既知の差異）。本テストは pyproject ではなく **spec §4.1 の必須依存名集合**で照合する。`wheelhouse/` には pyahocorasick wheel が実在（Phase 2 G1 で集約済）ゆえ lock 生成（Step 3・全 whl 走査）に確実に含まれる。

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_corpus_gen.py tests/unit/test_requirements_lock.py -q`
Expected: FAIL（`corpus_gen` 未作成 / `requirements.lock` 未生成）

- [ ] **Step 3: 最小実装**

Create `tests/perf/corpus_gen.py`:

```python
"""決定的合成ソース木生成（同一シード同一木・spec v4 §4 WS6）。"""

import random
from pathlib import Path

_JAVA = "class C{0}{{ static final int S{0}={1}; int u{0}=S{2}; }}\n"
_C = "static int s{0}={1};\nint u{0}=s{2};\n"
_SH = "S{0}={1}\necho $S{2}\n"


def generate(root: Path, *, seed: int, n_files: int) -> None:
    root = Path(root)
    rnd = random.Random(seed)               # シード固定＝決定的
    for i in range(n_files):
        kind = i % 3
        d = root / f"pkg{i % 5}"
        d.mkdir(parents=True, exist_ok=True)
        ref = rnd.randint(0, max(0, i))
        if kind == 0:
            (d / f"C{i}.java").write_text(_JAVA.format(i, rnd.randint(1, 9), ref), "utf-8")
        elif kind == 1:
            (d / f"c{i}.c").write_text(_C.format(i, rnd.randint(1, 9), ref), "utf-8")
        else:
            (d / f"s{i}.sh").write_text(_SH.format(i, rnd.randint(1, 9), ref), "utf-8")
```

Create `scripts/gen_requirements_lock.py`:

```python
"""wheelhouse/*.whl から pkg==ver --hash=sha256 を生成（spec §4.1/WS5）。"""

import hashlib
import re
import sys
from pathlib import Path

WH = Path("wheelhouse")
out = []
for whl in sorted(WH.glob("*.whl")):
    m = re.match(r"([A-Za-z0-9_.]+)-([0-9][^-]*)-", whl.name)
    if not m:
        print(f"skip(命名不一致): {whl.name}", file=sys.stderr)
        continue
    pkg, ver = m.group(1).replace("_", "-"), m.group(2)
    sha = hashlib.sha256(whl.read_bytes()).hexdigest()
    out.append(f"{pkg}=={ver} --hash=sha256:{sha}")
Path("requirements.lock").write_text("\n".join(out) + "\n", "utf-8")
print(f"requirements.lock 生成: {len(out)} packages")
```

Run: `python scripts/gen_requirements_lock.py`

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_corpus_gen.py tests/unit/test_requirements_lock.py -q`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add tests/perf/corpus_gen.py scripts/gen_requirements_lock.py requirements.lock tests/unit/test_corpus_gen.py tests/unit/test_requirements_lock.py
git commit -m "feat(phase3): corpus_gen 決定的合成木＋requirements.lock 整合（WS6/WS5）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: perf 計測本体 ＋ `_ITEMS_PER_MB` 較正 ＋ Inv 能動ガード ＋ Phase 3 完了記録

`_ITEMS_PER_MB` を perf 証跡と同一コミットで一度だけ較正。既定経路が定数不感であることを能動ガードテストで機械保証。

**Files:**
- Modify: `tests/perf/test_perf.py`, `src/grep_analyzer/budget.py:9`
- Create: `tests/integration/test_inv1_items_per_mb.py`, `tests/unit/test_requirements_lock_offline.py`
- Modify: `docs/superpowers/plans/phase0-gate-result.md`

- [ ] **Step 1: 失敗するテストを書く（Inv-1 能動ガード＋offline 再現非ゲート）**

Create `tests/integration/test_inv1_items_per_mb.py`:

```python
"""既定経路が _ITEMS_PER_MB に不感＝Inv-1 機械保証（spec v4 §7・WS6）。"""

import hashlib
import pytest
from grep_analyzer.cli import main


def _run(tmp_path):
    src = tmp_path / "src"; src.mkdir(parents=True, exist_ok=True)
    (src / "A.java").write_text("class A{ static final int K=1; }\n", "utf-8")
    inp = tmp_path / "input"; inp.mkdir(parents=True, exist_ok=True)
    (inp / "K.grep").write_text("A.java:1:static final int K\n", "utf-8")
    out = tmp_path / "o"
    assert main(["--input", str(inp), "--output", str(out),
                 "--source-root", str(src)]) == 0
    return hashlib.sha256((out / "K.tsv").read_bytes()).hexdigest()


def test_既定出力は_items_per_mb値に不感(tmp_path, monkeypatch):
    # 真の能動ガード: 既定定数での出力 sha を基準に、定数を極値へ
    # monkeypatch しても **基準と一致** すること（v=default 比較）。
    ref = _run(tmp_path / "ref")                       # 既定 _ITEMS_PER_MB
    for v in (1, 10 ** 9):
        monkeypatch.setattr("grep_analyzer.budget._ITEMS_PER_MB", v)
        assert _run(tmp_path / f"v{v}") == ref          # 既定経路は定数不感
        monkeypatch.undo()
```

Create `tests/unit/test_requirements_lock_offline.py`:

```python
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
         "ahocorasick,chardet,pytest"], capture_output=True, text=True)
    assert imp.returncode == 0, imp.stderr
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/integration/test_inv1_items_per_mb.py -q`
Expected: PASS（既定経路は定数不感ゆえ実は最初から GREEN＝能動ガードとして機能。FAIL する場合は配線退行＝要調査）
Run: `python -m pytest tests/unit/test_requirements_lock_offline.py -q -m perf`
Expected: PASS（明示 `-m perf` で実行）

- [ ] **Step 3: perf 計測本体＋`_ITEMS_PER_MB` 較正**

`tests/perf/test_perf.py` を計測実体に置換:

```python
"""非ゲート perf ベースライン（spec §11・@pytest.mark.perf）。"""

import resource
import sys
import time
import pytest
from grep_analyzer.cli import main
from tests.perf.corpus_gen import generate


@pytest.mark.perf
@pytest.mark.parametrize("n", [200, 400, 800])
def test_scale(tmp_path, n):
    src = tmp_path / "src"; generate(src, seed=1, n_files=n)
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "S0.grep").write_text("pkg0/C0.java:1:S0\n", "utf-8")
    out = tmp_path / "o"
    t0 = time.perf_counter()
    main(["--input", str(inp), "--output", str(out), "--source-root", str(src)])
    dt = time.perf_counter() - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(f"PERF n={n} dt={dt:.3f}s rss_kb={rss}")


@pytest.mark.perf
def test_calibrate_items_per_mb(tmp_path, monkeypatch):
    """`_ITEMS_PER_MB` 較正の具体手順（実行可能・非ゲート）。

    重要: `estimate_items` は `fixedpoint.py` の全呼出が `if not
    budget.unlimited` 配下（L188/209/239）。既定 `--memory-limit` 無
    （budget.unlimited=True）では **一度も呼ばれない**。よって較正は
    **十分大きい有限 `--memory-limit`** を与え budget 経路を有効化しつつ
    degrade を発火させない（exceeded=False のまま実 item を計測）。
    spy 0 回なら計測不能として **明示的に FAIL** させる。
    """
    import tracemalloc
    from grep_analyzer import budget as _b

    seen = []
    real = _b.estimate_items

    def _spy(*, n_symbols, n_edges, n_intro):
        v = real(n_symbols=n_symbols, n_edges=n_edges, n_intro=n_intro)
        seen.append(v)
        return v

    # fixedpoint は `from grep_analyzer.budget import estimate_items`（関数
    # オブジェクト束縛）ゆえ fixedpoint 名前空間側を差し替える。
    monkeypatch.setattr("grep_analyzer.fixedpoint.estimate_items", _spy)

    src = tmp_path / "src"; generate(src, seed=7, n_files=600)
    inp = tmp_path / "in"; inp.mkdir(parents=True, exist_ok=True)
    (inp / "S0.grep").write_text("pkg0/C0.java:1:S0\n", "utf-8")
    out = tmp_path / "o"
    BIG_LIMIT_MB = 100_000          # budget 経路有効化・degrade 非発火に十分大
    tracemalloc.start()
    main(["--input", str(inp), "--output", str(out), "--source-root", str(src),
          "--memory-limit", str(BIG_LIMIT_MB)])
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert seen, ("estimate_items が呼ばれていない＝較正不能。"
                  "--memory-limit 指定で budget 経路を有効化すること")
    max_items = max(seen)
    bytes_per_item = peak / max_items
    items_per_mb = int(1_048_576 // max(1.0, bytes_per_item))
    print(f"CALIB peak_bytes={peak} max_items={max_items} "
          f"bytes_per_item={bytes_per_item:.1f} ITEMS_PER_MB={items_per_mb}")
    assert items_per_mb > 0
```

計測・較正手順（具体）:
1. `python -m pytest tests/perf/test_perf.py -q -m perf -s` を実行。`PERF n=...`（スケール）と `CALIB ... ITEMS_PER_MB=<X>` 行を収集（cp312/x86_64・G1 環境）。`test_calibrate_items_per_mb` は `--memory-limit 100000` 付きで走る（既定経路では `estimate_items` が `not budget.unlimited` 配下ゆえ不発火＝spy 0 回なら `assert seen` で FAIL し較正不能を明示。無意味値の混入を防ぐ安全弁）。
2. `CALIB` 行の `ITEMS_PER_MB=<X>` を採用値とし、`src/grep_analyzer/budget.py:9` の `_ITEMS_PER_MB = 4096` を `_ITEMS_PER_MB = <X>` に**1 回だけ**置換。
3. `PERF`/`CALIB` 全出力と採用根拠（測定環境・式 `floor(1_048_576 / bytes_per_item)`）を `docs/superpowers/plans/phase3-perf-report.md` に保存。
4. スケール特性: `PERF` の `n=200/400/800` の `dt`/`rss` から線形/準線形を確認し O 表記見積りを同レポートに記載。

- [ ] **Step 4: 較正後の全回帰（Inv-1 不変・能動ガード緑）**

Run: `python -m pytest -q`
Expected: 既存 167 + Phase 3 追加分 passed（**`_ITEMS_PER_MB` 変更後も既定経路不変＝`test_inv1_items_per_mb` PASS**、perf は skipped）
Run: `python -m pytest tests/golden -q`
Expected: golden 14 PASS（byte 不変）

- [ ] **Step 5: Phase 3 完了記録追記＋コミット**

`docs/superpowers/plans/phase0-gate-result.md` に追記（完了日 UTC・コミット範囲・全テスト結果・WS1〜6 対応表・Inv-1/5/6/7 充足・perf スケール証跡＋`_ITEMS_PER_MB` 較正値と根拠・`requirements.lock` オフライン再現結果・v1 出荷判定＝稼働先想定モダンLinux/glibc≧2.17 前提）。

```bash
git add src/grep_analyzer/budget.py tests/perf/test_perf.py tests/integration/test_inv1_items_per_mb.py tests/unit/test_requirements_lock_offline.py docs/superpowers/plans/phase0-gate-result.md docs/superpowers/plans/phase3-perf-report.md
git commit -m "feat(phase3): perf計測＋_ITEMS_PER_MB実測較正＋Inv-1能動ガード＋Phase3完了記録（WS6/WS5・v1出荷可能）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review（spec v4 との突合）

**1. Spec coverage:**

| spec v4 | 実装タスク |
|---|---|
| §2 EngineOptions 末尾既定・CLI | Task 1 |
| §3 手順1 `_canonical_data_blob` | Task 2 |
| §3 手順2-6 part分割/manifest/孤児・WS1原子性・WS2 | Task 3 |
| §4 WS1 完了判定5条件 | Task 4 |
| §4 WS1 耐クラッシュ・§7 注入方針・Inv-7 | Task 5 |
| §4 WS3 §10.3縮約/§8.4免除・Inv-6・detail_limit=0同値 | Task 6 |
| §3 pipeline 配線・resume スキップ・Inv-1 byte不変 | Task 7 |
| §4 WS4 3 decode 経路・output_encoding・BOM | Task 8（BOM は Task 3 で実装・WS4 で検証） |
| §4 WS6 perf 非ゲート機構・I-A/I-B | Task 9 |
| §4 WS6 corpus_gen・§4 WS5 lock 整合 | Task 10 |
| §4 WS6 perf計測/`_ITEMS_PER_MB`較正・Inv-1能動ガード・WS5 offline・§8 完了記録 | Task 11 |
| Inv-1/5/6/7 回帰 | Task 3/5/6/7/11（既存 golden14・167 を各タスク Step で byte 不変確認） |

スコープ外（spec §1）＝キーワード内チェックポイント resume・動的トップN・実60GB実測は本計画でも非対象（spec 準拠）。

**2. Placeholder scan:** 各 Step に実コード/実コマンド/期待出力を記載。`_ITEMS_PER_MB` 較正値のみ実測依存だが Task 11 Step 3 に**実行可能な `test_calibrate_items_per_mb`**（tracemalloc ピーク × `estimate_items` spy で bytes/item を実測し `ITEMS_PER_MB=<X>` を出力）＋採用手順を具体化済（散文 placeholder を排除）。Task 1/Task 6 の「Step1 テストを後 Step で書換」パターンは解消（Step1 を最終形＝tuple は `list(...)` 比較、§8.4 は `_is_exempt` import 形で記述）。

**3. Type consistency:** `_data_line(h) -> str` / `_blob_from_data_rows(data_rows: list[str]) -> bytes`（**書込側 `_canonical_data_blob` と完了判定 `resume.is_complete` が共有する唯一の正規化終端**＝spec v4 §3 手順1）/ `_canonical_data_blob(ordered: list[Hit]) -> bytes` / `_rows_from_part_text(text) -> list[str]`（先頭 BOM 除去込み・`split("\n")`）/ `finalize(out_dir, keyword, rows, opts)` / `resume.is_complete(out_dir, keyword, opts) -> bool` / `_write_manifest(out_dir, keyword, manifest)` / `_is_exempt(cat, exempt=SECTION_8_4_CATEGORIES) -> bool`（`render` が委譲＝`prov_` 判定単一源）/ `Diagnostics.render(detail_limit=0, exempt=None)` / `_file_meta(rel, raw, lang_map, fallback_chain=None)` を全タスクで一貫使用。`EngineOptions.encoding_fallback` は `tuple` 既定・利用側 `list(...)`。Task 8 の `_scan_file` args 拡張は `fixedpoint.py:248` と `:264` の**2 箇所両方**を明記。

**4. Plan review reflected（v3）:** 3軸計画レビュー第1〜2ラウンド反映。第1ラウンド＝(a) 完了判定が書込側と同一関数 `_blob_from_data_rows` 共有（C-1/C-3）、(b) lock テストを spec §4.1 必須依存名で照合＋pyahocorasick 欠落注記（I-3）、(c) Task9 `markexpr` トークン判定＋pytester `makeini`（I-1）、(d) Task2 アンカーを sanitize 適用＋実 U+2028 強化（重大1）、(e) Task6 `render`→`_is_exempt` 委譲（重大2）、(f) Task3 `nparts=9→width2`（M-2）、(g) Task1/6 Step1 を最終形（書換パターン排除）。**第2ラウンド（TDD軸が実測検出）**＝(h) Task11 `test_calibrate_items_per_mb` は既定経路で `estimate_items` 不発火（`not budget.unlimited` 配下）ゆえ `--memory-limit 100000` 付き＋`assert seen` で較正不能を明示 FAIL（Critical-1）、(i) Task8/11 の `_run`/`_split_fixture` を `mkdir(parents=True, exist_ok=True)` に修正（Critical-2）、(j) Task8 分割テストを test_fixedpoint.py:212 同型の実分割発火 fixture に再設計（Important-A）。**第3ラウンド（TDD軸が実測検出）**＝(k) `decode_bytes` は ② chardet 検出が ③ fallback 鎖より先で短いソースを高確信確定するため、`--encoding-fallback` 変化が出力に出ず Task8 の WS4 検出テストが配線正否に依らず永久 FAIL（偽 RED）＝TDD 駆動不能（C-new-1）。対応: Task8 全 encoding テストを `monkeypatch.setattr("grep_analyzer.encoding.chardet.detect", lambda d: {"encoding": None})` で ② を中立化し ③ を**決定的に経由**させる設計に再構築（本番 decode 挙動は不変・テスト都合のみ）。spec整合・依存整合の2軸は第2ラウンドで収束確認済（v3/v4 変更は Task8/11 テストコード＋注記のみで他軸結論不変）。Inv-1 byte 不変は第1ラウンドで実コード1バイト突合により完全一致を実証済（Task7 安全）。

**既知の計画内委譲（spec v4 整合・非ブロッカー）:** `tsv.write_tsv` の薄ラッパ残置 vs `output_writer` 吸収は Task 7 実装時に一意化（制約: Inv-1＋§10.3 原子プリミティブ保持。本計画は `output_writer._atomic_write` で原子プリミティブを内製再現し `write_tsv` を据置く＝最小差分・Inv-1 安全）。
