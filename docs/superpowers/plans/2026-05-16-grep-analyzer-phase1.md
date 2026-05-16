# grep_analyzer Phase 1 (決定的コア) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** grep結果（`input/<keyword>.grep`）を読み、direct参照のみを言語別に分類し、完全決定的なTSVとgoldenを出力する「決定的コア」を作る（多ホップ間接追跡なし）。

**Architecture:** 純Pythonパッケージ `grep_analyzer`。パイプライン Ingest→言語ディスパッチ→分類器（Java/C/Pro\*C=tree-sitter, SQL/Shell=正規表現）→決定的TSV出力＋診断。Phase 1 は spec §15 フェーズ1（direct のみ・完全決定性）に対応。間接参照エンジン（§8）は Phase 2 で別計画。

**Tech Stack:** Python 3.12 / pytest / tree-sitter==0.21.3 + tree-sitter-java==0.21.0 + tree-sitter-c==0.21.4 / chardet==5.2.0。設計書 `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`（最新版が正）、テスト規約 `.claude/skills/writing-tests.md`、コーディング規約 `.claude/skills/coding-conventions.md` に従う（docstring/コメントは日本語、テスト名は日本語）。

---

## Task 0: フェーズ0ゲート G1（実装着手前の前提検証・コードなし）

spec §4.2 G1 / §15 フェーズ0。**本タスクが通らない限り Task 1 以降に着手しない。**

- [ ] **Step 1: ターゲット環境を確定し記録**

ターゲット実機（または同等環境）で確認し、結果を `docs/superpowers/plans/phase0-gate-result.md` に追記:
```bash
uname -m            # CPUアーキ (例: x86_64 / aarch64)
ldd --version | head -1   # glibc 版（musl の場合は `ldd` 出力で判別）
python3.12 --version
python3.12 -c "import sysconfig; print(sysconfig.get_platform())"
```

- [ ] **Step 2: 全必須依存の wheel がオフライン取得可能か実証**

開発環境（オンライン可）で、ターゲットの platform タグに対して:
```bash
mkdir -p wheelhouse
# <PLAT> は Step 1 の sysconfig.get_platform() を pip タグ化したもの
# （例 linux-x86_64 → manylinux2014_x86_64 / 対象が musl なら musllinux_*）
pip download --dest wheelhouse --only-binary=:all: \
  --implementation cp --python-version 3.12 --abi cp312 --platform <PLAT> \
  "tree-sitter==0.21.3" "tree-sitter-java==0.21.0" "tree-sitter-c==0.21.4" "chardet==5.2.0" \
  pytest
ls wheelhouse
```
Expected: 上記すべて（推移依存含む）の cp312・対象 `<PLAT>` 向け `.whl` が `wheelhouse/` に揃う。1つでも sdist しか取れない／取得不能なら、spec §4.2 の (a) sdistビルド同梱 or (b) 代替 を本計画着手前に意思決定し、`phase0-gate-result.md` に記録。

- [ ] **Step 3: ゲート判定を記録**

`phase0-gate-result.md` に「G1: PASS（アーキ/libc/wheel 揃い）」または「G1: FAIL（理由・対応）」を明記。PASS のときのみ Task 1 へ進む。

---

## Task 1: プロジェクト雛形と pytest マーカ

**Files:**
- Create: `pyproject.toml`
- Create: `src/grep_analyzer/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: 失敗するスモークテストを書く**

`tests/test_smoke.py`:
```python
"""パッケージimport と CLI 起動の生存確認（spec §11 smoke）。"""


def test_grep_analyzerをimportできる():
    import grep_analyzer  # noqa: F401
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/test_smoke.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'grep_analyzer'`）

- [ ] **Step 3: 雛形を作成**

`pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "grep_analyzer"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "tree-sitter==0.21.3",
    "tree-sitter-java==0.21.0",
    "tree-sitter-c==0.21.4",
    "chardet==5.2.0",
]

[project.optional-dependencies]
dev = ["pytest>=8"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "perf: 性能ダッシュボード（非ゲート・CI停止しない。spec §11）",
    "requires_ripgrep: 実ripgrepバイナリを要する隔離テスト（spec §11）",
]
```

`src/grep_analyzer/__init__.py`:
```python
"""grep結果を言語別に分類し決定的TSVを出力するツール。"""

__version__ = "0.1.0"
```

`tests/conftest.py`:
```python
"""pytest 共通設定。src レイアウトを import 可能にする。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add pyproject.toml src/grep_analyzer/__init__.py tests/conftest.py tests/test_smoke.py
git commit -m "feat: プロジェクト雛形とpytestマーカ"
```

---

## Task 2: ドメインモデル（Hit / TSVスキーマ / 決定的ソート）

**Files:**
- Create: `src/grep_analyzer/model.py`
- Test: `tests/unit/test_model.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_model.py`:
```python
"""ドメインモデルとTSV決定的ソートの仕様。"""

from grep_analyzer.model import TSV_COLUMNS, Hit, sort_key


def test_TSV列順はspec9の固定順である():
    assert TSV_COLUMNS == [
        "keyword", "language", "file", "lineno", "ref_kind",
        "category", "category_sub", "usage_summary", "via_symbol",
        "chain", "snippet", "encoding", "confidence",
    ]


def test_Hitはタプル化でTSV列順に並ぶ():
    h = Hit(
        keyword="K", language="java", file="a/b.java", lineno=3,
        ref_kind="direct", category="比較", category_sub="",
        usage_summary="if 比較", via_symbol="", chain="K@a/b.java:3",
        snippet='if (x.equals("K"))', encoding="utf-8", confidence="high",
    )
    assert h.to_row() == [
        "K", "java", "a/b.java", "3", "direct", "比較", "",
        "if 比較", "", "K@a/b.java:3", 'if (x.equals("K"))', "utf-8", "high",
    ]


def test_sort_keyはfile_lineno_ref_kindの順で全順序を与える():
    a = Hit("K", "java", "a.java", 2, "direct", "比較", "", "", "", "K@a.java:2", "s", "utf-8", "high")
    b = Hit("K", "java", "a.java", 10, "direct", "比較", "", "", "", "K@a.java:10", "s", "utf-8", "high")
    assert sorted([b, a], key=sort_key) == [a, b]
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/unit/test_model.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/model.py`:
```python
"""ドメインモデル（Hit）とTSVスキーマ・決定的ソート（spec §9）。"""

from dataclasses import dataclass

TSV_COLUMNS = [
    "keyword", "language", "file", "lineno", "ref_kind",
    "category", "category_sub", "usage_summary", "via_symbol",
    "chain", "snippet", "encoding", "confidence",
]


@dataclass(frozen=True)
class Hit:
    """TSV1行に対応する分類結果。Phase 1 では ref_kind は常に "direct"。"""

    keyword: str
    language: str
    file: str
    lineno: int
    ref_kind: str
    category: str
    category_sub: str
    usage_summary: str
    via_symbol: str
    chain: str
    snippet: str
    encoding: str
    confidence: str

    def to_row(self) -> list[str]:
        """TSV_COLUMNS の順で文字列セルのリストを返す。"""
        return [
            self.keyword, self.language, self.file, str(self.lineno),
            self.ref_kind, self.category, self.category_sub,
            self.usage_summary, self.via_symbol, self.chain,
            self.snippet, self.encoding, self.confidence,
        ]


def sort_key(h: Hit) -> tuple:
    """spec §9 の全順序安定ソートキー。lineno は数値順。"""
    return (
        h.file, h.lineno, h.ref_kind, h.via_symbol, h.chain,
        h.category, h.category_sub, h.confidence, h.usage_summary, h.snippet,
    )
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/unit/test_model.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/model.py tests/unit/test_model.py
git commit -m "feat: Hitモデルとtsv決定的ソートキー"
```

---

## Task 3: grep行パーサ（最左の数字コロン境界）

**Files:**
- Create: `src/grep_analyzer/ingest.py`
- Test: `tests/unit/test_ingest.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_ingest.py`:
```python
"""grep -rn 行パースの仕様（spec §6）。"""

from grep_analyzer.ingest import parse_grep_line


def test_通常行はpath_lineno_contentに分割する():
    assert parse_grep_line("src/A.java:42:  if (x)") == ("src/A.java", 42, "  if (x)")


def test_最左の数字コロン境界を採用しパス内コロンに耐える():
    assert parse_grep_line("C:\\a:10:code") == ("C:\\a", 10, "code")


def test_content先頭が数字コロンでも最左境界で切る():
    assert parse_grep_line("a.sh:3:5: not a lineno") == ("a.sh", 3, "5: not a lineno")


def test_lineno無し行はNoneを返す():
    assert parse_grep_line("justtext without colon number") is None
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/unit/test_ingest.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/ingest.py`:
```python
"""input/*.grep の行パース（spec §6）。"""

import re

_LINE_RE = re.compile(r"^(?P<path>.*?):(?P<lineno>\d+):(?P<content>.*)$", re.DOTALL)


def parse_grep_line(line: str) -> tuple[str, int, str] | None:
    """`path:lineno:content` を最左の `:<数字>:` 境界で分割する。

    不一致なら None（呼び出し側が diagnostics に回す）。
    """
    m = _LINE_RE.match(line.rstrip("\n"))
    if m is None:
        return None
    return m.group("path"), int(m.group("lineno")), m.group("content")
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/unit/test_ingest.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/ingest.py tests/unit/test_ingest.py
git commit -m "feat: grep行パーサ(最左数字コロン境界)"
```

---

## Task 4: 文字コード判定（決定的フォールバック鎖・落とさない）

**Files:**
- Create: `src/grep_analyzer/encoding.py`
- Test: `tests/unit/test_encoding.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_encoding.py`:
```python
"""文字コード判定とフォールバック（spec §10.1）。

chardet の検出は短い/曖昧な入力で結果が揺れる（実測: 短い cp932 を Windows-1252、
`\\xff\\xfe..` を UTF-16 と誤検出）。決定的に検証するため、フォールバック経路の
テストは chardet.detect を stub する（chardet は外部の検出オラクル＝外部I/O境界。
writing-tests.md のモック線引きに合致）。実 chardet 経路は「決して落ちない」契約のみ検証。
"""

from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes


def test_UTF8は置換なしで復号される():
    text, enc, replaced = decode_bytes("あいう".encode("utf-8"), DEFAULT_FALLBACK)
    assert text == "あいう"
    assert enc == "utf-8"
    assert replaced is False


def test_検出不発時はフォールバック鎖のcp932で復号される(monkeypatch):
    monkeypatch.setattr(
        "grep_analyzer.encoding.chardet.detect", lambda b: {"encoding": None}
    )
    text, enc, replaced = decode_bytes("日本語".encode("cp932"), DEFAULT_FALLBACK)
    assert text == "日本語"
    assert enc == "cp932"
    assert replaced is False


def test_どの厳格復号も不可ならlatin1置換で要確認になる(monkeypatch):
    monkeypatch.setattr(
        "grep_analyzer.encoding.chardet.detect", lambda b: {"encoding": None}
    )
    # 単独の \x81 は cp932/euc-jp の不完全リード byte かつ utf-8 不正 →
    # latin-1 置換へ確定（注: \xff は Python の cp932 が PUA に写すため不可）
    text, enc, replaced = decode_bytes(b"\x81", DEFAULT_FALLBACK)
    assert isinstance(text, str)
    assert enc == "latin-1"
    assert replaced is True


def test_実chardet経路でも例外を投げない():
    text, enc, replaced = decode_bytes("日本語".encode("cp932"), DEFAULT_FALLBACK)
    assert isinstance(text, str)  # 誤検出し得るが「決して落ちない」契約のみ検証
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/unit/test_encoding.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/encoding.py`:
```python
"""文字コード判定と決定的フォールバック鎖（spec §10.1）。decodeで絶対に落とさない。"""

import chardet

# spec §10.1: utf-8 → 検出結果 → cp932/euc-jp → latin-1（置換・最終手段）
DEFAULT_FALLBACK = ["cp932", "euc-jp", "latin-1"]


def decode_bytes(data: bytes, fallback_chain: list[str]) -> tuple[str, str, bool]:
    """(text, 使用エンコーディング, 置換が発生したか) を返す。

    手順: ① utf-8 厳格 → ② chardet 検出（全バイト1回）→ ③ fallback_chain 順に厳格 →
    ④ latin-1 + replace（必ず成功・置換フラグ True）。

    短い/曖昧な入力では chardet が誤検出し得る（spec §10.1 の既知の限界）。
    その場合も例外は出さず、置換発生時は encoding 列＋diagnostics の「要確認」で
    顕在化させる（呼び出し側責務）。
    """
    try:
        return data.decode("utf-8"), "utf-8", False
    except UnicodeDecodeError:
        pass

    detected = chardet.detect(data).get("encoding")
    if detected:
        try:
            return data.decode(detected), detected.lower(), False
        except (UnicodeDecodeError, LookupError):
            pass

    for enc in fallback_chain[:-1]:
        try:
            return data.decode(enc), enc, False
        except (UnicodeDecodeError, LookupError):
            continue

    last = fallback_chain[-1]
    return data.decode(last, errors="replace"), last, True
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/unit/test_encoding.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/encoding.py tests/unit/test_encoding.py
git commit -m "feat: 文字コード判定とフォールバック鎖"
```

---

## Task 5: 言語ディスパッチ（拡張子＋EXEC SQLヒューリスティック）

**Files:**
- Create: `src/grep_analyzer/dispatch.py`
- Test: `tests/unit/test_dispatch.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_dispatch.py`:
```python
"""言語ディスパッチの決定的規則（spec §5.1）。"""

from grep_analyzer.dispatch import detect_language


def test_拡張子で言語を判定する():
    assert detect_language("a/B.java", "", {}) == "java"
    assert detect_language("a/q.sql", "", {}) == "sql"
    assert detect_language("a/run.sh", "", {}) == "shell"
    assert detect_language("a/m.c", "", {}) == "c"


def test_EXEC_SQLを含むcはProCと判定する():
    assert detect_language("a/m.c", "  EXEC SQL SELECT 1;", {}) == "proc"


def test_pc拡張子はProCである():
    assert detect_language("a/m.pc", "", {}) == "proc"


def test_lang_map上書きが効く():
    assert detect_language("a/x.inc", "", {".inc": "shell"}) == "shell"


def test_判定不能はcにフォールバックする():
    assert detect_language("a/unknown.xyz", "no exec sql here", {}) == "c"
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/unit/test_dispatch.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/dispatch.py`:
```python
"""ファイルの言語判定（spec §5.1）。"""

import os
import re

_EXT_MAP = {
    ".java": "java",
    ".sql": "sql",
    ".sh": "shell", ".ksh": "shell", ".bash": "shell",
    ".pc": "proc",
    ".c": "c", ".h": "c",
}
_EXEC_SQL_RE = re.compile(r"\bEXEC\s+SQL\b", re.IGNORECASE)


def detect_language(path: str, content_sample: str, lang_map: dict[str, str]) -> str:
    """拡張子マップ＋内容ヒューリスティックで言語を返す。判定不能は "c"。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in lang_map:
        return lang_map[ext]
    lang = _EXT_MAP.get(ext)
    if lang in ("c", "proc") or ext == ".h":
        if _EXEC_SQL_RE.search(content_sample):
            return "proc"
        return lang or "c"
    if lang is not None:
        return lang
    return "c"
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/unit/test_dispatch.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/dispatch.py tests/unit/test_dispatch.py
git commit -m "feat: 言語ディスパッチ(拡張子+EXEC SQL)"
```

---

## Task 6: Pro\*C 前処理（行数保存のプレースホルダ置換）

**Files:**
- Create: `src/grep_analyzer/proc_preprocess.py`
- Test: `tests/unit/test_proc_preprocess.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_proc_preprocess.py`:
```python
"""Pro*C の EXEC SQL 区間を行数保存して中立化する（spec §7・行番号不変）。"""

from grep_analyzer.proc_preprocess import mask_exec_sql


def test_行数は保存される():
    src = "int a;\nEXEC SQL SELECT 1\n  INTO :x\nFROM t;\nint b;\n"
    out = mask_exec_sql(src)
    assert out.count("\n") == src.count("\n")
    assert out.splitlines()[0] == "int a;"
    assert out.splitlines()[4] == "int b;"


def test_EXEC_SQL区間はC構文を壊さない中立行に置換される():
    src = "EXEC SQL SELECT 1;\n"
    out = mask_exec_sql(src)
    assert "SELECT" not in out
    assert out.endswith("\n")
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/unit/test_proc_preprocess.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/proc_preprocess.py`:
```python
"""Pro*C前処理: EXEC SQL / EXEC ORACLE 区間を行数保存で中立トークンに置換（spec §7）。

行番号を原ソースと不変に保つため、置換は各物理行を「同じ行数の空文字列」に潰し
改行のみ残す（桁ズレは許容、行番号は不変）。
"""

import re

# `EXEC SQL ... ;` / `EXEC SQL ... END-EXEC` / `EXEC ORACLE ... ;` を行跨ぎで捕捉
_EXEC_RE = re.compile(
    r"\bEXEC\s+(?:SQL|ORACLE)\b.*?(?:;|END-EXEC\b)",
    re.IGNORECASE | re.DOTALL,
)


def mask_exec_sql(source: str) -> str:
    """EXEC SQL/ORACLE 区間を中立化。区間内の各行を空行化し改行数を保存する。"""

    def _blank(m: re.Match) -> str:
        # マッチ内の改行数を保ち、各行の中身を消す（行番号不変）
        return "\n" * m.group(0).count("\n")

    return _EXEC_RE.sub(_blank, source)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/unit/test_proc_preprocess.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/proc_preprocess.py tests/unit/test_proc_preprocess.py
git commit -m "feat: Pro*C前処理(行数保存マスク)"
```

---

## Task 7: 正規表現分類器（SQL / Shell）

**Files:**
- Create: `src/grep_analyzer/classifiers/__init__.py`
- Create: `src/grep_analyzer/classifiers/base.py`
- Create: `src/grep_analyzer/classifiers/regex_classifier.py`
- Test: `tests/unit/test_regex_classifier.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_regex_classifier.py`:
```python
"""SQL/Shell の正規表現分類（spec §7）。confidence は medium。"""

from grep_analyzer.classifiers.regex_classifier import classify_sql, classify_shell


def test_SQLのWHERE比較は比較と判定する():
    assert classify_sql("WHERE col = 'X'") == ("比較", "medium")


def test_SQLのINSERT_VALUESは代入と判定する():
    assert classify_sql("INSERT INTO t VALUES ('X')") == ("代入", "medium")


def test_Shellの変数代入は代入と判定する():
    assert classify_shell('CODE="X"') == ("代入", "medium")


def test_Shellのtest比較は比較と判定する():
    assert classify_shell('[ "$x" = "X" ]') == ("比較", "medium")


def test_該当規則がなければその他と判定する():
    assert classify_sql("-- just a comment") == ("その他", "medium")
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/unit/test_regex_classifier.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/classifiers/__init__.py`:
```python
"""言語別分類器パッケージ（spec §7）。"""
```

`src/grep_analyzer/classifiers/base.py`:
```python
"""分類器の共通型。Phase 1 は direct 行の分類のみ（spec §15 フェーズ1）。"""

# 分類結果 = (共通上位カテゴリ, confidence)。category_sub は v1 空固定（spec §9）。
ClassifyResult = tuple[str, str]
```

`src/grep_analyzer/classifiers/regex_classifier.py`:
```python
"""SQL/Shell の正規表現分類（spec §7）。"""

import re

from grep_analyzer.classifiers.base import ClassifyResult

_SQL_RULES = [
    (re.compile(r"\bWHERE\b.*?[=<>]", re.IGNORECASE), "比較"),
    (re.compile(r"\bCASE\s+WHEN\b", re.IGNORECASE), "分岐"),
    (re.compile(r"\b(?:INSERT|UPDATE)\b", re.IGNORECASE), "代入"),
]
_SHELL_RULES = [
    (re.compile(r"^\s*\w+="), "代入"),
    (re.compile(r"\[\s+.+?(?:=|==|-eq)\s+.+?\]"), "比較"),
    (re.compile(r"^\s*case\s+"), "分岐"),
]


def _apply(rules, line: str) -> ClassifyResult:
    for pat, cat in rules:
        if pat.search(line):
            return (cat, "medium")
    return ("その他", "medium")


def classify_sql(line: str) -> ClassifyResult:
    """SQL行を分類する。"""
    return _apply(_SQL_RULES, line)


def classify_shell(line: str) -> ClassifyResult:
    """Shell行を分類する。"""
    return _apply(_SHELL_RULES, line)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/unit/test_regex_classifier.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/classifiers/ tests/unit/test_regex_classifier.py
git commit -m "feat: SQL/Shell正規表現分類器"
```

---

## Task 8: tree-sitter 分類器（Java / C / Pro\*C）

**Files:**
- Create: `src/grep_analyzer/classifiers/ts_classifier.py`
- Test: `tests/unit/test_ts_classifier.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_ts_classifier.py`:
```python
"""tree-sitter 分類（spec §7）。構文位置が確定すれば high。"""

from grep_analyzer.classifiers.ts_classifier import classify_ts


def test_Javaのif比較行は比較highと判定する():
    src = 'class A {\n void m(){\n  if (s.equals("K")) {}\n }\n}\n'
    assert classify_ts("java", src, 3) == ("比較", "high")


def test_Javaのフィールド宣言は宣言highと判定する():
    src = 'class A {\n static final String K = "K";\n}\n'
    assert classify_ts("java", src, 2) == ("宣言", "high")


def test_Cのdefineは宣言highと判定する():
    src = '#define CODE "X"\nint main(){return 0;}\n'
    assert classify_ts("c", src, 1) == ("宣言", "high")


def test_ProCはEXEC_SQLをマスクしてもC宣言を分類できる():
    # `char *p = "X";` は C の declaration（宣言）。EXEC SQL 行が中立化されても
    # 行番号保存のため3行目が宣言として解釈できることを確認する。
    src = 'int f(){\n EXEC SQL SELECT 1;\n char *p = "X";\n}\n'
    assert classify_ts("proc", src, 3) == ("宣言", "high")
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/unit/test_ts_classifier.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/classifiers/ts_classifier.py`:
```python
"""tree-sitter による Java/C/Pro*C 分類（spec §7、py-tree-sitter 0.21 API）。"""

import tree_sitter_c
import tree_sitter_java
from tree_sitter import Language, Parser

from grep_analyzer.classifiers.base import ClassifyResult
from grep_analyzer.proc_preprocess import mask_exec_sql

# py-tree-sitter 0.21.3 の Language.__init__ は (ptr, name) の2引数必須。
# tree_sitter_<lang>.language() は int ポインタを返す（spec §4.1 ロード規約）。
_JAVA = Language(tree_sitter_java.language(), "java")
_C = Language(tree_sitter_c.language(), "c")

# ノード型 → 共通上位カテゴリ（spec §7 の判定軸の最小集合）。
# Phase 1 は決定的基盤が目的（分類精度は handcrafted の領分・spec §11）。
# 内側から外へ climb して最初に一致した「文レベル」ノードのカテゴリを採る。
# argument_list / init_declarator は包含関係で if/宣言 と衝突するため意図的に含めない。
_CATEGORY_BY_NODE = {
    "if_statement": "比較",
    "switch_statement": "分岐",
    "switch_expression": "分岐",
    "field_declaration": "宣言",
    "local_variable_declaration": "宣言",
    "declaration": "宣言",
    "preproc_def": "宣言",
    "assignment_expression": "代入",
    "return_statement": "return",
}


def _parser(language: str) -> Parser:
    # "proc" を含む非 Java 言語は tree-sitter-c で解析する（spec §7 Pro*C 前処理方式）。
    p = Parser()
    p.set_language(_JAVA if language == "java" else _C)
    return p


def _node_at_line(root, lineno: int):
    """対象行（0始まり=lineno-1）を内包する最小ノードを決定的に返す。

    同スパンの曖昧さを除くため、`(行スパン, start_byte, end_byte, ノード型)` の最小で
    一意に選ぶ（走査順に依存しない決定的な全順序・spec §9 決定性）。
    """
    target = lineno - 1
    best = None
    best_key = None
    cursor = [root]
    while cursor:
        node = cursor.pop()
        if node.start_point[0] <= target <= node.end_point[0]:
            key = (node.end_point[0] - node.start_point[0], node.start_byte, node.end_byte, node.type)
            if best_key is None or key < best_key:
                best, best_key = node, key
            cursor.extend(node.children)
    return best


def classify_ts(language: str, source: str, lineno: int) -> ClassifyResult:
    """ファイル全体を AST 解析し、対象行を含む構文要素から分類する。"""
    src = mask_exec_sql(source) if language == "proc" else source
    tree = _parser(language).parse(src.encode("utf-8"))
    node = _node_at_line(tree.root_node, lineno)
    while node is not None:
        cat = _CATEGORY_BY_NODE.get(node.type)
        if cat is not None:
            return (cat, "high")
        node = node.parent
    return ("その他", "high")
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/unit/test_ts_classifier.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/classifiers/ts_classifier.py tests/unit/test_ts_classifier.py
git commit -m "feat: tree-sitter分類器(Java/C/ProC)"
```

---

## Task 9: 診断コレクタ

**Files:**
- Create: `src/grep_analyzer/diagnostics.py`
- Test: `tests/unit/test_diagnostics.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_diagnostics.py`:
```python
"""診断の集約とスキーマ（spec §10.3: カテゴリ別件数サマリ＋詳細）。"""

from grep_analyzer.diagnostics import Diagnostics


def test_カテゴリ別件数サマリが先頭に来る():
    d = Diagnostics()
    d.add("bad_grep_line", "input/k.grep:5")
    d.add("bad_grep_line", "input/k.grep:9")
    d.add("decode_replaced", "src/a.c")
    text = d.render()
    lines = text.splitlines()
    assert lines[0] == "# summary"
    assert "bad_grep_line\t2" in text
    assert "decode_replaced\t1" in text
    assert "# detail" in text
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/unit/test_diagnostics.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/diagnostics.py`:
```python
"""非致命の診断を集約する（spec §10.3）。先頭にカテゴリ別件数サマリ、続いて詳細。"""

from collections import Counter, defaultdict


class Diagnostics:
    """カテゴリ別に診断メッセージを蓄積し、サマリ＋詳細で描画する。"""

    def __init__(self) -> None:
        self._counts: Counter = Counter()
        self._detail: dict[str, list[str]] = defaultdict(list)

    def add(self, category: str, message: str) -> None:
        """1件の診断を記録する。"""
        self._counts[category] += 1
        self._detail[category].append(message)

    def render(self) -> str:
        """spec §10.3 のスキーマ（summary→detail）でテキスト化する。"""
        out = ["# summary"]
        for cat in sorted(self._counts):
            out.append(f"{cat}\t{self._counts[cat]}")
        out.append("# detail")
        for cat in sorted(self._detail):
            for msg in self._detail[cat]:
                out.append(f"{cat}\t{msg}")
        return "\n".join(out) + "\n"
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/unit/test_diagnostics.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/diagnostics.py tests/unit/test_diagnostics.py
git commit -m "feat: 診断コレクタ(summary+detail)"
```

---

## Task 10: TSV 書き出し（決定的ソート＋原子的書込＋BOM規則）

**Files:**
- Create: `src/grep_analyzer/tsv.py`
- Test: `tests/unit/test_tsv.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_tsv.py`:
```python
"""TSV出力: 決定的ソート・タブ改行サニタイズ・原子的書込・BOM規則（spec §9/§10.3）。"""

from pathlib import Path

from grep_analyzer.model import Hit
from grep_analyzer.tsv import write_tsv


def _h(file, lineno, snippet="s"):
    return Hit("K", "java", file, lineno, "direct", "比較", "", "u", "", f"K@{file}:{lineno}", snippet, "utf-8", "high")


def test_出力はヘッダ付きで決定的にソートされる(tmp_path: Path):
    out = tmp_path / "K.tsv"
    write_tsv(out, [_h("b.java", 1), _h("a.java", 2)], "utf-8-sig")
    raw = out.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf"  # UTF-8 BOM
    rows = raw.decode("utf-8-sig").splitlines()
    assert rows[0].split("\t")[0] == "keyword"
    assert rows[1].split("\t")[2] == "a.java"
    assert rows[2].split("\t")[2] == "b.java"


def test_非UTF8出力ではBOMを付けない(tmp_path: Path):
    out = tmp_path / "K.tsv"
    write_tsv(out, [_h("a.java", 1)], "cp932")
    assert out.read_bytes()[:3] != b"\xef\xbb\xbf"


def test_セル内タブと改行は空白化され列数が保たれる(tmp_path: Path):
    from grep_analyzer.model import TSV_COLUMNS

    out = tmp_path / "K.tsv"
    write_tsv(out, [_h("a.java", 1, snippet="x\ty\nz")], "utf-8-sig")
    data_row = out.read_text("utf-8-sig").splitlines()[1]
    cells = data_row.split("\t")
    assert len(cells) == len(TSV_COLUMNS)  # サニタイズで列がズレない
    assert cells[TSV_COLUMNS.index("snippet")] == "x y z"
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/unit/test_tsv.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/tsv.py`:
```python
"""TSV出力（spec §9）。決定的全順序ソート・サニタイズ・原子的書込・BOM規則。"""

import os
import tempfile
from pathlib import Path

from grep_analyzer.model import TSV_COLUMNS, Hit, sort_key


def _sanitize(cell: str) -> str:
    """フィールド内のタブ・改行を空白に置換する（spec §9）。"""
    return cell.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def write_tsv(path: Path, hits: list[Hit], encoding: str) -> None:
    """hits を決定的にソートし、一時ファイル→fsync→rename で原子的に書き出す。

    encoding が "utf-8-sig" のときのみ BOM を付与（非UTF-8は付けない・spec §9）。
    """
    ordered = sorted(hits, key=sort_key)
    lines = ["\t".join(TSV_COLUMNS)]
    lines += ["\t".join(_sanitize(c) for c in h.to_row()) for h in ordered]
    data = ("\n".join(lines) + "\n").encode(encoding, errors="replace")

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # rename 済みのみ完了（spec §10.3）
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/unit/test_tsv.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/tsv.py tests/unit/test_tsv.py
git commit -m "feat: 決定的TSV書込(原子的・BOM規則)"
```

---

## Task 11: パイプライン（direct のみ・spec §15 フェーズ1）

**Files:**
- Create: `src/grep_analyzer/pipeline.py`
- Test: `tests/unit/test_pipeline.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_pipeline.py`:
```python
"""Ingest→dispatch→classify→TSV の direct-only パイプライン（spec §15 フェーズ1）。"""

from pathlib import Path

from grep_analyzer.pipeline import run


def test_grepヒットを分類してキーワード毎TSVを出力する(tmp_path: Path):
    src_root = tmp_path / "src"
    src_root.mkdir()
    (src_root / "A.java").write_text(
        'class A {\n void m(){\n  if (s.equals("STATUS_OK")) {}\n }\n}\n', "utf-8"
    )
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "STATUS_OK.grep").write_text("A.java:3:  if (s.equals(\"STATUS_OK\")) {}\n", "utf-8")
    out = tmp_path / "out"

    rc = run(input_dir=inp, output_dir=out, source_root=src_root)

    assert rc == 0
    tsv = (out / "STATUS_OK.tsv").read_text("utf-8-sig").splitlines()
    cols = tsv[0].split("\t")
    row = dict(zip(cols, tsv[1].split("\t")))
    assert row["keyword"] == "STATUS_OK"
    assert row["language"] == "java"
    assert row["file"] == "A.java"
    assert row["lineno"] == "3"
    assert row["ref_kind"] == "direct"
    assert row["category"] == "比較"
    assert row["confidence"] == "high"
    assert row["chain"] == "STATUS_OK@A.java:3"
    assert (out / "diagnostics.txt").exists()


def test_壊れたgrep行は捨てず診断に回る(tmp_path: Path):
    (tmp_path / "src").mkdir()
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "K.grep").write_text("this line has no lineno\n", "utf-8")
    out = tmp_path / "out"
    rc = run(input_dir=inp, output_dir=out, source_root=tmp_path / "src")
    assert rc == 0
    assert "bad_grep_line" in (out / "diagnostics.txt").read_text("utf-8")
    assert (out / "K.tsv").exists()
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/unit/test_pipeline.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/pipeline.py`:
```python
"""direct-only パイプライン（spec §15 フェーズ1）。多ホップ追跡は Phase 2。"""

from pathlib import Path

from grep_analyzer.classifiers.regex_classifier import classify_shell, classify_sql
from grep_analyzer.classifiers.ts_classifier import classify_ts
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.dispatch import detect_language
from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes
from grep_analyzer.ingest import parse_grep_line
from grep_analyzer.model import Hit
from grep_analyzer.tsv import write_tsv


def _classify(language: str, file_text: str, lineno: int, content: str):
    if language in ("java", "c", "proc"):
        return classify_ts(language, file_text, lineno)
    if language == "sql":
        return classify_sql(content)
    # shell および未知言語は正規表現(shell)分類にフォールバック
    # （Phase 2 で言語追加時は dispatch と本関数の両方を更新すること）
    return classify_shell(content)


def run(input_dir: Path, output_dir: Path, source_root: Path) -> int:
    """input/*.grep を処理し、キーワード毎TSV＋diagnostics.txt を出力する。"""
    diag = Diagnostics()
    output_dir.mkdir(parents=True, exist_ok=True)

    for grep_file in sorted(Path(input_dir).glob("*.grep")):
        keyword = grep_file.stem
        raw_bytes = grep_file.read_bytes()
        text, _, _ = decode_bytes(raw_bytes, DEFAULT_FALLBACK)
        hits: list[Hit] = []

        for raw_line in text.splitlines():
            parsed = parse_grep_line(raw_line)
            if parsed is None:
                diag.add("bad_grep_line", f"{grep_file.name}: {raw_line!r}")
                continue
            rel, lineno, content = parsed
            target = Path(source_root) / rel
            if not target.is_file():
                diag.add("missing_source", str(rel))
                continue
            file_text, enc, replaced = decode_bytes(target.read_bytes(), DEFAULT_FALLBACK)
            if replaced:
                diag.add("decode_replaced", str(rel))
            language = detect_language(rel, file_text[:4096], {})
            category, confidence = _classify(language, file_text, lineno, content)
            hits.append(Hit(
                keyword=keyword, language=language, file=rel, lineno=lineno,
                ref_kind="direct", category=category, category_sub="",
                usage_summary=f"{category} ({language})", via_symbol="",
                chain=f"{keyword}@{rel}:{lineno}", snippet=content,
                encoding=enc + (" 要確認" if replaced else ""), confidence=confidence,
            ))

        write_tsv(output_dir / f"{keyword}.tsv", hits, "utf-8-sig")

    (output_dir / "diagnostics.txt").write_text(diag.render(), encoding="utf-8")
    return 0
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/unit/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/pipeline.py tests/unit/test_pipeline.py
git commit -m "feat: direct-onlyパイプライン"
```

---

## Task 12: CLI と smoke 強化

**Files:**
- Create: `src/grep_analyzer/cli.py`
- Create: `src/grep_analyzer/__main__.py`
- Modify: `tests/test_smoke.py`
- Test: `tests/integration/test_cli.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/integration/test_cli.py`:
```python
"""CLI境界契約（spec §10.4）。in-process 既定。"""

from pathlib import Path

from grep_analyzer.cli import main


def test_必須引数で実行しexit0とTSVを返す(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "A.java").write_text('class A{String K="K";}\n', "utf-8")
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "K.grep").write_text('A.java:1:class A{String K="K";}\n', "utf-8")
    out = tmp_path / "out"
    rc = main([
        "--input", str(inp), "--output", str(out), "--source-root", str(tmp_path / "src"),
    ])
    assert rc == 0
    assert (out / "K.tsv").exists()
```

`tests/test_smoke.py` に追記:
```python
def test_CLIのhelpがexit0を返す():
    import subprocess
    import sys
    from pathlib import Path

    src_dir = Path(__file__).resolve().parents[1] / "src"
    r = subprocess.run(
        [sys.executable, "-m", "grep_analyzer", "--help"],
        capture_output=True, cwd=str(src_dir),
    )
    assert r.returncode == 0


def test_tree_sitter言語がロードできる():
    from grep_analyzer.classifiers.ts_classifier import classify_ts

    assert classify_ts("java", "class A{}\n", 1)[1] == "high"
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/integration/test_cli.py tests/test_smoke.py -v`
Expected: FAIL（`ModuleNotFoundError: grep_analyzer.cli`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/cli.py`:
```python
"""CLIエントリ（spec §10.4）。Phase 1 は direct-only オプションのみ実装。"""

import argparse
from pathlib import Path

from grep_analyzer.pipeline import run


def main(argv: list[str] | None = None) -> int:
    """引数をパースし direct-only パイプラインを実行する。終了コードを返す。"""
    p = argparse.ArgumentParser(prog="grep_analyzer")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--source-root", required=True, dest="source_root")
    args = p.parse_args(argv)
    return run(
        input_dir=Path(args.input),
        output_dir=Path(args.output),
        source_root=Path(args.source_root),
    )
```

`src/grep_analyzer/__main__.py`:
```python
"""`python -m grep_analyzer` エントリ。"""

import sys

from grep_analyzer.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/integration/test_cli.py tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/cli.py src/grep_analyzer/__main__.py tests/integration/test_cli.py tests/test_smoke.py
git commit -m "feat: CLIエントリとsmoke強化"
```

---

## Task 13: golden 基盤（決定性回帰）

**Files:**
- Create: `tests/golden/conftest.py`
- Create: `tests/golden/test_golden.py`
- Create: `tests/golden/cases/java_direct/{src/A.java,input/STATUS_OK.grep,expected/STATUS_OK.tsv}`
- Create: `tests/golden/cases/c_direct/{src/m.c,input/CODE.grep,expected/CODE.tsv}`
- Create: `tests/golden/cases/proc_direct/{src/p.pc,input/X.grep,expected/X.tsv}`（Pro\*C行番号保存の必須回帰）
- Create: `tests/golden/cases/sql_direct/{src/q.sql,input/X.grep,expected/X.tsv}`
- Create: `tests/golden/cases/shell_direct/{src/run.sh,input/CODE.grep,expected/CODE.tsv}`
- Create: `tests/golden/cases/encoding_utf8/{src/jp.java,input/コード.grep,expected/コード.tsv}`（文字コード判定値 pin）

> spec §11 必須回帰のうち「言語×ref_kind 必須網羅」「Pro\*C `EXEC SQL`＋行番号保存」「文字コード期待値 pin」を Phase 1（direct のみ）で満たす。`category_sub` は空固定。**非UTF-8 の golden pin は chardet 短入力誤検出により非決定的になり得るため Phase 1 では採用せず、フォールバック決定性は Task 4 の chardet stub 済み unit で担保する**（多ホップ/host-var追跡と非UTF-8 golden 強化は Phase 2/3）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/golden/conftest.py`:
```python
"""golden ケースを自動 parametrize する（spec §11）。"""

from pathlib import Path

import pytest

CASES = sorted((Path(__file__).parent / "cases").glob("*/"))


@pytest.fixture(params=[c.name for c in CASES])
def golden_case(request):
    return Path(__file__).parent / "cases" / request.param
```

`tests/golden/test_golden.py`:
```python
"""合成代表ツリーの TSV 完全一致による回帰検出（spec §11）。"""

from grep_analyzer.pipeline import run


def test_合成ケースのTSVが期待値と完全一致する(golden_case, tmp_path):
    out = tmp_path / "out"
    rc = run(
        input_dir=golden_case / "input",
        output_dir=out,
        source_root=golden_case / "src",
    )
    assert rc == 0
    for expected in (golden_case / "expected").glob("*.tsv"):
        actual = (out / expected.name).read_text("utf-8-sig")
        assert actual == expected.read_text("utf-8-sig"), expected.name
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/golden/test_golden.py -v`
Expected: FAIL（`cases/java_direct` のファイル未作成 → 期待TSV不一致 or FileNotFound）

- [ ] **Step 3: 合成ケースと期待値を作成**

`tests/golden/cases/java_direct/src/A.java`:
```java
class A {
  static final String STATUS_OK = "STATUS_OK";
  void m(String s){
    if (s.equals("STATUS_OK")) {}
  }
}
```

`tests/golden/cases/java_direct/input/STATUS_OK.grep`:
```
A.java:2:  static final String STATUS_OK = "STATUS_OK";
A.java:4:    if (s.equals("STATUS_OK")) {}
```

`tests/golden/cases/java_direct/expected/STATUS_OK.tsv`（タブ区切り・末尾改行・UTF-8 BOM 付きで保存。下記は列順の内容）:
```
keyword	language	file	lineno	ref_kind	category	category_sub	usage_summary	via_symbol	chain	snippet	encoding	confidence
STATUS_OK	java	A.java	2	direct	宣言		宣言 (java)		STATUS_OK@A.java:2	  static final String STATUS_OK = "STATUS_OK";	utf-8	high
STATUS_OK	java	A.java	4	direct	比較		比較 (java)		STATUS_OK@A.java:4	    if (s.equals("STATUS_OK")) {}	utf-8	high
```

**追加ケース（spec §11 必須網羅・すべて direct）**

`tests/golden/cases/c_direct/src/m.c`:
```c
#define CODE "X"
int main(){ return 0; }
```
`tests/golden/cases/c_direct/input/CODE.grep`:
```
m.c:1:#define CODE "X"
```
期待 `expected/CODE.tsv`（ヘッダ＋）: `CODE	c	m.c	1	direct	宣言		宣言 (c)		CODE@m.c:1	#define CODE "X"	utf-8	high`

`tests/golden/cases/proc_direct/src/p.pc`（EXEC SQL は2〜3行目を跨ぐ。行番号保存で4行目のC宣言が lineno 4 のまま分類されることを固定）:
```c
int f(){
 EXEC SQL SELECT CODE
   INTO :x FROM t;
 char *p = "X";
}
```
`tests/golden/cases/proc_direct/input/X.grep`:
```
p.pc:4: char *p = "X";
```
期待 `expected/X.tsv`: `X	proc	p.pc	4	direct	宣言		宣言 (proc)		X@p.pc:4	 char *p = "X";	utf-8	high`

`tests/golden/cases/sql_direct/src/q.sql`:
```sql
SELECT * FROM t WHERE col = 'X';
```
`tests/golden/cases/sql_direct/input/X.grep`:
```
q.sql:1:SELECT * FROM t WHERE col = 'X';
```
期待 `expected/X.tsv`: `X	sql	q.sql	1	direct	比較		比較 (sql)		X@q.sql:1	SELECT * FROM t WHERE col = 'X';	utf-8	medium`

`tests/golden/cases/shell_direct/src/run.sh`:
```bash
CODE="X"
echo "$CODE"
```
`tests/golden/cases/shell_direct/input/CODE.grep`:
```
run.sh:1:CODE="X"
```
期待 `expected/CODE.tsv`: `CODE	shell	run.sh	1	direct	代入		代入 (shell)		CODE@run.sh:1	CODE="X"	utf-8	medium`

`tests/golden/cases/encoding_utf8/src/jp.java`（UTF-8 日本語。utf-8 厳格経路で encoding=utf-8 が決定的に固定される）:
```java
class J {
  static final String コード = "コード";
}
```
`tests/golden/cases/encoding_utf8/input/コード.grep`:
```
jp.java:2:  static final String コード = "コード";
```
期待 `expected/コード.tsv`: `コード	java	jp.java	2	direct	宣言		宣言 (java)		コード@jp.java:2	  static final String コード = "コード";	utf-8	high`

**期待TSVの確定手順（全ケース共通・spec §11「必ず git diff で目視レビューしてから regen」）**:
```bash
for c in java_direct c_direct proc_direct sql_direct shell_direct encoding_utf8; do
  python -m grep_analyzer --input "tests/golden/cases/$c/input" \
    --output "/tmp/g/$c" --source-root "tests/golden/cases/$c/src"
done
```
生成された各 `/tmp/g/<case>/*.tsv` を上表の内容と目視照合し、一致を確認できたら `expected/` に配置（diagnostics.txt は expected に含めない＝conftest は `*.tsv` のみ照合）。差異があれば実装バグなので Task 該当箇所を修正してから確定する。

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/golden/test_golden.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add tests/golden/
git commit -m "chore(golden): golden基盤と6言語direct代表ケース"
```

---

## Task 14: Phase 1 全テスト緑化と完了確認

- [ ] **Step 1: 全テスト実行**

Run: `pytest -v`
Expected: 全 PASS（unit / integration / golden / smoke）

- [ ] **Step 2: spec §15 フェーズ1 充足を確認**

`docs/superpowers/specs/2026-05-16-grep-analyzer-design.md` §15 フェーズ1 の各項目（Ingest / grep行パース / 文字コード / 言語ディスパッチ / 分類器(tree-sitter, Pro\*C行番号保存) / TSVスキーマ / golden 基盤・direct のみ完全決定性）が Task 1〜13 で実装済みであることをチェックリスト照合し、`docs/superpowers/plans/phase0-gate-result.md` に「Phase 1 完了」を追記。

- [ ] **Step 3: コミット**

```bash
git add -A
git commit -m "chore: Phase 1 完了（決定的コア・direct-only）"
```

---

## Phase 1 の境界（Phase 2 以降は別計画）

- **本計画に含まない（Phase 2: 不動点エンジン / Phase 3: 規模運用）**: 多ホップ間接追跡（§8）、シンボル採否ポリシー（§8.3）、来歴グラフ集約・並列走査・60GB走査（§8.2）、`pyahocorasick`/`ripgrep`、`--resume`原子性運用、part分割、`tests/perf/`。これらは Phase 1 完了後に spec §8/§15 を入力として別の writing-plans で計画する。
- Phase 1 の成果物は「direct参照のみを言語別分類し完全決定的TSV＋goldenを出す動くツール」であり、それ単体でテスト可能・出荷可能。
