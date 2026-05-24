# golden 現実性・堅牢性 補強 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 現行 golden ハーネス（`tests/golden/cases/`）に「汚い実コード／混在エンコーディング／バイナリ・NUL 混入」を再現する新規 6 ケースを追加し、現挙動を特性化（characterization）して回帰固定する。併せて §9 サニタイズを全制御文字へ拡張する。

**Architecture:** 設計 spec `docs/superpowers/specs/2026-05-24-golden-realism-robustness-design.md` に従う。期待値は決め打ちせず `pipeline.run` の実出力を人手レビュー後に凍結する（案A）。ハーネスに opt-in の diagnostics `# summary` 比較を追加。サニタイズは単一集約点 `tsv._SANITIZE_MAP` を拡張。

**Tech Stack:** Python 3.12 / pytest / `grep_analyzer`（`pipeline.run`）/ chardet==5.2.0（ハッシュ pin）/ git `.gitattributes`。

**重要な前提（読む前に）:**
- 現行 golden ケース数は **39**（`ls tests/golden/cases | wc -l` = 39、`pytest tests/golden -q` = 39 passed）。本プラン完了で **45**。
- 既存 39 ケースの `expected/` は**バイト不変**でなければならない（Task 2/13 で確認）。
- golden ハーネス: `tests/golden/test_golden.py` が各ケースを `tmp_path` で隔離実行し、`expected/*.tsv` を **TSV 完全一致**（`{SOURCE_ROOT}` 逆置換後）で比較。`conftest.py` が `cases/*/` を自動 parametrize。parametrize id はケースのディレクトリ名（例 `[grep_binary_nul]`）。
- 作業ブランチ: memory「main 直接作業可（ソロ）」に従い main で作業・コミット。

---

## File Structure

| ファイル | 役割 | 操作 |
|---|---|---|
| `scripts/gen_golden_case.py` | golden ケースの `expected/` を現 pipeline 出力から（再）生成する開発ツール。ハーネスの正規化を写経 | 作成 |
| `src/grep_analyzer/tsv.py` | サニタイズ集約点 `_SANITIZE_MAP` を全制御文字へ拡張 | 変更 |
| `tests/unit/test_tsv.py` | 制御文字サニタイズの回帰テスト追加 | 変更 |
| `tests/golden/test_golden.py` | opt-in の `diagnostics_summary.txt` 比較を追加 | 変更 |
| `.gitattributes` | golden を `-text`、jar を `binary` 指定 | 作成 |
| `tests/golden/cases/grep_binary_nul/**` | ③ grep 本文の生バイト堅牢性 | 作成 |
| `tests/golden/cases/grep_jar_artifact/**` | ③ ディスク上 jar＋`Binary file … matches` | 作成 |
| `tests/golden/cases/encoding_mixed_tree/**` | ② SQL 混在エンコーディングツリー | 作成 |
| `tests/golden/cases/bom_crlf_source/**` | ② BOM＋CRLF ソース | 作成 |
| `tests/golden/cases/messy_c_legacy/**` | ① 汚い C | 作成 |
| `tests/golden/cases/source_ctrl_chars/**` | ①/③ ソース行の制御文字（§7 回帰） | 作成 |
| `tests/golden/cases/README.md` | 新規ケースの characterization 注記（集約） | 作成 |
| `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md` | §9/§11 normative 反映 | 変更 |

---

## Task 1: golden 生成ヘルパ（開発ツール）

**Files:**
- Create: `scripts/gen_golden_case.py`

このヘルパは「ケースの `input/`・`src/` から `pipeline.run` を回し、ハーネスと同一の `{SOURCE_ROOT}` 正規化を施して `expected/*.tsv` を書き、必要なら `expected/diagnostics_summary.txt` を書く」。以降の全ケースが使う。正規化は `tests/golden/test_golden.py` の写し。

- [ ] **Step 1: ヘルパを作成**

```python
# scripts/gen_golden_case.py
"""golden ケースの expected/ を現 pipeline 出力から（再）生成する開発ツール。

使い方:
    python scripts/gen_golden_case.py tests/golden/cases/<case> [--with-diag-summary]

挙動: <case>/input・<case>/src で pipeline.run を回し、tests/golden/test_golden.py と
同一の {SOURCE_ROOT} 逆置換（各行先頭1回）を施して <case>/expected/*.tsv を上書きする。
--with-diag-summary 指定時は diagnostics.txt の "# summary" ブロックを
<case>/expected/diagnostics_summary.txt に書く。

注意: 生成後は必ず `git diff` で内容を人手レビューしてからコミットする（spec 案A）。
"""
import argparse
import dataclasses
import json
import tempfile
from pathlib import Path

from grep_analyzer.pipeline import _default_opts, run


def _opts_for(case: Path):
    o = _default_opts()
    cfg = case / "opts.json"
    if cfg.is_file():
        d = json.loads(cfg.read_text("utf-8"))
        repl = {k: d[k] for k in ("follow_symlinks", "output_encoding", "resume")
                if k in d}
        o = dataclasses.replace(o, **repl)
    return o


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("case")
    ap.add_argument("--with-diag-summary", action="store_true")
    args = ap.parse_args()
    case = Path(args.case)
    opts = _opts_for(case)
    out = Path(tempfile.mkdtemp(prefix="gen_golden_"))
    rc = run(input_dir=case / "input", output_dir=out,
             source_root=case / "src", opts=opts)
    assert rc == 0, f"pipeline rc={rc}"

    sr = str((case / "src").resolve())
    exp = case / "expected"
    exp.mkdir(parents=True, exist_ok=True)
    for tsv in sorted(out.glob("*.tsv")):
        mpath = out / f"{tsv.stem}.manifest.json"
        enc = "utf-8-sig"
        if mpath.is_file():
            enc = json.loads(mpath.read_text("utf-8")).get("encoding", "utf-8-sig")
        text = tsv.read_text(enc)
        text = "".join(
            (ln.replace(sr + "/", "{SOURCE_ROOT}/", 1) if (sr + "/") in ln else ln)
            for ln in text.splitlines(keepends=True))
        (exp / tsv.name).write_text(text, "utf-8-sig")
        print(f"wrote {exp / tsv.name}")

    if args.with_diag_summary:
        diag = (out / "diagnostics.txt").read_text("utf-8")
        lines, in_sum = [], False
        for ln in diag.splitlines():
            if ln == "# summary":
                in_sum = True
                continue
            if ln == "# detail":
                break
            if in_sum:
                lines.append(ln)
        (exp / "diagnostics_summary.txt").write_text("\n".join(lines) + "\n", "utf-8")
        print(f"wrote {exp / 'diagnostics_summary.txt'}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: ヘルパが import エラー無く動くことを確認（既存ケースで no-op 再生成）**

Run: `cd /workspaces/grep_helpers2 && python scripts/gen_golden_case.py tests/golden/cases/c_direct && git diff --stat tests/golden/cases/c_direct`
Expected: `wrote .../c_direct/expected/CODE.tsv` と表示され、**`git diff` に差分が出ない**（既存 expected を現出力で上書きしてもバイト一致＝ヘルパの正規化がハーネスと整合している証拠）。

- [ ] **Step 3: 確認用の再生成を破棄（差分ゼロなので何もなし）し、コミット**

```bash
git add scripts/gen_golden_case.py
git commit -m "test(golden): expected 再生成ヘルパ scripts/gen_golden_case.py を追加"
```

---

## Task 2: §9 サニタイズを全制御文字へ拡張（TDD）

**Files:**
- Test: `tests/unit/test_tsv.py`
- Modify: `src/grep_analyzer/tsv.py`

現 `_SANITIZE_MAP` は `\t\r\n\v\f` U+0085 U+2028 U+2029 のみ空白化。NUL/その他 C0/DEL/C1 が素通りし出力 TSV セルに残る（spec §9 intent 違反＝rubric R2、ユーザー判断で修正）。新集合は**現集合を包含**するため既存 expected はバイト不変。

- [ ] **Step 1: 失敗するテストを追加**

`tests/unit/test_tsv.py` の末尾に追記:

```python
def test_全制御文字を空白化_C0_DEL_C1():
    # NUL/C0制御/DEL(U+007F)/C1(U+0080-009F) はすべて半角空白へ
    src = "a\x00b\x01c\x1fd\x7fe\x80f\x9fg"
    assert sanitize_field(src) == "a b c d e f g"


def test_既存の拡張空白集合は引き続き空白化():
    # 後方互換（現集合を包含）
    assert sanitize_field("a\tb\rc\nd\x0be\x0cf\x85g h i") == \
        "a b c d e f g h i"
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest tests/unit/test_tsv.py::test_全制御文字を空白化_C0_DEL_C1 -v`
Expected: FAIL（`a\x00b...` がそのまま返り assert で不一致）

- [ ] **Step 3: `_SANITIZE_MAP` を全制御文字集合へ拡張**

`src/grep_analyzer/tsv.py` を次へ置換:

```python
"""TSV フィールドのサニタイズ規約。

全制御文字（C0 U+0000–001F / DEL U+007F / C1 U+0080–009F）と
行/改ページ分割（U+2028 U+2029）を半角空白 1 個へ置換する `sanitize_field` を
提供する。書込本体は output_writer.py。

Related: spec §9 規約①
"""

# spec §9 サニタイズ規約①: 全制御文字＋ U+2028/U+2029 を半角空白1個へ。
# 旧集合（\t \r \n \v \f U+0085 U+2028 U+2029）を包含（C0⊂新集合・U+0085 は C1）。
# split("\n")/data_sha256 の決定性コアは不変（U+000A は従来どおり空白化）。
_SANITIZE_MAP = {c: " " for c in range(0x00, 0x20)}   # C0 制御
_SANITIZE_MAP[0x7F] = " "                             # DEL
_SANITIZE_MAP.update({c: " " for c in range(0x80, 0xA0)})  # C1 制御（U+0085 含む）
_SANITIZE_MAP[0x2028] = " "                           # LINE SEPARATOR
_SANITIZE_MAP[0x2029] = " "                           # PARAGRAPH SEPARATOR


def sanitize_field(cell: str) -> str:
    """フィールド内の全制御文字・行分割クラスを空白へ置換する（spec §9）。"""
    return cell.translate(_SANITIZE_MAP)
```

- [ ] **Step 4: 単体テストが通ることを確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest tests/unit/test_tsv.py -v`
Expected: 全 PASS（新2件＋既存3件）

- [ ] **Step 5: 既存 golden がバイト不変であることを確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest tests/golden -q && git diff --stat tests/golden/cases`
Expected: `39 passed`、かつ `git diff` 差分なし（既存 fixture は C0/C1 を含まないため expected 不変）

- [ ] **Step 6: コミット**

```bash
git add src/grep_analyzer/tsv.py tests/unit/test_tsv.py
git commit -m "fix(tsv): サニタイズを全制御文字(C0/DEL/C1)へ拡張 — 出力TSVへの生バイト混入を防止(spec §9)"
```

---

## Task 3: ハーネスに opt-in diagnostics summary 比較を追加

**Files:**
- Modify: `tests/golden/test_golden.py`

`expected/diagnostics_summary.txt` が存在するケースのみ、生成 `diagnostics.txt` の `# summary` ブロックを完全一致比較する。既存 39 ケースは当該ファイル不在ゆえ無影響。

- [ ] **Step 1: 比較ロジックを追加**

`tests/golden/test_golden.py` の `test_合成ケースのTSVが期待値と完全一致する` 内、TSV 比較ループ（`for expected in sorted(...)` ブロック）の**直後**、`cfg = golden_case / "opts.json"` 行の**直前**に挿入:

```python
    exp_sum = golden_case / "expected" / "diagnostics_summary.txt"
    if exp_sum.is_file():                                 # spec §11 opt-in
        diag_text = (out / "diagnostics.txt").read_text("utf-8")
        lines, in_sum = [], False
        for ln in diag_text.splitlines():
            if ln == "# summary":
                in_sum = True
                continue
            if ln == "# detail":
                break
            if in_sum:
                lines.append(ln)
        actual_sum = "\n".join(lines) + "\n"
        assert actual_sum == exp_sum.read_text("utf-8"), "diagnostics_summary.txt"
```

- [ ] **Step 2: 既存 39 ケースに無影響なことを確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest tests/golden -q`
Expected: `39 passed`（`diagnostics_summary.txt` を持つケースがまだ無いため挙動不変）

- [ ] **Step 3: コミット**

```bash
git add tests/golden/test_golden.py
git commit -m "test(golden): expected/diagnostics_summary.txt 存在時に #summary ブロックを比較(opt-in・spec §11)"
```

---

## Task 4: `.gitattributes` で golden を保護

**Files:**
- Create: `.gitattributes`

- [ ] **Step 1: `.gitattributes` を作成**

```
# golden はバイト完全一致の資産。eol 正規化を一切受けない（expected の BOM/CRLF/
# 混在エンコーディング/バイナリ src を保護）。spec §11 / 設計 2026-05-24。
tests/golden/cases/**                                 -text
tests/golden/cases/grep_jar_artifact/src/lib/app.jar  binary
```

- [ ] **Step 2: 適用後も既存 golden が通ることを確認**

Run: `cd /workspaces/grep_helpers2 && git check-attr -a tests/golden/cases/java_direct/expected/CODE.tsv`
Expected: `text: unset`（`-text` が効いている）

- [ ] **Step 3: コミット**

```bash
git add .gitattributes
git commit -m "build: .gitattributes で golden を -text 化・jar を binary 指定(再現性保護)"
```

---

## Task 5: ケース `grep_binary_nul`（③ grep 本文の生バイト堅牢性）

**Files:**
- Create: `tests/golden/cases/grep_binary_nul/src/m.c`
- Create: `tests/golden/cases/grep_binary_nul/input/777.grep`
- Create: `tests/golden/cases/grep_binary_nul/expected/777.tsv`（生成）
- Create: `tests/golden/cases/grep_binary_nul/expected/diagnostics_summary.txt`（生成）

固定対象: grep 本文に生バイトがあっても `rc=0`・正常 hit は TSV 化・コロン無し行は `bad_grep_line`。

- [ ] **Step 1: fixture を byte-exact に作成**

```bash
cd /workspaces/grep_helpers2 && python - <<'PY'
from pathlib import Path
base = Path("tests/golden/cases/grep_binary_nul")
(base/"src").mkdir(parents=True, exist_ok=True)
(base/"input").mkdir(parents=True, exist_ok=True)
(base/"src/m.c").write_text(
    'int main(void){\n'
    '  const char *CODE = "777";\n'
    '  return CODE[0];\n'
    '}\n')
g  = b'm.c:2:  const char *CODE = "777";\n'          # 正常 hit
g += b'm.c:3:\x00\xff\xfe 777 binary\x01\n'          # 有効prefix＋生バイト content → parse成功(hit化)
g += b'\x00\x00\x00 binary noise without colon \xff\xfe\n'  # コロン無し → bad_grep_line
(base/"input/777.grep").write_bytes(g)
print("fixtures written")
PY
```

- [ ] **Step 2: expected を生成して人手レビュー**

Run: `cd /workspaces/grep_helpers2 && python scripts/gen_golden_case.py tests/golden/cases/grep_binary_nul --with-diag-summary`
レビュー基準（rubric 適用）:
- `expected/777.tsv` に **2 行**（`m.c:2` と `m.c:3` の direct hit）＋ヘッダ。`file` 列が `{SOURCE_ROOT}/m.c`。生 NUL/制御バイトが**セルに残っていない**（残っていれば Task 2 未適用＝バグ）。
- `expected/diagnostics_summary.txt` に `bad_grep_line\t1` を含む（コロン無し行が 1 件）。
- 確認: `cat -v tests/golden/cases/grep_binary_nul/expected/777.tsv | sed -n '1,5p'` で生バイトが無いこと。

- [ ] **Step 3: 当該ケースの golden テストが通ることを確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest "tests/golden/test_golden.py::test_合成ケースのTSVが期待値と完全一致する[grep_binary_nul]" -v`
Expected: PASS

- [ ] **Step 4: コミット**

```bash
git add tests/golden/cases/grep_binary_nul
git commit -m "test(golden): grep_binary_nul — grep本文の生バイト/NULでも落ちず正常hitのみ抽出(③)"
```

---

## Task 6: ケース `grep_jar_artifact`（③ ディスク上 jar ＋ Binary file 行）

**Files:**
- Create: `tests/golden/cases/grep_jar_artifact/src/Main.java`
- Create: `tests/golden/cases/grep_jar_artifact/src/lib/app.jar`（本物の小 jar）
- Create: `tests/golden/cases/grep_jar_artifact/input/777.grep`
- Create: `tests/golden/cases/grep_jar_artifact/expected/777.tsv`（生成）
- Create: `tests/golden/cases/grep_jar_artifact/expected/diagnostics_summary.txt`（生成）

固定対象: `rc=0`・TSV は正常 hit のみ・`bad_grep_line`(Binary file 行)＋`walk_skipped_binary`(jar)。ユーザー要望の現実シナリオ。

- [ ] **Step 1: fixture を byte-exact に作成（jar は決定的に生成）**

```bash
cd /workspaces/grep_helpers2 && python - <<'PY'
import zipfile
from pathlib import Path
base = Path("tests/golden/cases/grep_jar_artifact")
(base/"src/lib").mkdir(parents=True, exist_ok=True)
(base/"input").mkdir(parents=True, exist_ok=True)
(base/"src/Main.java").write_text(
    'public class Main {\n'
    '  // 777\n'
    '  String code = "777";\n'
    '}\n')
# 本物の小 jar(=ZIP)。class magic + NUL を含むため walk がバイナリ判定する。
# date_time 固定で再現的バイト列。STORED で平文を保持。
jar = base/"src/lib/app.jar"
with zipfile.ZipFile(jar, "w", zipfile.ZIP_STORED) as z:
    zi = zipfile.ZipInfo("META-INF/MANIFEST.MF", date_time=(2020,1,1,0,0,0))
    z.writestr(zi, b"Manifest-Version: 1.0\n")
    zc = zipfile.ZipInfo("Main.class", date_time=(2020,1,1,0,0,0))
    z.writestr(zc, b'\xca\xfe\xba\xbe\x00\x00\x00\x34 code 777 blob\x00')
g  = b'Main.java:2:  // 777\n'
g += b'Main.java:3:  String code = "777";\n'
g += b'Binary file lib/app.jar matches\n'   # GNU grep 標準のバイナリ一致行(行番号なし)
(base/"input/777.grep").write_bytes(g)
print("fixtures written; jar bytes:", jar.stat().st_size)
PY
```

- [ ] **Step 2: expected を生成して人手レビュー**

Run: `cd /workspaces/grep_helpers2 && python scripts/gen_golden_case.py tests/golden/cases/grep_jar_artifact --with-diag-summary`
レビュー基準:
- `expected/777.tsv` に **2 行**（`Main.java:2` = その他/コメント、`Main.java:3` = 宣言）。`lib/app.jar` を指す行は**無い**（Binary file 行は hit 化されない）。
- `expected/diagnostics_summary.txt` に `bad_grep_line\t1` と `walk_skipped_binary\t1` を含む。

- [ ] **Step 3: 当該ケースの golden テストが通ることを確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest "tests/golden/test_golden.py::test_合成ケースのTSVが期待値と完全一致する[grep_jar_artifact]" -v`
Expected: PASS

- [ ] **Step 4: コミット**

```bash
git add tests/golden/cases/grep_jar_artifact
git commit -m "test(golden): grep_jar_artifact — src内jar走査除外＋Binary file行のbad_grep_line化(③)"
```

---

## Task 7: ケース `encoding_mixed_tree`（② SQL 混在エンコーディングツリー）

**Files:**
- Create: `tests/golden/cases/encoding_mixed_tree/src/utf8_q.sql`（UTF-8）
- Create: `tests/golden/cases/encoding_mixed_tree/src/cp932_q.sql`（CP932）
- Create: `tests/golden/cases/encoding_mixed_tree/src/eucjp_q.sql`（EUC-JP）
- Create: `tests/golden/cases/encoding_mixed_tree/input/777.grep`（ASCII）
- Create: `tests/golden/cases/encoding_mixed_tree/expected/777.tsv`（生成）

固定対象: `encoding` 列がファイル毎に出る（**実 run 値を凍結**。chardet 検出名は `shift_jis` 等に揺れ得るため決め打ちしない）。分類は ASCII signal で頑健。

- [ ] **Step 1: fixture を byte-exact に作成（各ファイルを別エンコーディングで書く）**

```bash
cd /workspaces/grep_helpers2 && python - <<'PY'
from pathlib import Path
base = Path("tests/golden/cases/encoding_mixed_tree")
(base/"src").mkdir(parents=True, exist_ok=True)
(base/"input").mkdir(parents=True, exist_ok=True)
# 日本語コメントで chardet 検出を働かせる。ヒット行(3行目)は純ASCII。
body = (
    "-- ステータスコードのマスタ参照クエリ\n"
    "-- 日本語コメント行を増やして文字コード検出を安定させる目的\n"
    "SELECT name FROM master WHERE code = '777';\n")
(base/"src/utf8_q.sql").write_bytes(body.encode("utf-8"))
(base/"src/cp932_q.sql").write_bytes(body.encode("cp932"))
(base/"src/eucjp_q.sql").write_bytes(body.encode("euc-jp"))
# grep のヒット行は純ASCII＝grep ファイルは単一エンコーディング(ASCII)で済む。
g = ("utf8_q.sql:3:SELECT name FROM master WHERE code = '777';\n"
     "cp932_q.sql:3:SELECT name FROM master WHERE code = '777';\n"
     "eucjp_q.sql:3:SELECT name FROM master WHERE code = '777';\n")
(base/"input/777.grep").write_bytes(g.encode("ascii"))
print("fixtures written")
PY
```

- [ ] **Step 2: expected を生成して人手レビュー**

Run: `cd /workspaces/grep_helpers2 && python scripts/gen_golden_case.py tests/golden/cases/encoding_mixed_tree`
レビュー基準（rubric R3 適用）:
- `expected/777.tsv` に **3 行**（各 SQL ファイルの 3 行目 direct hit）。
- `encoding` 列が**3 ファイルで異なる値**になっている（例 `utf-8` / `cp932` または `shift_jis` / `euc-jp`）。**実出力をそのまま凍結**する（検出名が想定と違っても rubric R3＝chardet 仕様として README に記録）。
- 分類（category）はファイル間で一致（ASCII signal `WHERE`/`=` 由来で化けに非依存）。
- 確認: `cut -f2,3,4,12 tests/golden/cases/encoding_mixed_tree/expected/777.tsv`（language/file/lineno/encoding 列）で 3 エンコーディングが出ること。

- [ ] **Step 3: 当該ケースの golden テストが通ることを確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest "tests/golden/test_golden.py::test_合成ケースのTSVが期待値と完全一致する[encoding_mixed_tree]" -v`
Expected: PASS

- [ ] **Step 4: コミット**

```bash
git add tests/golden/cases/encoding_mixed_tree
git commit -m "test(golden): encoding_mixed_tree — 1ツリーにUTF-8/CP932/EUC-JP同居・encoding列をファイル毎に固定(②)"
```

---

## Task 8: ケース `bom_crlf_source`（② BOM＋CRLF ソース）

**Files:**
- Create: `tests/golden/cases/bom_crlf_source/src/win.c`（UTF-8 BOM＋CRLF）
- Create: `tests/golden/cases/bom_crlf_source/input/777.grep`
- Create: `tests/golden/cases/bom_crlf_source/expected/777.tsv`（生成）

固定対象: 先頭 BOM が行番号を壊さない。CR は除去でなく**空白化**される（§7 後）現挙動を凍結。

- [ ] **Step 1: fixture を byte-exact に作成**

```bash
cd /workspaces/grep_helpers2 && python - <<'PY'
from pathlib import Path
base = Path("tests/golden/cases/bom_crlf_source")
(base/"src").mkdir(parents=True, exist_ok=True)
(base/"input").mkdir(parents=True, exist_ok=True)
# 先頭 UTF-8 BOM ＋ 全行 CRLF。ヒットは 3 行目(777)。
text = ("#include <stdio.h>\r\n"
        "int main(void){\r\n"
        "  int x = 777;\r\n"
        "  return x;\r\n"
        "}\r\n")
(base/"src/win.c").write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
# grep のヒット行も CRLF を温存(parse_grep_line が rstrip するので content から \r は消える)。
g = b"win.c:3:  int x = 777;\r\n"
(base/"input/777.grep").write_bytes(g)
print("fixtures written")
PY
```

- [ ] **Step 2: expected を生成して人手レビュー**

Run: `cd /workspaces/grep_helpers2 && python scripts/gen_golden_case.py tests/golden/cases/bom_crlf_source`
レビュー基準:
- `expected/777.tsv` に **1 行**（`win.c:3` direct 宣言）。行番号が 3（BOM が行をずらしていない）。
- `snippet` 列に生 `\r` が無い（CR→空白化済。末尾に空白が付き得る＝現挙動として凍結）。
- 確認: `cat -v tests/golden/cases/bom_crlf_source/expected/777.tsv` で `^M`(CR) や BOM 文字が snippet セルに無いこと。

- [ ] **Step 3: 当該ケースの golden テストが通ることを確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest "tests/golden/test_golden.py::test_合成ケースのTSVが期待値と完全一致する[bom_crlf_source]" -v`
Expected: PASS

- [ ] **Step 4: コミット**

```bash
git add tests/golden/cases/bom_crlf_source
git commit -m "test(golden): bom_crlf_source — 先頭BOM/CRLFが行番号・snippetを壊さない挙動を固定(②)"
```

---

## Task 9: ケース `messy_c_legacy`（① 汚い C）

**Files:**
- Create: `tests/golden/cases/messy_c_legacy/src/legacy.c`
- Create: `tests/golden/cases/messy_c_legacy/input/777.grep`
- Create: `tests/golden/cases/messy_c_legacy/expected/777.tsv`（生成）

固定対象: 乱雑入力（タブ/行末空白/深ネスト/多文1行/コメントアウト/ブロックコメント）での分類と snippet サニタイズ。

- [ ] **Step 1: fixture を byte-exact に作成（タブ・行末空白を含む）**

```bash
cd /workspaces/grep_helpers2 && python - <<'PY'
from pathlib import Path
base = Path("tests/golden/cases/messy_c_legacy")
(base/"src").mkdir(parents=True, exist_ok=True)
(base/"input").mkdir(parents=True, exist_ok=True)
# 行番号を固定するため明示的に列挙。\t=タブ、行末に空白を残す行あり。
lines = [
    "/* legacy 777 handler - see ticket #777 */",      # 1: ブロックコメント中の 777 x2
    "int\tproc(int x){",                                # 2: タブ・ヒット無し
    "\tif (x == 777) {        /* 777 check */",         # 3: タブ深ネスト＋777 x2
    "\t\tint a=1; int b=777; int c=3;",                 # 4: 多文1行＋777
    "\t\treturn b;",                                    # 5
    "\t}",                                              # 6
    "\t// dead: int old = 777;",                        # 7: コメントアウトされたコード
    "\treturn 0;   ",                                   # 8: 行末空白(ヒット無し)
    "}",                                                # 9
]
(base/"src/legacy.c").write_text("\n".join(lines) + "\n")
# grep -rn 777 legacy.c 相当（1,3,4,7 行が 777 を含む）。content はソースそのまま。
g = (
    "legacy.c:1:/* legacy 777 handler - see ticket #777 */\n"
    "legacy.c:3:\tif (x == 777) {        /* 777 check */\n"
    "legacy.c:4:\t\tint a=1; int b=777; int c=3;\n"
    "legacy.c:7:\t// dead: int old = 777;\n")
(base/"input/777.grep").write_bytes(g.encode("utf-8"))
print("fixtures written")
PY
```

- [ ] **Step 2: expected を生成して人手レビュー**

Run: `cd /workspaces/grep_helpers2 && python scripts/gen_golden_case.py tests/golden/cases/messy_c_legacy`
レビュー基準:
- `expected/777.tsv` に **4 行**（1,3,4,7 行目）。
- `snippet` 列でタブが**空白化**されている（生 `\t` が無い）。
- 各行の `category` が現挙動として妥当（1/7=その他＝コメント、3=条件判定、4=変数代入 などになる想定。違っても rubric R3 で実出力を凍結し README に記録）。
- 確認: `cat -v tests/golden/cases/messy_c_legacy/expected/777.tsv` で `^I`(タブ＝セル区切り以外)が snippet 内に無いこと。

- [ ] **Step 3: 当該ケースの golden テストが通ることを確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest "tests/golden/test_golden.py::test_合成ケースのTSVが期待値と完全一致する[messy_c_legacy]" -v`
Expected: PASS

- [ ] **Step 4: コミット**

```bash
git add tests/golden/cases/messy_c_legacy
git commit -m "test(golden): messy_c_legacy — タブ/深ネスト/多文1行/コメントアウトの乱雑Cの分類とsnippetを固定(①)"
```

---

## Task 10: ケース `source_ctrl_chars`（①/③ ソース行の制御文字 — §7 回帰）

**Files:**
- Create: `tests/golden/cases/source_ctrl_chars/src/ctrl.c`
- Create: `tests/golden/cases/source_ctrl_chars/input/777.grep`
- Create: `tests/golden/cases/source_ctrl_chars/expected/777.tsv`（生成）

固定対象: ソース行に NUL/C0/DEL が混入しても、Task 2 のサニタイズ拡張により**全制御文字が空白へ正規化**され出力 TSV に生バイトが残らない。**Task 2（§7）が必須前提。**

- [ ] **Step 1: fixture を byte-exact に作成（ソースに NUL/C0/DEL を埋込）**

```bash
cd /workspaces/grep_helpers2 && python - <<'PY'
from pathlib import Path
base = Path("tests/golden/cases/source_ctrl_chars")
(base/"src").mkdir(parents=True, exist_ok=True)
(base/"input").mkdir(parents=True, exist_ok=True)
# 2 行目の文字列リテラルに生 NUL/C0/DEL を混入(バイナリ片混入の旧資産想定)。
# NUL/C0/DEL は valid UTF-8(<=U+007F) なので decode は utf-8 成功(置換なし)。
ln2 = b'  char *CODE = "777\x00\x01\x1f\x7f junk";'
src  = b'int main(void){\n' + ln2 + b'\n  return 0;\n}\n'
(base/"src/ctrl.c").write_bytes(src)
# grep のヒット行(2 行目)。content にも同じ生バイトを含む(grep -a 相当)。
g = b'ctrl.c:2:' + ln2 + b'\n'
(base/"input/777.grep").write_bytes(g)
print("fixtures written")
PY
```

- [ ] **Step 2: expected を生成して人手レビュー**

Run: `cd /workspaces/grep_helpers2 && python scripts/gen_golden_case.py tests/golden/cases/source_ctrl_chars`
レビュー基準（rubric 適用＝Task 2 が効いている証拠）:
- `expected/777.tsv` に **1 行**（`ctrl.c:2` direct）。
- `snippet` 列に**生バイトが一切無い**（NUL/`\x01`/`\x1f`/`\x7f` が**空白化**され `"777    junk"` のようになる）。**生 NUL が残っていたら Task 2 未適用＝即修正**。
- 確認: `python -c "import pathlib; b=pathlib.Path('tests/golden/cases/source_ctrl_chars/expected/777.tsv').read_bytes(); print('has NUL:', b'\x00' in b, '| has DEL:', b'\x7f' in b)"` → 両方 `False`。

- [ ] **Step 3: 当該ケースの golden テストが通ることを確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest "tests/golden/test_golden.py::test_合成ケースのTSVが期待値と完全一致する[source_ctrl_chars]" -v`
Expected: PASS

- [ ] **Step 4: コミット**

```bash
git add tests/golden/cases/source_ctrl_chars
git commit -m "test(golden): source_ctrl_chars — ソース行のNUL/C0/DELが空白化され生バイトがTSVに残らない(§7回帰・①③)"
```

---

## Task 11: 本体 spec へ normative 反映（§9 / §11）

**Files:**
- Modify: `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`

memory「確定設計は spec が正本」に従い、実装に合わせて 2 点追記する。

- [ ] **Step 1: §9 サニタイズ規約①の対象集合を更新**

`docs/superpowers/specs/2026-05-16-grep-analyzer-design.md` 内、§9 サニタイズ規約①の記述（`\t` `\r` `\n` `\v` `\f` `U+0085` `U+2028` `U+2029` を半角空白へ、という箇所＝238 行目付近「サニタイズ規約（v9・全セル共通…」）に、次の一文を追記する:

```
（2026-05-24 改訂）空白化対象を「全制御文字（C0 U+0000–U+001F／DEL U+007F／C1 U+0080–U+009F）＋ U+2028 ＋ U+2029」へ拡張する。旧列挙（\t \r \n \v \f U+0085 U+2028 U+2029）を包含し、決定性アルゴリズムは不変・対象文字集合のみ拡張（出力 TSV セルへの生制御バイト混入を防止＝「1 セルを保つ」intent の完全化）。回帰は §11 `source_ctrl_chars`。
```

- [ ] **Step 2: §11 に diagnostics summary 比較を追記**

§11（golden 比較機構）の記述に、次の一文を追記する:

```
（2026-05-24 追加）`expected/diagnostics_summary.txt` が存在するケースは、生成 `diagnostics.txt` の `# summary` ブロック（カテゴリ＋件数）のみを完全一致比較する（opt-in。不在ケースは TSV のみ＝現行不変）。detail は決定的だが `repr` 焼き込み・detail_limit 件数依存で脆いため比較対象外。バイナリ/堅牢系ケース（`grep_binary_nul` / `grep_jar_artifact`）が使用。
```

- [ ] **Step 3: spec に矛盾が無いか確認（目視）し、コミット**

Run: `cd /workspaces/grep_helpers2 && git diff docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`
Expected: §9・§11 に上記 2 段落が入っていること。

```bash
git add docs/superpowers/specs/2026-05-16-grep-analyzer-design.md
git commit -m "docs(spec): §9 サニタイズを全制御文字へ拡張・§11 に diagnostics summary 比較を normative 追記"
```

---

## Task 12: characterization 注記の集約 README

**Files:**
- Create: `tests/golden/cases/README.md`

per-case README は既存 39 ケースと非対称になるため、新規 6 ケースの注記を 1 枚に集約する。

- [ ] **Step 1: README を作成**

```markdown
# golden ケース characterization 注記（2026-05-24 追加分）

設計: `docs/superpowers/specs/2026-05-24-golden-realism-robustness-design.md`。
期待値は `pipeline.run` の実出力を人手レビュー後に凍結（案A）。再生成は
`python scripts/gen_golden_case.py tests/golden/cases/<case> [--with-diag-summary]`。

| ケース | 懸念 | 固定する挙動 | rubric / 注記 |
|---|---|---|---|
| `grep_binary_nul` | ③ | grep 本文の生バイト/NUL でも rc=0・正常 hit のみ・コロン無し行は bad_grep_line | summary 比較あり |
| `grep_jar_artifact` | ③ | src 内 jar を walk 除外・`Binary file … matches` 行を bad_grep_line 化 | summary 比較あり。jar は決定的生成（date_time 固定） |
| `encoding_mixed_tree` | ② | 1 ツリーに UTF-8/CP932/EUC-JP 同居・encoding 列がファイル毎に出る | **R3**: encoding 名は chardet==5.2.0 のアーティファクト。CP932 は内容次第で `cp932`/`shift_jis` 等に揺れるため決め打ちせず実出力を凍結。lock 変更時は本ケース再生成 |
| `bom_crlf_source` | ② | 先頭 BOM が行番号を壊さない・CR は空白化される | R3: CR は「除去」でなく空白化（末尾空白が付き得る） |
| `messy_c_legacy` | ① | 乱雑 C（タブ/深ネスト/多文1行/コメントアウト）の分類と snippet サニタイズ | R3: 分類は現挙動を凍結 |
| `source_ctrl_chars` | ①/③ | ソース行の NUL/C0/DEL が空白化され生バイトが TSV に残らない | **R2→修正済**: §7 サニタイズ拡張の回帰テスト（spec §9 改訂） |
```

- [ ] **Step 2: コミット**

```bash
git add tests/golden/cases/README.md
git commit -m "docs(golden): 新規6ケースの characterization 注記を集約 README に記載"
```

---

## Task 13: 最終検証

**Files:** なし（検証のみ）

- [ ] **Step 1: golden 全体が通る（45 件）**

Run: `cd /workspaces/grep_helpers2 && python -m pytest tests/golden -q`
Expected: `45 passed`

- [ ] **Step 2: 既存 39 ケースの expected がバイト不変**

Run: `cd /workspaces/grep_helpers2 && git status --porcelain tests/golden/cases | grep -v '^??' ; echo "---(変更行が無ければ既存不変)---"`
Expected: 既存ケース（新規6以外）の `expected/*.tsv` に変更（` M `）が出ない。新規6ケースは未追跡（`??`）または追加済。

- [ ] **Step 3: ユニット・全体テストが通る**

Run: `cd /workspaces/grep_helpers2 && python -m pytest -q`
Expected: 全 PASS（既存＋新規）

- [ ] **Step 4: 新規バイナリ fixture の git 属性が効いている**

Run: `cd /workspaces/grep_helpers2 && git check-attr -a tests/golden/cases/grep_jar_artifact/src/lib/app.jar tests/golden/cases/source_ctrl_chars/src/ctrl.c`
Expected: jar は `binary`（text: unset, diff: unset）、ctrl.c は `text: unset`（`-text`）。

---

## Self-Review（プラン作成者による点検結果）

- **Spec coverage:** 設計 §4（6 ケース）→ Task 5–10。§5（harness）→ Task 3。§6（.gitattributes）→ Task 4。§7（sanitize）→ Task 2。§8（spec 反映）→ Task 11。§9（検証）→ Task 13。§10（README）→ Task 12。生成手段（案A）→ Task 1。全要件にタスク対応あり。
- **依存順序:** Task 2（§7）→ Task 10（source_ctrl_chars が依存）。Task 3（harness）→ Task 5/6（summary 比較を使用）。Task 1（生成ヘルパ）→ Task 5 以降。順序維持必須。
- **Placeholder scan:** 各ケースの `expected` は characterization のため Task 1 のヘルパで生成し人手レビュー後に凍結する（プレースホルダではなく生成手順＋レビュー基準を明示）。fixture バイトは全タスクで具体化済。
- **Type/名称整合:** `gen_golden_case.py` の CLI（`--with-diag-summary`）、`_SANITIZE_MAP`、`diagnostics_summary.txt`、parametrize id（ケース名）はタスク間で一貫。
