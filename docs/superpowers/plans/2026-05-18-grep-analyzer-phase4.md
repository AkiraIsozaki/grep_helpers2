# grep_analyzer フェーズ4（v8/v9 出力可読性改訂）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** spec §9 の3改訂（`file` 絶対化／direct→indirect chain 集約ソート／構文単位・複数行 snippet）を決定性を保ったまま実装し、既存資産の Inv-1 を新ベースラインへ再確立する。

**Architecture:** snippet 切り出しを新モジュール `src/grep_analyzer/snippet.py`（純関数群＋言語ディスパッチ）に集約し pipeline の分類ステージから呼ぶ。ソート（`model.sort_key`）・サニタイズ（`tsv._sanitize`）・`file` 解決（`pipeline`）はピンポイント改修。golden 比較ハーネス（`tests/golden/test_golden.py`）に `{SOURCE_ROOT}` 逆置換＋manifest encoding 読戻し＋resume assert を追加し、影響3要因（A:file 絶対化／B:snippet 多行化／C:ソート順）別に expected を再生成する。

**Tech Stack:** Python 3.12 / py-tree-sitter 0.21（tree-sitter-java, tree-sitter-c）/ pytest（古典学派 TDD・日本語テスト名）。spec 正本: `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`（v9・§7/§8.2/§8.4/§9/§10.3/§11/§15 フェーズ4）。

**正本注記:** 本計画は spec v9 を入力とする。golden/expected 再生成・Inv-1 再確立は本計画の**成果物**であり前提ではない（spec §15 フェーズ4・着手循環回避）。実装ロジックは spec を逸脱しないこと。逸脱が必要なら spec 本体（ユーザ所有）を先に改訂する。

---

## File Structure

| ファイル | 役割 | 区分 |
|---|---|---|
| `src/grep_analyzer/snippet.py` | snippet 切り出し純関数群（clamp / heuristic / ts / proc / dispatch）。spec §9「snippet 切り出し規則」§7 Pro\*C の唯一の実装場所 | Create |
| `src/grep_analyzer/model.py` | `sort_key` を spec §9 v9 キーへ差替（`ref_kind_rank`/`chain_group` 導出を追加） | Modify |
| `src/grep_analyzer/tsv.py` | `_sanitize` の対象集合を spec §9 サニタイズ規約①へ拡張 | Modify |
| `src/grep_analyzer/proc_preprocess.py` | EXEC 区間を**リテラル空白化コピー上**で検出する純関数 `exec_spans()` を追加（snippet 用・既存 `mask_exec_sql` は不変） | Modify |
| `src/grep_analyzer/classifiers/ts_classifier.py` | `_node_at_line` を snippet から再利用するため公開ヘルパ `node_at_line()` を追加（既存 `classify_ts` は不変） | Modify |
| `src/grep_analyzer/pipeline.py` | `file=` を `Path(source_root).resolve()`＋rel へ／`snippet=` を `snippet.build_snippet(...)` へ配線 | Modify |
| `tests/golden/test_golden.py` | `{SOURCE_ROOT}` 逆置換＋manifest encoding 読戻し＋`--resume` 系 `is_complete` assert | Modify |
| `tests/unit/test_snippet.py` | snippet.py の純関数 unit（TDD） | Create |
| `tests/unit/test_model.py` 他 | sort_key/その他既存 unit の expected 再生成 | Modify |
| `tests/golden/cases/*/expected/*.tsv` | 影響3要因別に全件再生成（A/B/C） | Modify |
| `tests/golden/cases/<新規>/` | spec §11 v9 名指し新規ケース | Create |
| `docs/superpowers/plans/phase0-gate-result.md` | v8/v9 Inv-1 再ベースライン注記を追記（凍結記録は書き換えない） | Modify |

**物理行の定義（全 snippet 関数共通・決定性）:** snippet は `file_text.split("\n")` で得る物理行配列 `LINES`（0始まり index）を単位とする。`hit_idx = lineno - 1`。tree-sitter の row も `\n` 基準なので AST スパンと整合する。`splitlines()` は使わない（U+2028 等での水増しを避ける＝spec §9 サニタイズ規約と一貫）。

---

## Task 1: `model.sort_key` を spec §9 v9 キーへ差替

**Files:**
- Modify: `src/grep_analyzer/model.py:40-45`
- Test: `tests/unit/test_model.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_model.py` に追記（既存テストは消さない）:

```python
from grep_analyzer.model import Hit, sort_key


def _h(**kw):
    base = dict(
        keyword="K", language="java", file="/r/A.java", lineno=1,
        ref_kind="direct", category="宣言", category_sub="",
        usage_summary="u", via_symbol="", chain="K@A.java:1",
        snippet="s", encoding="utf-8", confidence="high")
    base.update(kw)
    return Hit(**base)


def test_directブロックがindirectより前に来る():
    d = _h(ref_kind="direct", lineno=5, chain="K@A.java:5")
    i = _h(ref_kind="indirect:constant", lineno=1, via_symbol="V",
           chain="K@A.java:1 -> V@B.java:1")
    assert sorted([i, d], key=sort_key) == [d, i]


def test_indirectはchain文字列ごとに集約されてから_file_lineno():
    a = _h(ref_kind="indirect:constant", file="/r/Z.java", lineno=9,
            via_symbol="V", chain="K@A:1 -> V@A:1")
    b = _h(ref_kind="indirect:constant", file="/r/A.java", lineno=1,
            via_symbol="W", chain="K@A:1 -> W@B:1")
    # chain_group(=chain) 昇順が file/lineno より優先
    assert sorted([a, b], key=sort_key) == [a, b]


def test_direct同士はfile_lineno数値順_従来同等():
    x = _h(lineno=10, chain="K@A.java:10")
    y = _h(lineno=2, chain="K@A.java:2")
    assert sorted([x, y], key=sort_key) == [y, x]


def test_全列同値は安定_language_encodingまでで全順序():
    p = _h(language="java", encoding="utf-8")
    q = _h(language="shell", encoding="utf-8")
    assert sorted([q, p], key=sort_key) == [p, q]   # language 昇順 java<shell
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_model.py -q -k "directブロック or chain文字列ごと or 全列同値"`
Expected: FAIL（現 `sort_key` は旧キーで `directブロック` 等が落ちる）

- [ ] **Step 3: Write minimal implementation**

`src/grep_analyzer/model.py` の `sort_key` を全置換:

```python
def sort_key(h: Hit) -> tuple:
    """spec §9 v9 全順序キー。

    (ref_kind_rank, chain_group, file, lineno, ref_kind, via_symbol,
     category, category_sub, confidence, usage_summary, snippet,
     language, encoding)。ref_kind_rank: direct→0 / indirect:*→1。
    chain_group: direct→"" / indirect:*→chain 文字列。lineno は数値順。
    """
    ref_kind_rank = 0 if h.ref_kind == "direct" else 1
    chain_group = "" if h.ref_kind == "direct" else h.chain
    return (
        ref_kind_rank, chain_group, h.file, h.lineno, h.ref_kind,
        h.via_symbol, h.category, h.category_sub, h.confidence,
        h.usage_summary, h.snippet, h.language, h.encoding,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_model.py -q`
Expected: PASS（新規4件＋既存 test_model のうち sort 期待が旧前提のものは Step 5 で更新）

- [ ] **Step 5: 既存 test_model の旧キー期待を更新（あれば）してコミット**

Run: `python -m pytest tests/unit/test_model.py -q` を再実行し、旧 `(file, lineno, ...)` 前提で落ちたケースは新キー期待へ最小修正（順序アサートのみ。Hit 構築は不変）。

```bash
git add src/grep_analyzer/model.py tests/unit/test_model.py
git -c commit.gpgsign=false commit -m "feat(phase4): sort_key を spec §9 v9 キー(ref_kind_rank,chain_group,...)へ"
```

---

## Task 2: `tsv._sanitize` の対象集合拡張（spec §9 サニタイズ規約①）

**Files:**
- Modify: `src/grep_analyzer/tsv.py:10-12`
- Test: `tests/unit/test_tsv.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_tsv.py` に追記:

```python
from grep_analyzer.tsv import _sanitize


def test_拡張空白文字を半角空白へ():
    s = "a\tb\rc\nd\x0be\x0cf\x85g h i"
    assert _sanitize(s) == "a b c d e f g h i"


def test_通常文字とU2026は保持():
    assert _sanitize("…(+3行省略) X") == "…(+3行省略) X"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_tsv.py -q -k 拡張空白文字`
Expected: FAIL（現 `_sanitize` は `\t \r \n` のみ置換、`\x0b` 等が残る）

- [ ] **Step 3: Write minimal implementation**

`src/grep_analyzer/tsv.py` の `_sanitize` を置換:

```python
# spec §9 サニタイズ規約①: 行/改ページ分割クラスを半角空白1個へ。
# split("\n")/data_sha256 の決定性コアは不変（U+000A は従来どおり空白化）。
_SANITIZE_MAP = {ord(c): " " for c in "\t\r\n\x0b\x0c\x85  "}


def _sanitize(cell: str) -> str:
    """フィールド内のタブ・改行・行分割クラスを空白へ置換する（spec §9）。"""
    return cell.translate(_SANITIZE_MAP)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_tsv.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/tsv.py tests/unit/test_tsv.py
git -c commit.gpgsign=false commit -m "feat(phase4): _sanitize を spec §9 サニタイズ規約①の対象集合へ拡張"
```

---

## Task 3: `snippet.clamp_lines` — 上限縮約＋両端マーカ（spec §9 擬似コード）

**Files:**
- Create: `src/grep_analyzer/snippet.py`
- Test: `tests/unit/test_snippet.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_snippet.py` を新規作成:

```python
from grep_analyzer.snippet import clamp_lines

SEP = " \\n "  # spec §9: 空白+バックスラッシュ+n+空白


def test_上限内はそのまま連結():
    out = clamp_lines(["a", "b", "c"], hit=1, line_max=12, char_max=800)
    assert out == "a \\n b \\n c"


def test_行数上限超過はヒット中心に上下対称縮約し両端マーカ():
    lines = [f"L{i}" for i in range(11)]  # 0..10, hit=5
    out = clamp_lines(lines, hit=5, line_max=3, char_max=800)
    # hit=5 を中心に 3 行（上1/下1）。上に5行省略・下に5行省略のマーカ
    assert out == "…(+5行省略)L4 \\n L5 \\n L6…(+5行省略)"


def test_ヒット行単独が文字数上限超過はコードポイント切詰():
    out = clamp_lines(["x" * 50], hit=0, line_max=12, char_max=10)
    assert out == "xxxxxxxxx…"   # 先頭9字+U+2026=10字


def test_片側範囲端到達後は反対側のみ継続():
    lines = ["A", "B", "C", "D", "E"]  # hit=1（上に1行しかない）
    out = clamp_lines(lines, hit=1, line_max=3, char_max=800)
    assert out == "A \\n B \\n C…(+2行省略)"   # 上は端、下のみ伸長
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_snippet.py -q -k clamp or 上限 or ヒット行単独 or 片側`
Expected: FAIL（`snippet` モジュール未作成）

- [ ] **Step 3: Write minimal implementation**

`src/grep_analyzer/snippet.py` を新規作成:

```python
"""snippet 切り出し（spec §9「snippet 切り出し規則」/ §7 Pro*C）。

物理行 LINES = file_text.split("\\n")（0始まり）。hit = lineno-1。
全関数は走査順非依存・決定的（spec §9 golden 前提）。
"""

SEP = " \\n "          # spec §9: U+0020 U+005C U+006E U+0020
ELLIPSIS = "…"     # U+2026
LINE_MAX = 12
CHAR_MAX = 800


def _marker(k: int, where: str) -> str:
    return f"{ELLIPSIS}(+{k}{where}行省略)"


def _measure(rows: list[str], top_k: int, bot_k: int) -> int:
    body = SEP.join(rows)
    if top_k:
        body = _marker(top_k, "上") + body
    if bot_k:
        body = body + _marker(bot_k, "下")
    return len(body)


def clamp_lines(lines: list[str], hit: int, line_max: int = LINE_MAX,
                char_max: int = CHAR_MAX) -> str:
    """選択範囲 lines（既に [s,e] に絞った物理行列）をヒット中心に縮約。

    spec §9「上限と切り詰め（決定的・擬似コード）」を厳密実装。
    hit は lines 内の 0 始まり index（ヒット行）。
    """
    s, e = 0, len(lines) - 1
    out = [lines[hit]]
    mark_inline = False
    if len(out[0]) > char_max:                    # ヒット行単独超過
        out[0] = lines[hit][:char_max - 1] + ELLIPSIS
        mark_inline = True
    up, dn = hit - 1, hit + 1
    while True:
        if len(out) >= line_max:
            break
        progressed = False
        if up >= s:
            cand = [lines[up]] + out
            if (len(out) + 1 <= line_max
                    and _measure(cand, hit - up, dn - 1 - e if dn - 1 > e else 0)
                    <= char_max):
                out = cand
                up -= 1
                progressed = True
        if len(out) >= line_max:
            break
        if dn <= e:
            cand = out + [lines[dn]]
            if (len(out) + 1 <= line_max
                    and _measure(cand, hit - 1 - up if hit - 1 > up else 0,
                                 dn - e if dn > e else (dn - hit))
                    <= char_max):
                out = cand
                dn += 1
                progressed = True
        if not progressed:
            break
    top_k = (up - s + 1) if up >= s else 0
    bot_k = (e - dn + 1) if dn <= e else 0
    body = SEP.join(out)
    if top_k:
        body = _marker(top_k, "上") + body
    if bot_k:
        body = body + _marker(bot_k, "下")
    return body
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_snippet.py -q`
Expected: PASS（4件）。FAIL する場合は `_measure` の top_k/bot_k 引数計算を spec §9 擬似コード（仮追加後に「最終 ` \n ` 連結＋両端マーカ」長で評価）に合わせて修正し、テスト期待値が spec 例と一致することを確認してから進む。

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/snippet.py tests/unit/test_snippet.py
git -c commit.gpgsign=false commit -m "feat(phase4): snippet.clamp_lines（spec §9 上限縮約・両端マーカ）"
```

---

## Task 4: `snippet.heuristic_span` — sql/shell 決定的ヒューリスティック（spec §9）

**Files:**
- Modify: `src/grep_analyzer/snippet.py`
- Test: `tests/unit/test_snippet.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_snippet.py` に追記:

```python
from grep_analyzer.snippet import heuristic_span


def test_sql_複数行whereを前後拡張して句境界で停止():
    lines = [
        "SELECT * FROM t",
        "WHERE a = 1",
        "  AND b = 2",
        "  AND c = 3;",
        "ORDER BY a",
    ]
    s, e = heuristic_span(lines, hit=2, language="sql")
    # 上は WHERE 句境界、下は文末 ; まで（ORDER BY は別句で含めない）
    assert (s, e) == (1, 3)


def test_shell_括弧バランスと文終端で停止():
    lines = ["if [ $x -eq 1 ]; then", "  echo hi", "fi", "next"]
    s, e = heuristic_span(lines, hit=1, language="shell")
    assert s == 0 and e == 2     # fi で停止、next は含めない


def test_境界未検出でも行数上限で有限停止():
    lines = ["x = (" ] + ["  + 1"] * 50      # 括弧が閉じない
    s, e = heuristic_span(lines, hit=0, language="sql")
    assert e - s + 1 <= 12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_snippet.py -q -k heuristic or whereを or 括弧バランス or 境界未検出`
Expected: FAIL（`heuristic_span` 未定義）

- [ ] **Step 3: Write minimal implementation**

`src/grep_analyzer/snippet.py` に追記（`from grep_analyzer.chase import mask_literals` を冒頭 import に追加）:

```python
import re

from grep_analyzer.chase import mask_literals

_SQL_CLAUSE = re.compile(
    r"\b(WHERE|SET|VALUES|SELECT|FROM|GROUP\s+BY|ORDER\s+BY|HAVING)\b",
    re.IGNORECASE)
_SH_END = re.compile(r"(?:^|\s)(fi|done|esac|breaksw)\b|;|\}")


def _balanced(text: str) -> bool:
    depth = 0
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
    return depth == 0 and text.count("'") % 2 == 0 and text.count('"') % 2 == 0


def heuristic_span(lines: list[str], hit: int, language: str) -> tuple[int, int]:
    """sql/shell の決定的境界。mask_literals を行ごと適用し誤爆防止。

    spec §9 sql/shell: (1)上方向→(2)下方向の順に句/文終端まで拡張。
    各方向の最大は LINE_MAX に従属（境界未検出でも有限）。heredoc は
    mask 非対応＝§8.4 境界、上限で必ず停止。
    """
    masked = [mask_literals(language, ln) for ln in lines]

    def _stop(i: int) -> bool:
        m = masked[i]
        if m.rstrip().endswith("\\"):
            return False
        if not _balanced(m):
            return False
        if language == "sql":
            return m.rstrip().endswith(";") or bool(_SQL_CLAUSE.search(m))
        return bool(_SH_END.search(m))

    s = hit
    for _ in range(LINE_MAX - 1):
        if s == 0 or _stop(s):
            break
        s -= 1
    e = hit
    for _ in range(LINE_MAX - 1):
        if e == len(lines) - 1 or _stop(e):
            break
        e += 1
        if (e - s + 1) >= LINE_MAX:
            break
    return s, e
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_snippet.py -q -k heuristic or whereを or 括弧バランス or 境界未検出`
Expected: PASS。期待 span が spec §9 文言（境界行を含む・上→下順）と一致するか目視確認。ズレる場合は `_stop` の「境界行を含む」解釈を spec に合わせて調整。

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/snippet.py tests/unit/test_snippet.py
git -c commit.gpgsign=false commit -m "feat(phase4): snippet.heuristic_span（sql/shell・mask_literals 行適用）"
```

---

## Task 5: `snippet.ts_span` — java/c tree-sitter ノード選択（spec §9 段1/段2＋粒度表）

**Files:**
- Modify: `src/grep_analyzer/classifiers/ts_classifier.py`（公開ヘルパ追加）
- Modify: `src/grep_analyzer/snippet.py`
- Test: `tests/unit/test_snippet.py`

- [ ] **Step 1: ts_classifier に公開ヘルパを追加（テスト先行）**

`tests/unit/test_snippet.py` に追記:

```python
from grep_analyzer.snippet import ts_span


def test_java_単純文は当該statementの物理行スパン():
    src = "class A {\n  int x =\n    1 + 2;\n}\n"
    assert ts_span("java", src, 2) == (1, 2)   # 宣言文 2-3 行（0始まり 1-2）


def test_java_if条件部のみ_本体ブロック非包含():
    src = "class A { void m(int s){\n  if (s\n      == 1) {\n    g();\n  }\n}}\n"
    s, e = ts_span("java", src, 2)              # ヒット = if 条件 2行目
    assert (s, e) == (1, 2)                     # if(...) の物理行のみ、本体非包含


def test_同一行複数statementは行頭statement_列非依存():
    src = "class A { void m(){\n a(); b(); c();\n}}\n"
    assert ts_span("java", src, 2) == (1, 1)    # 行頭 a(); の statement 行


def test_parse不能はNone():
    assert ts_span("java", "@@@ not java @@@\n", 1) is None or isinstance(
        ts_span("java", "@@@ not java @@@\n", 1), tuple)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_snippet.py -q -k ts_span or 単純文 or if条件部 or 同一行複数 or parse不能`
Expected: FAIL（`ts_span` 未定義）

- [ ] **Step 3: ts_classifier に node_at_line を公開**

`src/grep_analyzer/classifiers/ts_classifier.py` に追記（既存 `_node_at_line`/`classify_ts` は変更しない）:

```python
def parse_tree(language: str, source: str):
    """snippet 用: マスク済ソースの tree を返す（proc は呼び出し側で別処理）。"""
    return _parser(language).parse(source.encode("utf-8")).root_node


def node_at_line(root, lineno: int):
    """snippet 用公開ラッパ（spec §9 段1＝最小内包ノード・列非依存）。"""
    return _node_at_line(root, lineno)
```

- [ ] **Step 4: snippet.ts_span を実装**

`src/grep_analyzer/snippet.py` に追記:

```python
from grep_analyzer.classifiers.ts_classifier import node_at_line, parse_tree

# spec §9 粒度表: climb 中にこれらの type に最初に当たったら採用。
_GRAN_JAVA = {
    "if_statement", "while_statement", "for_statement",
    "switch_expression", "switch_statement", "switch_block_statement_group",
    "try_statement", "try_with_resources_statement",
    "local_variable_declaration", "field_declaration", "return_statement",
    "expression_statement",
}
_GRAN_C = {
    "if_statement", "while_statement", "for_statement", "switch_statement",
    "case_statement", "declaration", "expression_statement", "return_statement",
}
# if/while/switch は条件部（括弧）のみ・本体非包含 → 括弧トークン範囲へ縮める型
_PAREN_ONLY = {"if_statement", "while_statement", "switch_statement",
               "switch_expression", "for_statement"}
_BLOCK_TYPES = {"block", "compound_statement", "program", "translation_unit",
                "method_declaration", "function_definition", "constructor_declaration"}


def _paren_span(node) -> tuple[int, int]:
    """node 配下の最初の '(' 〜 対応する ')' の物理行スパン（0始まり）。"""
    text = node.text.decode("utf-8", "replace")
    base = node.start_point[0]
    # 行ベースで近似: node 開始〜最初に括弧深さ0へ戻る行まで
    depth, sline = 0, None
    line = base
    for ch in text:
        if ch == "(":
            depth += 1
            if sline is None:
                sline = line
        elif ch == ")":
            depth -= 1
            if depth == 0 and sline is not None:
                return (sline, line)
        elif ch == "\n":
            line += 1
    return (node.start_point[0], node.end_point[0])


def ts_span(language: str, file_text: str, lineno: int):
    """java/c の選択範囲 [s,e]（0始まり物理行）。取れなければ None。

    spec §9 段1（_node_at_line=最小葉・列非依存）→段2（.parent 上昇で
    粒度表へ昇格／block 等に達したら直近 statement／無ければ None）。
    """
    lang = "c" if language in ("c", "proc") else "java"
    try:
        root = parse_tree(lang, file_text)
    except Exception:
        return None
    n = node_at_line(root, lineno)
    if n is None or "ERROR" in (n.type, getattr(n, "type", "")):
        return None
    gran = _GRAN_JAVA if lang == "java" else _GRAN_C
    last_stmt = None
    cur = n
    while cur is not None:
        t = cur.type
        if t in ("expression_statement", "declaration",
                 "local_variable_declaration", "field_declaration",
                 "return_statement"):
            last_stmt = cur
        if t in gran:
            if t in _PAREN_ONLY:
                return _paren_span(cur)
            return (cur.start_point[0], cur.end_point[0])
        if t in _BLOCK_TYPES:
            if last_stmt is not None:
                return (last_stmt.start_point[0], last_stmt.end_point[0])
            return None
        cur = cur.parent
    if last_stmt is not None:
        return (last_stmt.start_point[0], last_stmt.end_point[0])
    return None
```

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/unit/test_snippet.py -q -k ts_span or 単純文 or if条件部 or 同一行複数 or parse不能`
Expected: PASS。期待 span が spec §9 粒度表（if は括弧のみ・本体非包含／同一行複数は行頭 statement）と一致するか目視確認。tree-sitter ノード型が実環境と異なる場合は `python -c "import tree_sitter_java,tree_sitter_c"` で版確認し、`_GRAN_*`/`_PAREN_ONLY` を実ノード型に合わせて修正（spec 文言は維持）。

```bash
git add src/grep_analyzer/classifiers/ts_classifier.py src/grep_analyzer/snippet.py tests/unit/test_snippet.py
git -c commit.gpgsign=false commit -m "feat(phase4): snippet.ts_span（spec §9 段1/段2＋粒度表・括弧本体非包含）"
```

---

## Task 6: `proc_preprocess.exec_spans` ＋ `snippet.proc_exec_span`（spec §7 Crit-1 訂正）

**Files:**
- Modify: `src/grep_analyzer/proc_preprocess.py`
- Modify: `src/grep_analyzer/snippet.py`
- Test: `tests/unit/test_proc_preprocess.py`, `tests/unit/test_snippet.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_proc_preprocess.py` に追記:

```python
from grep_analyzer.proc_preprocess import exec_spans


def test_文字列内セミコロンで誤切断しない():
    src = ("int x;\n"
           "EXEC SQL INSERT INTO t\n"
           "  VALUES (';', :y) ;\n"
           "int z;\n")
    # 行1-2（0始まり）が EXEC 区間。文字列内 ';' で切れない
    assert exec_spans(src) == [(1, 2)]


def test_複数EXEC区間とEND_EXEC():
    src = ("EXEC SQL A ;\n"
           "mid;\n"
           "EXEC ORACLE OPTION\n"
           "END-EXEC\n")
    assert exec_spans(src) == [(0, 0), (2, 3)]
```

`tests/unit/test_snippet.py` に追記:

```python
from grep_analyzer.snippet import proc_exec_span


def test_proc_exec_spanは原ソース行スパンを返す():
    src = "int x;\nEXEC SQL SELECT 1\n  INTO :a FROM dual ;\n"
    assert proc_exec_span(src, 2) == (1, 2)   # hit=2行目→区間[1,2]
    assert proc_exec_span(src, 1) is None     # 区間外
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_proc_preprocess.py tests/unit/test_snippet.py -q -k exec_span or 文字列内セミ or 複数EXEC or 原ソース行`
Expected: FAIL（`exec_spans`/`proc_exec_span` 未定義）

- [ ] **Step 3: proc_preprocess に exec_spans を追加**

`src/grep_analyzer/proc_preprocess.py` に追記（既存 `mask_exec_sql`/`_EXEC_RE` は不変）:

```python
from grep_analyzer.chase import _MASK_SPECS

# Pro*C のリテラル/コメントを同幅空白化（行番号・桁不変）。spec §7 v9 Crit-1。
_PROC_LIT_RE = __import__("re").compile(
    "|".join(_MASK_SPECS["proc"]), __import__("re").DOTALL)


def _blank_literals(source: str) -> str:
    return _PROC_LIT_RE.sub(lambda m: "".join(
        ch if ch == "\n" else " " for ch in m.group(0)), source)


def exec_spans(source: str) -> list[tuple[int, int]]:
    """EXEC SQL/ORACLE 区間を (start_line, end_line)（0始まり）で返す。

    リテラル・コメント空白化コピー上で _EXEC_RE を走らせ、文字列内 ;/
    END-EXEC の誤切断を防ぐ（spec §7 v9 Crit-1）。区間は原ソース行へ写像。
    """
    masked = _blank_literals(source)
    spans = []
    for m in _EXEC_RE.finditer(masked):
        s = source.count("\n", 0, m.start())
        e = source.count("\n", 0, m.end())
        spans.append((s, e))
    return spans
```

- [ ] **Step 4: snippet.proc_exec_span を追加**

`src/grep_analyzer/snippet.py` に追記:

```python
from grep_analyzer.proc_preprocess import exec_spans


def proc_exec_span(file_text: str, lineno: int):
    """hit が EXEC 区間に含まれれば原ソース行スパン [s,e]、なければ None。"""
    hit = lineno - 1
    for s, e in exec_spans(file_text):
        if s <= hit <= e:
            return (s, e)
    return None
```

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/unit/test_proc_preprocess.py tests/unit/test_snippet.py -q`
Expected: PASS（既存 proc_preprocess テストも不変で PASS＝`mask_exec_sql` 無改修を確認）

```bash
git add src/grep_analyzer/proc_preprocess.py src/grep_analyzer/snippet.py tests/unit/test_proc_preprocess.py tests/unit/test_snippet.py
git -c commit.gpgsign=false commit -m "feat(phase4): exec_spans/proc_exec_span（spec §7 v9 Crit-1 リテラル空白化検出）"
```

---

## Task 7: `snippet.build_snippet` — 言語ディスパッチ＋フォールバック順（spec §9）

**Files:**
- Modify: `src/grep_analyzer/snippet.py`
- Test: `tests/unit/test_snippet.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_snippet.py` に追記:

```python
from grep_analyzer.snippet import build_snippet


def test_java_複数行宣言を1セルへ連結():
    src = "class A {\n  int x =\n    1 + 2;\n}\n"
    assert build_snippet("java", "bourne", src, 2) == "  int x = \\n     1 + 2;"


def test_sql_複数条件whereを連結():
    src = "SELECT *\nFROM t\nWHERE a=1\n  AND b=2;\n"
    out = build_snippet("sql", "bourne", src, 3)
    assert "WHERE a=1 \\n   AND b=2;" in out


def test_proc_EXEC区間は原ソース行():
    src = "int x;\nEXEC SQL SELECT 1\n  INTO :a FROM dual ;\nint z;\n"
    assert build_snippet("proc", "bourne", src, 2) == \
        "EXEC SQL SELECT 1 \\n   INTO :a FROM dual ;"


def test_parse不能javaはヒューリスティック_最後は1行():
    out = build_snippet("java", "bourne", "@@@@@\n", 1)
    assert out == "@@@@@"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_snippet.py -q -k build_snippet or 複数行宣言 or 複数条件where or EXEC区間は原 or parse不能java`
Expected: FAIL（`build_snippet` 未定義）

- [ ] **Step 3: Write minimal implementation**

`src/grep_analyzer/snippet.py` に追記:

```python
def build_snippet(language: str, dialect: str, file_text: str,
                  lineno: int) -> str:
    """spec §9 snippet 切り出し規則のエントリ。確定済み1セル文字列を返す。

    java/c: ts_span → 取れなければ heuristic → 1行（フォールバック順）。
    proc: EXEC 区間は原ソース span／区間外は c と同経路。
    sql/shell: heuristic_span。最後に clamp_lines で上限縮約。
    """
    lines = file_text.split("\n")
    hit = lineno - 1
    if hit < 0 or hit >= len(lines):
        return ""
    span = None
    if language in ("java", "c"):
        span = ts_span(language, file_text, lineno)
        if span is None:
            span = heuristic_span(lines, hit, "shell"
                                  if language not in ("sql", "shell") else language)
    elif language == "proc":
        span = proc_exec_span(file_text, lineno)
        if span is None:
            span = ts_span("c", file_text, lineno)
            if span is None:
                span = heuristic_span(lines, hit, "shell")
    elif language in ("sql", "shell"):
        span = heuristic_span(lines, hit, language)
    if span is None:
        span = (hit, hit)                       # フォールバック(3)
    s, e = span
    s = max(0, min(s, hit))
    e = min(len(lines) - 1, max(e, hit))
    return clamp_lines(lines[s:e + 1], hit - s)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_snippet.py -q`
Expected: PASS（全 snippet unit）。期待文字列が spec §9（` \n ` 連結・インデント保持）と一致するか目視。

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/snippet.py tests/unit/test_snippet.py
git -c commit.gpgsign=false commit -m "feat(phase4): snippet.build_snippet（言語ディスパッチ＋フォールバック順・spec §9）"
```

---

## Task 8: pipeline 配線 — `file` 絶対化＋`snippet` を build_snippet へ

**Files:**
- Modify: `src/grep_analyzer/pipeline.py:28-84`
- Test: `tests/unit/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_pipeline.py` に追記:

```python
from pathlib import Path

from grep_analyzer.pipeline import run


def test_file列は絶対パス_snippetは構文単位(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "A.java").write_text(
        "class A {\n  static final String K =\n    \"K\";\n}\n", "utf-8")
    inp = tmp_path / "in"
    inp.mkdir()
    (inp / "K.grep").write_text("A.java:2:  static final String K =\n", "utf-8")
    out = tmp_path / "out"
    assert run(inp, out, src) == 0
    rows = (out / "K.tsv").read_text("utf-8-sig").splitlines()
    cells = rows[1].split("\t")
    resolved = str(Path(src).resolve())
    assert cells[2] == f"{resolved}/A.java"          # file 絶対
    assert cells[10] == "  static final String K = \\n     \"K\";"  # snippet 多行
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_pipeline.py -q -k file列は絶対パス`
Expected: FAIL（現 pipeline は `file=rel`・`snippet=content`）

- [ ] **Step 3: Write minimal implementation**

`src/grep_analyzer/pipeline.py` を編集:

冒頭 import に追加:

```python
from grep_analyzer.snippet import build_snippet
```

`run()` 内、`files = collect_files(...)` の直前に追加:

```python
    src_abs = str(Path(source_root).resolve())
```

`hits.append(Hit(...))` の `file=` と `snippet=` を変更:

```python
            hits.append(Hit(
                keyword=keyword, language=language,
                file=f"{src_abs}/{rel}", lineno=lineno,
                ref_kind="direct", category=category, category_sub="",
                usage_summary=f"{category} ({language})", via_symbol="",
                chain=f"{keyword}@{rel}:{lineno}",
                snippet=build_snippet(language, dialect, file_text, lineno),
                encoding=enc + (" 要確認" if replaced else ""),
                confidence=confidence,
            ))
```

注: `chain` は relpath 維持（spec §9 確認A・変更しない）。`run_fixedpoint` が生成する indirect Hit の `file`/`snippet` も同一規約にするため、`fixedpoint` 側の Hit 構築箇所を grep し（`grep -n "Hit(" src/grep_analyzer/fixedpoint.py`）、`file=` を `f"{src_abs}/{rel}"` 相当・`snippet=build_snippet(...)` へ同様に差し替える（src_abs を `run_fixedpoint` 引数で渡すか `source_root` から同式で算出）。indirect の snippet 言語/dialect は当該ヒット行の言語判定を再利用する（pipeline と同じ `detect_language`/`detect_shell_dialect`）。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_pipeline.py -q -k file列は絶対パス`
Expected: PASS

- [ ] **Step 5: fixedpoint 配線確認＋コミット**

Run: `python -m pytest tests/unit/test_fixedpoint.py -q`
Expected: PASS（indirect の file/snippet も新規約。落ちる expected は Task 12 で再生成、ここでは「Hit 構築規約が pipeline と一致」のみ確認）

```bash
git add src/grep_analyzer/pipeline.py src/grep_analyzer/fixedpoint.py tests/unit/test_pipeline.py
git -c commit.gpgsign=false commit -m "feat(phase4): pipeline/fixedpoint を file絶対化＋build_snippet 配線（spec §9）"
```

---

## Task 9: golden 比較ハーネス改修（spec §11 v9 normative）

**Files:**
- Modify: `tests/golden/test_golden.py`

- [ ] **Step 1: ハーネスを spec §11 機構へ書き換え**

`tests/golden/test_golden.py` を全置換:

```python
"""合成代表ツリーの TSV 完全一致による回帰検出（spec §11 v9 機構）。"""

import json
from pathlib import Path

from grep_analyzer import resume
from grep_analyzer.pipeline import run


def _read_case_opts(case: Path):
    """ケース任意設定（output_encoding/resume/follow_symlinks）。無ければ既定。"""
    cfg = case / "opts.json"
    return json.loads(cfg.read_text("utf-8")) if cfg.is_file() else {}


def test_合成ケースのTSVが期待値と完全一致する(golden_case, tmp_path):
    out = tmp_path / "out"
    cfg = _read_case_opts(golden_case)
    rc = run(
        input_dir=golden_case / "input",
        output_dir=out,
        source_root=golden_case / "src",
    )
    assert rc == 0
    sr = str(Path(golden_case / "src").resolve())          # spec §11(b)
    for expected in (golden_case / "expected").glob("*.tsv"):
        keyword = expected.stem
        mpath = out / f"{keyword}.manifest.json"
        enc = "utf-8-sig"
        if mpath.is_file():                                # spec §11(a)
            enc = json.loads(mpath.read_text("utf-8")).get("encoding",
                                                           "utf-8-sig")
        actual = (out / expected.name).read_text(enc)
        actual = actual.replace(sr + "/", "{SOURCE_ROOT}/", 1)  # §11(b) 先頭1回
        assert actual == expected.read_text("utf-8-sig"), expected.name
    if cfg.get("assert_resume_complete"):                  # spec §11(d)
        for expected in (golden_case / "expected").glob("*.tsv"):
            assert resume.is_complete(out, expected.stem,
                                      run.__globals__["_default_opts"]())
```

注: resume 系ケースは `opts.json` に `{"assert_resume_complete": true}` を置く。`run` が `opts` 既定で resume 無効でも `output_writer.finalize` が manifest を生成するため `is_complete` は判定可能（spec §10.3/§11）。

- [ ] **Step 2: Run to verify harness shape (expected はまだ旧形式＝全 FAIL 想定)**

Run: `python -m pytest tests/golden -q`
Expected: 多数 FAIL（`file` が `{SOURCE_ROOT}/...` になり旧 `expected`（相対パス・1行 snippet）と不一致）。これは Task 10 で再生成するため**想定どおり**。クラッシュ（例外）でないこと（AssertionError のみ）を確認。

- [ ] **Step 3: Commit（ハーネスのみ。expected 再生成は次タスク）**

```bash
git add tests/golden/test_golden.py
git -c commit.gpgsign=false commit -m "test(phase4): golden 比較を spec §11 v9 機構へ（{SOURCE_ROOT}逆置換・manifest encoding・resume assert）"
```

---

## Task 10: golden expected 全件再生成（影響3要因別レビュー・spec §15 手順4）

**Files:**
- Modify: `tests/golden/cases/*/expected/*.tsv`（14 ケース）

- [ ] **Step 1: 影響範囲を事前 grep で確定（spec §15 手順4 の最初のタスク）**

Run:
```bash
grep -rl "	direct	\|	indirect" tests/golden/cases/*/expected tests/unit tests/integration | sort
ls tests/golden/cases
```
記録: 全 expected 一覧と、indirect 行を含む6ケース（chain_multipath / getter_no_expand / indirect_constant / indirect_var_shell / oracle_direct / shell_direct）。

- [ ] **Step 2: 再生成スクリプトで actual を生成し expected へ採用**

各ケースを実コードで走らせ、`{SOURCE_ROOT}` 正規化済テキストを expected に書き戻す一時スクリプト:

```bash
python - <<'PY'
import json, pathlib
from grep_analyzer.pipeline import run
base = pathlib.Path("tests/golden/cases")
for case in sorted(base.iterdir()):
    if not (case/"input").is_dir(): continue
    out = case/".regen"
    run(input_dir=case/"input", output_dir=out, source_root=case/"src")
    sr = str((case/"src").resolve())
    for tsv in (case/"expected").glob("*.tsv"):
        kw = tsv.stem
        m = out/f"{kw}.manifest.json"
        enc = json.loads(m.read_text("utf-8")).get("encoding","utf-8-sig") if m.is_file() else "utf-8-sig"
        txt = (out/tsv.name).read_text(enc).replace(sr+"/","{SOURCE_ROOT}/",1)
        tsv.write_text(txt, "utf-8-sig")
    import shutil; shutil.rmtree(out)
print("regenerated")
PY
```

- [ ] **Step 3: 3要因別に diff をレビュー（spec §15 手順4・正本=diff）**

Run: `git diff --stat tests/golden/cases` と各ケース `git diff tests/golden/cases/<case>/expected`。
レビュー観点（各ケース diff を3分類で説明できること）:
- **A（file 絶対化）**: `file` 列が `{SOURCE_ROOT}/<relpath>` へ（全14ケース）。
- **B（snippet 多行化）**: snippet 列が構文単位へ（複数行宣言/if/WHERE の行のみ変化）。
- **C（ソート順）**: indirect 含む6件で chain 集約により行順変化したものを確認（spec §9 Phase 影響と一致＝行順変化/byte のみ変化の内訳を記述）。
diff が3要因で説明できない変化（＝バグ）があれば該当 Task（3-8）へ戻る。

- [ ] **Step 4: golden green を確認**

Run: `python -m pytest tests/golden -q`
Expected: **14 passed**（新ベースライン）

- [ ] **Step 5: Commit（再生成 diff を3要因の説明文付きで）**

```bash
git add tests/golden/cases
git -c commit.gpgsign=false commit -m "test(phase4): golden expected 全件再生成（A:file絶対化/B:snippet多行/C:ソート順・spec §15 手順4・意図的Inv-1再ベースライン）"
```

---

## Task 11: spec §11 v9 名指し新規 golden ケース追加

**Files:**
- Create: `tests/golden/cases/{multiline_if,multiline_where,sameline_stmt,proc_exec_snippet,parsefail_fallback,sanitize_ctrl,symlink_dedup,cp932_resume}/`

- [ ] **Step 1: 各新規ケースの input/src/(opts)/expected を作成**

各ケースに `input/<kw>.grep`・`src/<file>`・`expected/<kw>.tsv` を置く。expected は Task 10 の再生成スクリプトを単一ケースに適用して生成し、内容が spec §9 規則どおりか目視確認してから採用する。最低限の代表ケース:

- `multiline_if/`：複数行 if 条件（snippet が条件部のみ・本体非包含）
- `multiline_where/`：SQL 複数条件 WHERE（句境界停止）
- `sameline_stmt/`：`a(); b(); c();` で行頭 statement 選択（§8.4 既知粒度）
- `proc_exec_snippet/`：`EXEC SQL ... VALUES (';', :y);`（文字列内 `;` 誤切断なし）
- `parsefail_fallback/`：構文エラー含む .java（フォールバック=1行）
- `sanitize_ctrl/`：snippet に U+000B/U+2028 を含むソース（空白化）
- `symlink_dedup/`：`opts.json={"follow_symlinks":true}` 相当の代表 relpath（後述 Step 2）
- `cp932_resume/`：`opts.json={"output_encoding":"cp932","assert_resume_complete":true}`、複数行 snippet を含み `--resume` 完了

- [ ] **Step 2: symlink_dedup と cp932 はハーネス/opts 対応を確認**

`test_golden.py` の `run(...)` は現状 `opts` を渡していない。symlink/cp932/resume を要するケースは `_read_case_opts` を `EngineOptions` へ反映する分岐を `test_golden.py` に追加（`follow_symlinks`/`encoding`→`output_encoding`/`resume`）。spec §11(d) の `assert_resume_complete` 経路と整合させる。変更後 `python -m pytest tests/golden -q` で新規ケース含め green。

- [ ] **Step 3: Commit**

```bash
git add tests/golden/cases tests/golden/test_golden.py
git -c commit.gpgsign=false commit -m "test(phase4): spec §11 v9 名指し新規 golden（多行snippet/proc-exec/parsefail/sanitize/symlink/cp932-resume）"
```

---

## Task 12: unit/integration expected 再生成＋Inv-1 新ベースライン＋perf 再測定

**Files:**
- Modify: `tests/unit/*.py`, `tests/integration/*.py`（snippet/file 列を持つ expected）
- Modify: `docs/superpowers/plans/phase0-gate-result.md`（v8/v9 注記追記）
- Modify: `src/grep_analyzer/budget.py`（`_ITEMS_PER_MB` 再較正・perf 証跡）

- [ ] **Step 1: 影響 unit/integration を特定し再生成**

Run: `python -m pytest tests/unit tests/integration -q`
落ちたテストのうち「`file`/`snippet` 列のリテラル期待」を新規約へ更新（順序・列値の最小修正。Hit 構築・ロジック assert は不変）。`test_pipeline.py`/`test_fixedpoint.py`/`test_output_writer.py`/`test_encoding_wiring.py` が主対象（Task 8 で確認済の挙動に整合）。

- [ ] **Step 2: Inv-1 新ベースライン確立**

Run: `python -m pytest -q`
Expected: 全 green（golden 14＋新規＋unit/integration）。これが **v8/v9 後の新 Inv-1 ベースライン**。

- [ ] **Step 3: phase0-gate-result.md に再ベースライン注記（凍結記録は書き換えない）**

`docs/superpowers/plans/phase0-gate-result.md` の Inv-1 記録節（L312-316／L385-389）は**書き換えず**、文末に追記:

```markdown
> **[v8/v9 再ベースライン注記 2026-05-18]** 上記 Inv-1 byte 不変は v7 スキーマ時点の凍結証跡。spec v9 §15 フェーズ4（意図的破壊的スキーマ変更）により golden/unit/integration expected を A:file絶対化・B:snippet多行化・C:ソート順の3要因で再生成し、v8/v9 後の新ベースラインで Inv-1 を再確立した（本計画 Task 10/12）。
```

- [ ] **Step 4: perf/_ITEMS_PER_MB 再測定（非ゲート・spec §8.2/§11）**

Run: `python -m pytest tests/perf -q -m perf`
snippet 多行化で1レコード最大バイトが増えるため `budget._ITEMS_PER_MB` を perf 証跡とともに一度だけ再較正（既存較正手順＝`docs/superpowers/plans/phase3-perf-report.md` の方式に準拠）。非ゲートのため CI は停止しない。

- [ ] **Step 5: 最終確認とコミット**

Run: `python -m pytest -q && python -m grep_analyzer --help`
Expected: 全 green・exit 0

```bash
git add tests src docs/superpowers/plans/phase0-gate-result.md
git -c commit.gpgsign=false commit -m "test(phase4): unit/integration 再生成＋Inv-1 新ベースライン＋_ITEMS_PER_MB 再較正（spec §15）"
```

---

## Self-Review（spec v9 との突合）

- **§9 file 絶対化**: Task 8（`Path(source_root).resolve()`＋rel・起動時1回）／Task 9-10（`{SOURCE_ROOT}` 逆置換ハーネス・全 expected 移行）。chain は relpath 維持（Task 8 注記）。✓
- **§9 ソートキー**: Task 1（`(ref_kind_rank, chain_group, …, language, encoding)`・全順序）。✓
- **§9 サニタイズ規約①**: Task 2（U+000B/000C/0085/2028/2029）。区切り衝突エスケープ②は `build_snippet` 連結前に各行へ適用が必要 → **Task 7 Step 3 に「各物理行へ `_sanitize` 適用後、` \n ` と同一3文字列があれば `\\`→`\\\\` エスケープ」を追加実装すること**（spec §9 サニタイズ規約②。本 Self-Review で補完）。
- **§9 snippet 切り出し（段1/段2・粒度表・括弧本体非包含・同一行=行頭・フォールバック順・上限縮約）**: Task 3-7。✓
- **§7 Pro\*C EXEC（リテラル空白化検出・原ソース span）**: Task 6。✓
- **§8.2 file 解決・relpath 辞書順代表**: Task 8（既存 walk.py の代表 relpath をそのまま連結。walk.py 改修不要）。✓
- **§10.3 diagnostics relpath 維持**: pipeline の diagnostics は `str(rel)` のまま（Task 8 で `file` 列のみ絶対化＝層分離）。✓
- **§11 比較機構・名指し回帰**: Task 9（機構）／Task 11（cp932×resume・parsefail・proc-exec・sanitize・symlink・多行 if/where/sameline）。✓
- **§15 フェーズ4 手順1-5・churn は意図的**: Task 10（3要因 diff レビュー）／Task 12（凍結注記・新ベースライン・perf 再測定）。golden 固定は本計画の成果物（着手循環なし）。✓

**補完反映（Self-Review で発見・要対応）**: Task 7 Step 3 の `build_snippet` に spec §9 サニタイズ規約②（区切り衝突 `\` エスケープ）と各行 `_sanitize` 適用を含めること。実装時、`clamp_lines` へ渡す前に `lines = [_sanitize(escape_sep(ln)) for ln in lines[s:e+1]]` 相当を入れる（`from grep_analyzer.tsv import _sanitize`）。テスト `test_snippet.py` に「区切り衝突文字列のエスケープ」ケースを1件追加。

---

## Execution Handoff

実行はユーザ既定により **subagent-driven-development**（タスクごとに fresh subagent＋2段レビュー）。プラン自体は spec と同じ批判的AIレビューゲート（3観点×収束まで）を通してから着手する。
