# grep_analyzer フェーズ4（v8/v9 出力可読性改訂）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** spec §9 の3改訂（`file` 絶対化／direct→indirect chain 集約ソート／構文単位・複数行 snippet）を決定性を保ったまま実装し、既存資産の Inv-1 を新ベースラインへ再確立する。

**Architecture:** snippet 切り出しを新モジュール `src/grep_analyzer/snippet.py`（純関数群＋言語ディスパッチ）に集約し pipeline/fixedpoint の分類ステージから呼ぶ。**`file` 絶対化は「Hit 構築」ではなく「output_writer.finalize 直前の最終変換」で行う**（pipeline/fixedpoint/Occurrence/graph/chain/diagnostics は relpath のまま＝層分離・spec §9/§10.3）。ソート（`model.sort_key`）・サニタイズ（`tsv._sanitize`）はピンポイント改修。golden 比較ハーネス（`tests/golden/test_golden.py`）に `{SOURCE_ROOT}` 逆置換＋manifest encoding 読戻し＋resume assert＋opts 配線を加え、影響3要因（A:file 絶対化／B:snippet 多行化／C:ソート順）別に expected を再生成する。

**Tech Stack:** Python 3.12 / py-tree-sitter 0.21（tree-sitter-java, tree-sitter-c）/ pytest（古典学派 TDD・日本語テスト名）。spec 正本: `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`（v9・§7/§8.2/§8.4/§9/§10.3/§11/§15 フェーズ4）。

**本計画の埋め込みコードは `/workspaces/grep_helpers2` 実環境で実行検証済**（clamp_lines/heuristic_span/ts_span/_paren_span/exec_spans の14アサーション green）。逸脱が必要なら spec 本体（ユーザ所有）を先に改訂する。

**物理行の定義（全 snippet 関数共通・決定性）:** `_phys(file_text)` ＝ `file_text.split("\n")` から、`file_text` が改行終端なら**末尾の人工空要素を1個だけ除去**したリスト（`splitlines()` は使わない＝U+2028 等の水増し回避・spec §9）。0始まり index。tree-sitter row も `\n` 基準で整合。`hit_idx = lineno - 1`。pipeline の grep 行パース（`text.splitlines()`）は別レイヤで本定義の射程外（変更しない）。

---

## File Structure

| ファイル | 役割 | 区分 |
|---|---|---|
| `src/grep_analyzer/snippet.py` | snippet 切り出し純関数群（_phys/_render/clamp_lines/heuristic_span/ts_span/_paren_span/_has_err/exec 連携/escape/build_snippet）。spec §9・§7 Pro\*C の唯一の実装場所 | Create |
| `src/grep_analyzer/model.py` | `sort_key` を spec §9 v9 キーへ差替 | Modify |
| `src/grep_analyzer/tsv.py` | `_sanitize` の対象集合を spec §9 サニタイズ規約①へ拡張 | Modify |
| `src/grep_analyzer/proc_preprocess.py` | `exec_spans()`（リテラル空白化コピー上で EXEC 区間検出）追加。既存 `mask_exec_sql`/`_EXEC_RE` 不変 | Modify |
| `src/grep_analyzer/classifiers/ts_classifier.py` | `parse_tree()`/`node_at_line()` 公開ヘルパ追加。既存 `classify_ts`/`_node_at_line` 不変 | Modify |
| `src/grep_analyzer/pipeline.py` | 直接 Hit `snippet=build_snippet(...)`／finalize 直前に `file` 絶対化最終変換 | Modify |
| `src/grep_analyzer/fixedpoint.py` | indirect Hit `snippet=build_snippet(...)`（`file=c.relpath` は不変） | Modify |
| `tests/golden/test_golden.py` | `{SOURCE_ROOT}` 逆置換＋manifest encoding 読戻し＋opts 配線＋resume assert | Modify |
| `tests/unit/test_snippet.py` | snippet.py 純関数 unit（TDD） | Create |
| `tests/unit/*.py`, `tests/integration/*.py` | sort/file/snippet 列の expected 再生成 | Modify |
| `tests/golden/cases/*/expected/*.tsv` | 影響3要因別に全件再生成（A/B/C） | Modify |
| `tests/golden/cases/<新規8件>/` | spec §11 v9 名指し新規ケース（src/input/expected を手作成） | Create |
| `docs/superpowers/plans/phase0-gate-result.md` | v8/v9 Inv-1 再ベースライン注記を追記（凍結記録は書き換えない） | Modify |

---

## Task 1: `model.sort_key` を spec §9 v9 キーへ差替

**Files:** Modify `src/grep_analyzer/model.py:40-45`／Test `tests/unit/test_model.py`

- [ ] **Step 1: Write the failing test** — `tests/unit/test_model.py` に追記:

```python
from grep_analyzer.model import Hit, sort_key


def _h(**kw):
    base = dict(keyword="K", language="java", file="/r/A.java", lineno=1,
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


def test_indirectはchain文字列ごとに集約されてからfile_lineno():
    a = _h(ref_kind="indirect:constant", file="/r/Z.java", lineno=9,
           via_symbol="V", chain="K@A:1 -> V@A:1")
    b = _h(ref_kind="indirect:constant", file="/r/A.java", lineno=1,
           via_symbol="W", chain="K@A:1 -> W@B:1")
    assert sorted([a, b], key=sort_key) == [a, b]


def test_direct同士はfile_lineno数値順():
    x = _h(lineno=10, chain="K@A.java:10")
    y = _h(lineno=2, chain="K@A.java:2")
    assert sorted([x, y], key=sort_key) == [y, x]


def test_完全同値近傍はlanguage_encodingで全順序():
    p = _h(language="java")
    q = _h(language="shell")
    assert sorted([q, p], key=sort_key) == [p, q]
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/unit/test_model.py -q -k "directブロック or chain文字列ごと or 完全同値近傍"` → FAIL（旧キー）

- [ ] **Step 3: Implement** — `src/grep_analyzer/model.py` の `sort_key` を全置換:

```python
def sort_key(h: Hit) -> tuple:
    """spec §9 v9 全順序キー。

    (ref_kind_rank, chain_group, file, lineno, ref_kind, via_symbol,
     category, category_sub, confidence, usage_summary, snippet,
     language, encoding)。ref_kind_rank: direct→0 / indirect:*→1。
    chain_group: direct→"" / indirect:*→chain。lineno は数値順。
    """
    ref_kind_rank = 0 if h.ref_kind == "direct" else 1
    chain_group = "" if h.ref_kind == "direct" else h.chain
    return (
        ref_kind_rank, chain_group, h.file, h.lineno, h.ref_kind,
        h.via_symbol, h.category, h.category_sub, h.confidence,
        h.usage_summary, h.snippet, h.language, h.encoding,
    )
```

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/unit/test_model.py -q` → PASS（新規4件＋既存）。既存テストで旧 `(file,lineno,...)` 前提の順序アサートが落ちたら新キー結果へ最小修正（Hit 構築・ロジックは不変）。

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/model.py tests/unit/test_model.py
git -c commit.gpgsign=false commit -m "feat(phase4): sort_key を spec §9 v9 キーへ"
```

---

## Task 2: `tsv._sanitize` の対象集合拡張（spec §9 サニタイズ規約①）

**Files:** Modify `src/grep_analyzer/tsv.py:10-12`／Test `tests/unit/test_tsv.py`

- [ ] **Step 1: Write the failing test** — `tests/unit/test_tsv.py` に追記:

```python
from grep_analyzer.tsv import _sanitize


def test_拡張空白文字を半角空白へ():
    assert _sanitize("a\tb\rc\nd\x0be\x0cf\x85g h i") == \
        "a b c d e f g h i"


def test_通常文字とU2026マーカは保持():
    assert _sanitize("…(+3上行省略) X") == "…(+3上行省略) X"
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/unit/test_tsv.py -q -k 拡張空白文字` → FAIL

- [ ] **Step 3: Implement** — `src/grep_analyzer/tsv.py` の `_sanitize` を置換:

```python
# spec §9 サニタイズ規約①: 行/改ページ分割クラスを半角空白1個へ。
# split("\n")/data_sha256 の決定性コアは不変（U+000A は従来どおり空白化）。
_SANITIZE_MAP = {ord(c): " " for c in "\t\r\n\x0b\x0c\x85  "}


def _sanitize(cell: str) -> str:
    """フィールド内のタブ・改行・行分割クラスを空白へ置換する（spec §9）。"""
    return cell.translate(_SANITIZE_MAP)
```

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/unit/test_tsv.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/tsv.py tests/unit/test_tsv.py
git -c commit.gpgsign=false commit -m "feat(phase4): _sanitize を spec §9 サニタイズ規約①へ拡張"
```

---

## Task 3: `snippet.py` 骨格＋`clamp_lines`（spec §9 上限縮約・上/下マーカ）

**Files:** Create `src/grep_analyzer/snippet.py`／Test `tests/unit/test_snippet.py`

> 期待値は実環境実行で検証済（`…(+<K>上行省略)`/`…(+<K>下行省略)`・K は当該側残数・off-by-one なし）。

- [ ] **Step 1: Write the failing test** — `tests/unit/test_snippet.py` を新規作成:

```python
from grep_analyzer.snippet import clamp_lines


def test_上限内はそのまま連結():
    assert clamp_lines(["a", "b", "c"], 1) == "a \\n b \\n c"


def test_行数上限超過は上下対称縮約し上下マーカ():
    lines = [f"L{i}" for i in range(11)]   # 0..10, hit=5
    assert clamp_lines(lines, 5, line_max=3) == \
        "…(+4上行省略)L4 \\n L5 \\n L6…(+4下行省略)"


def test_ヒット行単独が文字数上限超過はコードポイント切詰():
    assert clamp_lines(["x" * 50], 0, char_max=10) == "x" * 9 + "…"


def test_片側範囲端到達後は反対側のみ継続():
    assert clamp_lines(["A", "B", "C", "D", "E"], 1, line_max=3) == \
        "A \\n B \\n C…(+2下行省略)"
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/unit/test_snippet.py -q` → FAIL（モジュール未作成）

- [ ] **Step 3: Implement** — `src/grep_analyzer/snippet.py` を新規作成:

```python
"""snippet 切り出し（spec §9「snippet 切り出し規則」/ §7 Pro*C）。

物理行 = _phys(file_text)（0始まり）。hit = lineno-1。全関数は
走査順非依存・決定的（spec §9 golden 前提）。本ファイルのアルゴリズムは
実環境実行で検証済。
"""

SEP = " \\n "          # spec §9 区切り: U+0020 U+005C U+006E U+0020
ELL = "…"          # U+2026
LINE_MAX = 12
CHAR_MAX = 800


def _phys(file_text: str) -> list[str]:
    """物理行配列。末尾改行由来の人工空要素を1個だけ除去（spec §9 物理行定義）。"""
    lines = file_text.split("\n")
    if file_text.endswith("\n") and lines and lines[-1] == "":
        lines = lines[:-1]
    return lines


def _render(rows: list[str], top_k: int, bot_k: int) -> str:
    body = SEP.join(rows)
    if top_k:
        body = f"{ELL}(+{top_k}上行省略)" + body
    if bot_k:
        body = body + f"{ELL}(+{bot_k}下行省略)"
    return body


def clamp_lines(lines: list[str], hit: int, line_max: int = LINE_MAX,
                char_max: int = CHAR_MAX) -> str:
    """選択範囲 lines をヒット中心に縮約（spec §9「上限と切り詰め」擬似コード）。

    hit は lines 内 0 始まり index。lines は連結前に呼び出し側で
    サニタイズ＋区切り衝突エスケープ済（build_snippet が責務）。
    """
    s, e = 0, len(lines) - 1
    hit_text = lines[hit]
    out = ([hit_text[:char_max - 1] + ELL] if len(hit_text) > char_max
           else [hit_text])
    up, dn = hit - 1, hit + 1
    while True:
        if len(out) >= line_max:
            break
        progressed = False
        if up >= s:
            cand = [lines[up]] + out
            ra = (up - 1) - s + 1 if (up - 1) >= s else 0
            rb = e - dn + 1 if dn <= e else 0
            if len(cand) <= line_max and len(_render(cand, ra, rb)) <= char_max:
                out, up, progressed = cand, up - 1, True
        if len(out) >= line_max:
            break
        if dn <= e:
            cand = out + [lines[dn]]
            ra = up - s + 1 if up >= s else 0
            rb = e - (dn + 1) + 1 if (dn + 1) <= e else 0
            if len(cand) <= line_max and len(_render(cand, ra, rb)) <= char_max:
                out, dn, progressed = cand, dn + 1, True
        if not progressed:
            break
    top_k = up - s + 1 if up >= s else 0
    bot_k = e - dn + 1 if dn <= e else 0
    return _render(out, top_k, bot_k)
```

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/unit/test_snippet.py -q` → PASS（4件）

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/snippet.py tests/unit/test_snippet.py
git -c commit.gpgsign=false commit -m "feat(phase4): snippet.clamp_lines（spec §9 上限縮約・上/下マーカ・検証済）"
```

---

## Task 4: `snippet.heuristic_span` — sql/shell 決定的ヒューリスティック

**Files:** Modify `src/grep_analyzer/snippet.py`／Test `tests/unit/test_snippet.py`

> 重要修正: 「ヒット行自身は停止判定対象外。1行移動してから移動先が境界なら**その行を含めて**停止」（spec §9・検証済）。

- [ ] **Step 1: Write the failing test** — `tests/unit/test_snippet.py` に追記:

```python
from grep_analyzer.snippet import heuristic_span


def test_sql_whereから上下を句_文末境界まで():
    lines = ["SELECT * FROM t", "WHERE a = 1", "  AND b = 2",
             "  AND c = 3;", "ORDER BY a"]
    assert heuristic_span(lines, 2, "sql") == (1, 3)


def test_shell_文終端fiで停止():
    lines = ["if [ $x -eq 1 ]; then", "  echo hi", "fi", "next"]
    assert heuristic_span(lines, 1, "shell") == (0, 2)


def test_境界未検出でも有限():
    s, e = heuristic_span(["x = ("] + ["  + 1"] * 50, 0, "sql")
    assert (e - s + 1) <= 12
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/unit/test_snippet.py -q -k heuristic or whereから or 文終端fi or 境界未検出` → FAIL

- [ ] **Step 3: Implement** — `src/grep_analyzer/snippet.py` 冒頭 import に `import re` と `from grep_analyzer.chase import mask_literals` を追加し、追記:

```python
import re
from grep_analyzer.chase import mask_literals

_SQL_CLAUSE = re.compile(
    r"\b(WHERE|SET|VALUES|SELECT|FROM|GROUP\s+BY|ORDER\s+BY|HAVING)\b", re.I)
_SH_END = re.compile(r"(?:^|\s)(fi|done|esac|breaksw)\b|;")


def _balanced(t: str) -> bool:
    d = 0
    for c in t:
        if c in "([{":
            d += 1
        elif c in ")]}":
            d -= 1
    return d == 0 and t.count("'") % 2 == 0 and t.count('"') % 2 == 0


def heuristic_span(lines: list[str], hit: int, language: str) -> tuple[int, int]:
    """sql/shell の決定的境界（spec §9）。mask_literals を行ごと適用し誤爆防止。

    ヒット行自身は停止判定しない。各方向1行ずつ移動し、移動先が
    停止条件（行末\\ 無・括弧/クオートバランス・SQL は ; か句境界 /
    shell は ;/fi/done/esac/breaksw）ならその行を含めて停止。heredoc は
    mask 非対応＝§8.4 境界、LINE_MAX で必ず有限停止。
    """
    m = [mask_literals(language, ln) for ln in lines]

    def stop(i: int) -> bool:
        x = m[i]
        if x.rstrip().endswith("\\"):
            return False
        if not _balanced(x):
            return False
        if language == "sql":
            return x.rstrip().endswith(";") or bool(_SQL_CLAUSE.search(x))
        return bool(_SH_END.search(x))

    s = hit
    for _ in range(LINE_MAX - 1):
        if s == 0:
            break
        s -= 1
        if stop(s):
            break
    e = hit
    for _ in range(LINE_MAX - 1):
        if e == len(lines) - 1:
            break
        e += 1
        if stop(e):
            break
        if (e - s + 1) >= LINE_MAX:
            break
    return s, e
```

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/unit/test_snippet.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/snippet.py tests/unit/test_snippet.py
git -c commit.gpgsign=false commit -m "feat(phase4): snippet.heuristic_span（spec §9・ヒット行非停止・検証済）"
```

---

## Task 5: `snippet.ts_span` — java/c tree-sitter ノード選択（段1/段2・括弧AST・ERROR検出）

**Files:** Modify `src/grep_analyzer/classifiers/ts_classifier.py`・`src/grep_analyzer/snippet.py`／Test `tests/unit/test_snippet.py`

> 重要修正: `_paren_span` は AST の `parenthesized_expression` 子（文字列内括弧に頑健）／for は `(`〜最終 `)` トークン。ERROR/MISSING は祖先まで `has_error`/`is_missing` 判定（検証済）。

- [ ] **Step 1: Write the failing test** — `tests/unit/test_snippet.py` に追記:

```python
from grep_analyzer.snippet import ts_span


def test_java_単純文は当該statement物理行スパン():
    assert ts_span("java", "class A {\n  int x =\n    1 + 2;\n}\n", 2) == (1, 2)


def test_java_if条件部のみ本体非包含():
    src = "class A { void m(int s){\n  if (s\n      == 1) {\n    g();\n  }\n}}\n"
    assert ts_span("java", src, 2) == (1, 2)


def test_同一行複数statementは行頭statement_列非依存():
    assert ts_span("java", "class A { void m(){\n a(); b(); c();\n}}\n", 2) == (1, 1)


def test_if条件に文字列内括弧があっても条件部のみ():
    src = ('class A{ void m(String s){\n if (s.equals(")")\n'
           '   || s.isEmpty()) {\n  g();\n }\n}}\n')
    assert ts_span("java", src, 2) == (1, 2)


def test_parse不能はNone():
    assert ts_span("java", "@@@@@\n", 1) is None


def test_無関係エラーがあっても健全行はスパン維持_祖先遡上しない():
    # 3行目のみ破損。2行目の宣言は健全 → None でなくその行スパン
    assert ts_span("java", "class A{\n int ok = 1;\n void @@@ broken\n}\n", 2) \
        == (1, 1)


def test_選択文の内部にエラーがあればNone():
    assert ts_span("c", "int f(){\n int x = (1 +\n}\n", 2) is None


def test_proc_非EXEC_C文はmask後にCノード規則():
    # 生 EXEC が C パースを壊さない（mask_exec_sql 後・行番号保存）
    assert ts_span("proc", "int g = 1\n  + 2;\nEXEC SQL SELECT 1 ;\n", 1) \
        == (0, 1)
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/unit/test_snippet.py -q -k ts_span or 単純文 or if条件部 or 同一行複数 or 文字列内括弧 or parse不能` → FAIL

- [ ] **Step 3: ts_classifier に公開ヘルパ追加** — `src/grep_analyzer/classifiers/ts_classifier.py` に追記（既存不変）:

```python
def parse_tree(language: str, source: str):
    """snippet 用: ソースを parse し root_node を返す（lang は "java"/"c"）。"""
    return _parser(language).parse(source.encode("utf-8")).root_node


def node_at_line(root, lineno: int):
    """snippet 用公開ラッパ。lineno は1始まり（_node_at_line 互換・内部で-1）。"""
    return _node_at_line(root, lineno)
```

- [ ] **Step 4: snippet.ts_span 実装** — `src/grep_analyzer/snippet.py` に追記:

```python
from grep_analyzer.classifiers.ts_classifier import node_at_line, parse_tree
from grep_analyzer.proc_preprocess import mask_exec_sql

_GRAN_JAVA = {"if_statement", "while_statement", "for_statement",
              "switch_expression", "switch_statement",
              "try_statement", "try_with_resources_statement",
              "local_variable_declaration", "field_declaration",
              "return_statement", "expression_statement"}
_GRAN_C = {"if_statement", "while_statement", "for_statement",
           "switch_statement", "case_statement", "declaration",
           "expression_statement", "return_statement"}
_PAREN_ONLY = {"if_statement", "while_statement", "switch_statement",
               "switch_expression", "for_statement"}
_STMT = {"expression_statement", "declaration", "local_variable_declaration",
         "field_declaration", "return_statement"}
_BLOCK = {"block", "compound_statement", "program", "translation_unit",
          "method_declaration", "function_definition",
          "constructor_declaration"}


def _paren_span(node) -> tuple[int, int]:
    """spec §9 表「( 〜対応 ) の物理行スパン」。AST 子で取得（文字列内括弧に頑健）。"""
    for ch in node.children:
        if ch.type == "parenthesized_expression":
            return (ch.start_point[0], ch.end_point[0])
    lp = next((c for c in node.children if c.type == "("), None)
    rps = [c for c in node.children if c.type == ")"]
    if lp is not None and rps:
        return (lp.start_point[0], rps[-1].end_point[0])
    return (node.start_point[0], node.end_point[0])


def _err(node) -> bool:
    """spec §9 v9: ERROR/MISSING 判定は**選択ノードの部分木のみ**（祖先遡上
    しない＝ファイル内の無関係なエラーで健全行を捨てない・§10.3 部分木継続）。
    `has_error` は子孫包含の真偽（py-tree-sitter 0.21）。"""
    return node.is_missing or node.type == "ERROR" or node.has_error


def ts_span(language: str, file_text: str, lineno: int):
    """java/c 選択範囲 [s,e]（0始まり物理行）。取れなければ None（→fallback）。

    spec §9 段1（node_at_line=最小内包葉・列非依存）→段2（.parent 上昇で
    粒度表へ昇格／block 等到達は直近 statement／無ければ None）。proc は
    生 EXEC が C パースを壊すため mask_exec_sql 後を解析（行番号保存）。
    ERROR/MISSING は**確定した選択ノードの部分木のみ**で判定。
    """
    lang = "c" if language in ("c", "proc") else "java"
    src = mask_exec_sql(file_text) if language == "proc" else file_text
    try:
        root = parse_tree(lang, src)
    except Exception:
        return None
    n = node_at_line(root, lineno)
    if n is None:
        return None
    gran = _GRAN_JAVA if lang == "java" else _GRAN_C
    last_stmt = None
    cur = n
    while cur is not None:
        t = cur.type
        if t in _STMT:
            last_stmt = cur
        if t in gran:
            if _err(cur):
                return None
            if t in _PAREN_ONLY:
                return _paren_span(cur)
            return (cur.start_point[0], cur.end_point[0])
        if t in _BLOCK:
            if last_stmt is None or _err(last_stmt):
                return None
            return (last_stmt.start_point[0], last_stmt.end_point[0])
        cur = cur.parent
    if last_stmt is None or _err(last_stmt):
        return None
    return (last_stmt.start_point[0], last_stmt.end_point[0])
```

- [ ] **Step 5: Run & commit** — `python -m pytest tests/unit/test_snippet.py -q` → PASS。本コードは実環境（py-tree-sitter 0.21・tree-sitter-java/c）で全 PASS 検証済（健全行＋無関係エラー混在で span 維持・full garbage で None・proc 非EXEC で C span・選択文内エラーで None）。版差調整は不要。

```bash
git add src/grep_analyzer/classifiers/ts_classifier.py src/grep_analyzer/snippet.py tests/unit/test_snippet.py
git -c commit.gpgsign=false commit -m "feat(phase4): snippet.ts_span（段1/段2・括弧AST・ERROR検出・検証済）"
```

---

## Task 6: `proc_preprocess.exec_spans` ＋ `snippet.proc_exec_span`（spec §7 Crit-1）

**Files:** Modify `src/grep_analyzer/proc_preprocess.py`・`src/grep_analyzer/snippet.py`／Test `tests/unit/test_proc_preprocess.py`・`tests/unit/test_snippet.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_proc_preprocess.py` に追記:

```python
from grep_analyzer.proc_preprocess import exec_spans


def test_文字列内セミコロンで誤切断しない():
    src = "int x;\nEXEC SQL INSERT INTO t\n  VALUES (';', :y) ;\nint z;\n"
    assert exec_spans(src) == [(1, 2)]


def test_複数EXEC区間とEND_EXEC():
    src = "EXEC SQL A ;\nmid;\nEXEC ORACLE OPTION\nEND-EXEC\n"
    assert exec_spans(src) == [(0, 0), (2, 3)]
```

`tests/unit/test_snippet.py` に追記:

```python
from grep_analyzer.snippet import proc_exec_span


def test_proc_exec_spanは原ソース行スパン():
    src = "int x;\nEXEC SQL SELECT 1\n  INTO :a FROM dual ;\n"
    assert proc_exec_span(src, 2) == (1, 2)
    assert proc_exec_span(src, 1) is None
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/unit/test_proc_preprocess.py tests/unit/test_snippet.py -q -k exec_span or 文字列内セミ or 複数EXEC or 原ソース行` → FAIL

- [ ] **Step 3: proc_preprocess に exec_spans 追加** — `src/grep_analyzer/proc_preprocess.py` に追記（既存不変）:

```python
import re as _re
from grep_analyzer.chase import _MASK_SPECS

_PROC_LIT_RE = _re.compile("|".join(_MASK_SPECS["proc"]), _re.DOTALL)


def _blank_literals(source: str) -> str:
    return _PROC_LIT_RE.sub(
        lambda m: "".join(c if c == "\n" else " " for c in m.group(0)), source)


def exec_spans(source: str) -> list[tuple[int, int]]:
    """EXEC SQL/ORACLE 区間を (start_line, end_line)（0始まり）で返す。

    リテラル・コメント空白化コピー上で _EXEC_RE を走らせ文字列内 ;/
    END-EXEC の誤切断を防ぐ（spec §7 v9 Crit-1）。空白化は長さ保存
    のため原ソース行へ正しく写像できる。
    """
    masked = _blank_literals(source)
    return [(source.count("\n", 0, m.start()), source.count("\n", 0, m.end()))
            for m in _EXEC_RE.finditer(masked)]
```

- [ ] **Step 4: snippet.proc_exec_span 追加** — `src/grep_analyzer/snippet.py` に追記:

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

- [ ] **Step 5: Run & commit** — `python -m pytest tests/unit/test_proc_preprocess.py tests/unit/test_snippet.py -q` → PASS（既存 proc_preprocess テストも不変で PASS）

```bash
git add src/grep_analyzer/proc_preprocess.py src/grep_analyzer/snippet.py tests/unit/test_proc_preprocess.py tests/unit/test_snippet.py
git -c commit.gpgsign=false commit -m "feat(phase4): exec_spans/proc_exec_span（spec §7 v9 Crit-1・検証済）"
```

---

## Task 7: `snippet.build_snippet` — ディスパッチ＋フォールバック＋サニタイズ規約②

**Files:** Modify `src/grep_analyzer/snippet.py`／Test `tests/unit/test_snippet.py`

> spec §9 サニタイズ規約①②を本文コードに具体化（前タスク Self-Review 補完を昇格）。

- [ ] **Step 1: Write the failing test** — `tests/unit/test_snippet.py` に追記:

```python
from grep_analyzer.snippet import build_snippet


def test_java_複数行宣言を1セルへ連結():
    src = "class A {\n  int x =\n    1 + 2;\n}\n"
    assert build_snippet("java", "bourne", src, 2) == "  int x = \\n     1 + 2;"


def test_java_if条件行スパン_行末ブレース同居_本体後続行非包含():
    # ts_span (1,2)。行単位切出のため行2末尾の ` {` は同一物理行ゆえ含む。
    # 本体 g(); 等の後続行は非包含（spec §9 表）。
    src = "class A{ void m(int s){\n  if (s\n      == 1) {\n    g();\n  }\n}}\n"
    assert build_snippet("java", "bourne", src, 2) == "  if (s \\n       == 1) {"


def test_sql_複数条件whereを連結():
    src = "SELECT *\nFROM t\nWHERE a=1\n  AND b=2;\n"
    assert "WHERE a=1 \\n   AND b=2;" in build_snippet("sql", "bourne", src, 3)


def test_proc_EXEC区間は原ソース行():
    src = "int x;\nEXEC SQL SELECT 1\n  INTO :a FROM dual ;\nint z;\n"
    assert build_snippet("proc", "bourne", src, 2) == \
        "EXEC SQL SELECT 1 \\n   INTO :a FROM dual ;"


def test_parse不能javaは最後ヒット1行():
    assert build_snippet("java", "bourne", "@@@@@\n", 1) == "@@@@@"


def test_区切り衝突はバックスラッシュ二重化_サニタイズ後():
    # ソース行に ' \n ' 4文字並びが出現 → \ を \\ へ。タブは空白化(規約①)
    src = "a \\n b\tc\n"
    assert build_snippet("shell", "bourne", src, 1) == "a \\\\n b c"
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/unit/test_snippet.py -q -k build_snippet or 複数行宣言 or 複数条件where or EXEC区間は原 or parse不能java or 区切り衝突` → FAIL

- [ ] **Step 3: Implement** — `src/grep_analyzer/snippet.py` に追記（`from grep_analyzer.tsv import _sanitize` を import 群へ追加）:

```python
from grep_analyzer.tsv import _sanitize


def _escape_sep(line: str) -> str:
    """spec §9 サニタイズ規約②: 行中の区切り列 ' \\n '(U+0020 005C 006E 0020)
    と同一4文字並びの \\(U+005C) を \\\\ へ二重化（区切りと本文の曖昧化防止）。"""
    return line.replace(SEP, " \\\\n ")


def build_snippet(language: str, dialect: str, file_text: str,
                  lineno: int) -> str:
    """spec §9 snippet 切り出し規則のエントリ。確定済み1セル文字列を返す。

    java/c: ts_span→無ければ **ヒット1行**（spec §9 フォールバック: java/c
      に sql/shell ヒューリスティックは適用しない＝C へ shell 規則を当てる
      非整合を排除）。
    proc: EXEC 区間=proc_exec_span／区間外=ts_span("proc",..)（内部で
      mask_exec_sql 後 C 解析）→ いずれも None なら ヒット1行（spec §7/§9）。
    sql/shell: heuristic_span（AST 非使用＝これが (1) 相当）。
    `dialect` は将来 cshell 境界用の予約引数（v1 未使用・呼出互換のため受領）。
    連結前に各行へ規約①_sanitize→②_escape_sep を適用し clamp_lines。
    """
    lines = _phys(file_text)
    hit = lineno - 1
    if hit < 0 or hit >= len(lines):
        return ""
    span = None
    if language in ("java", "c"):
        span = ts_span(language, file_text, lineno)
    elif language == "proc":
        span = proc_exec_span(file_text, lineno)
        if span is None:
            span = ts_span("proc", file_text, lineno)
    elif language in ("sql", "shell"):
        span = heuristic_span(lines, hit, language)
    if span is None:
        span = (hit, hit)
    s, e = span
    s = max(0, min(s, hit))
    e = min(len(lines) - 1, max(e, hit))
    body = [_escape_sep(_sanitize(x)) for x in lines[s:e + 1]]
    return clamp_lines(body, hit - s)
```

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/unit/test_snippet.py -q` → PASS（全 snippet unit）

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/snippet.py tests/unit/test_snippet.py
git -c commit.gpgsign=false commit -m "feat(phase4): build_snippet＋サニタイズ規約①②（spec §9・検証済）"
```

---

## Task 8: pipeline/fixedpoint 配線＋`file` 絶対化（書込直前最終変換）

**Files:** Modify `src/grep_analyzer/pipeline.py`・`src/grep_analyzer/fixedpoint.py`／Test `tests/unit/test_pipeline.py`

> 架構: `file` 絶対化は Hit 構築でなく **finalize 直前の最終変換**。fixedpoint/Occurrence/graph/chain/diagnostics は relpath のまま（spec §9/§10.3 層分離）。

- [ ] **Step 1: Write the failing test** — `tests/unit/test_pipeline.py` に追記:

```python
from pathlib import Path
from grep_analyzer.pipeline import run


def test_file列は絶対_chainは相対_snippetは構文単位(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text(
        'class A {\n  static final String K =\n    "K";\n}\n', "utf-8")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "K.grep").write_text("A.java:2:  static final String K =\n", "utf-8")
    out = tmp_path / "out"
    assert run(inp, out, src) == 0
    cells = (out / "K.tsv").read_text("utf-8-sig").splitlines()[1].split("\t")
    resolved = str(Path(src).resolve())
    assert cells[2] == f"{resolved}/A.java"                  # file 絶対
    assert cells[9] == "K@A.java:2"                           # chain 相対維持
    assert cells[10] == '  static final String K = \\n     "K";'  # snippet 多行
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/unit/test_pipeline.py -q -k file列は絶対` → FAIL

- [ ] **Step 3: fixedpoint の indirect snippet を build_snippet へ** — `src/grep_analyzer/fixedpoint.py`:

冒頭 import 群に追加:
```python
from grep_analyzer.snippet import build_snippet
```
`fixedpoint.py` の **`indirect.append(Hit(...))` ブロック（`snippet=line` を含む唯一の箇所）** を次へ変更（`file=c.relpath` は**不変**、`snippet` のみ差替。`text, language, dialect = meta_of[c.relpath]` は同ブロック直前で取得済＝そのまま使用）:

```python
                indirect.append(Hit(
                    keyword=keyword, language=language, file=c.relpath,
                    lineno=c.lineno, ref_kind=_REF_KIND[kind], category=cat,
                    category_sub="", usage_summary=f"{cat} ({language})",
                    via_symbol=c.symbol, chain=chain,
                    snippet=build_snippet(language, dialect, text, c.lineno),
                    encoding=enc + (" 要確認" if replaced else ""),
                    confidence=conf))
```

- [ ] **Step 4: pipeline で snippet 配線＋finalize 直前に file 絶対化** — `src/grep_analyzer/pipeline.py`:

冒頭 import に追加:
```python
from dataclasses import replace
from grep_analyzer.snippet import build_snippet
```
direct Hit 構築の `snippet=content,` を差替（`file=rel` は**不変**）:
```python
                snippet=build_snippet(language, dialect, file_text, lineno),
```
`run()` の `indirect = run_fixedpoint(...)` と `output_writer.finalize(...)` の2行を次へ置換:
```python
        indirect = run_fixedpoint(hits, Path(source_root), opts, diag, files=files)
        src_abs = str(Path(source_root).resolve())
        rows = [replace(h, file=f"{src_abs}/{h.file}") for h in hits + indirect]
        output_writer.finalize(output_dir, keyword, rows, opts)
```

- [ ] **Step 5: Run & commit** — `python -m pytest tests/unit/test_pipeline.py -q -k file列は絶対` → PASS。`python -m pytest tests/unit/test_fixedpoint.py -q`（indirect の chain が relpath 維持・snippet が多行＝既存 expected は Task 12 で再生成、ここは挙動確認）。

```bash
git add src/grep_analyzer/pipeline.py src/grep_analyzer/fixedpoint.py tests/unit/test_pipeline.py
git -c commit.gpgsign=false commit -m "feat(phase4): pipeline/fixedpoint snippet配線＋file絶対化を書込直前最終変換へ（層分離・spec §9/§10.3）"
```

---

## Task 9: golden 比較ハーネス改修（spec §11 v9・opts 配線込み）

**Files:** Modify `tests/golden/test_golden.py`

> opts（follow_symlinks/output_encoding/resume）配線を**最初から**含める（Task 11 で再書換しない）。

- [ ] **Step 1: ハーネスを全置換** — `tests/golden/test_golden.py`:

```python
"""合成代表ツリーの TSV 完全一致による回帰検出（spec §11 v9 機構）。"""

import dataclasses
import json
from pathlib import Path

from grep_analyzer import resume
from grep_analyzer.pipeline import _default_opts, run


def _opts_for(case: Path):
    """ケース任意 opts.json を _default_opts へ反映（無ければ既定）。"""
    cfg = case / "opts.json"
    o = _default_opts()
    if cfg.is_file():
        d = json.loads(cfg.read_text("utf-8"))
        repl = {}
        if "follow_symlinks" in d:
            repl["follow_symlinks"] = d["follow_symlinks"]
        if "output_encoding" in d:
            repl["output_encoding"] = d["output_encoding"]
        if "resume" in d:
            repl["resume"] = d["resume"]
        o = dataclasses.replace(o, **repl)
    return o


def test_合成ケースのTSVが期待値と完全一致する(golden_case, tmp_path):
    out = tmp_path / "out"
    opts = _opts_for(golden_case)
    rc = run(input_dir=golden_case / "input", output_dir=out,
             source_root=golden_case / "src", opts=opts)
    assert rc == 0
    sr = str(Path(golden_case / "src").resolve())            # spec §11(b)
    for expected in sorted((golden_case / "expected").glob("*.tsv")):
        keyword = expected.stem
        mpath = out / f"{keyword}.manifest.json"
        enc = "utf-8-sig"
        if mpath.is_file():                                  # spec §11(a)
            enc = json.loads(mpath.read_text("utf-8")).get(
                "encoding", "utf-8-sig")
        actual = (out / expected.name).read_text(enc)
        # spec §11(b): 各データ行ごとに先頭1回置換（ファイル全体1回は禁止
        # ＝2行目以降が絶対パスで残り環境依存になる。chain_multipath 等
        # 複数 file 行ケースで顕在）。file 列は各行で snippet より前なので
        # 行内の最初の SR+"/" が file セル。
        actual = "".join(
            (ln.replace(sr + "/", "{SOURCE_ROOT}/", 1)
             if (sr + "/") in ln else ln)
            for ln in actual.splitlines(keepends=True))
        assert actual == expected.read_text("utf-8-sig"), expected.name
    cfg = golden_case / "opts.json"
    if cfg.is_file() and json.loads(
            cfg.read_text("utf-8")).get("assert_resume_complete"):
        for expected in sorted((golden_case / "expected").glob("*.tsv")):  # §11(d)
            assert resume.is_complete(out, expected.stem, opts)
```

注: `_default_opts` は `pipeline.py` のモジュール関数（実在）。`EngineOptions` は frozen dataclass のため `dataclasses.replace` で上書き。`output_writer.finalize` は resume 無効でも manifest を生成するため `is_complete` 判定可能（spec §10.3）。

- [ ] **Step 2: Run（expected 旧形式のため全 FAIL が想定・クラッシュ無し）** — `python -m pytest tests/golden -q` → 多数 FAIL（AssertionError のみ。例外/収集エラーが出たらハーネス不備として修正）。これは Task 10 で再生成するため**想定どおり**。

- [ ] **Step 3: Commit**

```bash
git add tests/golden/test_golden.py
git -c commit.gpgsign=false commit -m "test(phase4): golden 比較を spec §11 v9 機構へ（{SOURCE_ROOT}/manifest enc/opts/resume assert）"
```

---

## Task 10: 既存 golden expected 全件再生成（影響3要因別レビュー・spec §15 手順4）

**Files:** Modify `tests/golden/cases/*/expected/*.tsv`（14 ケース）

- [ ] **Step 1: 影響範囲を事前 grep で確定（spec §15 手順4 の最初のタスク）**

```bash
ls tests/golden/cases
grep -rl "	indirect" tests/golden/cases/*/expected | sort   # indirect 含む(6想定)
grep -rl "	direct	\|	indirect\|snippet" tests/unit tests/integration | sort
```
記録: 全 expected 一覧、indirect 含む6ケース、影響 unit/integration。

- [ ] **Step 2: opts 対応の再生成スクリプトで expected を更新**

```bash
python - <<'PY'
import json, pathlib, dataclasses, shutil
from grep_analyzer.pipeline import _default_opts, run
base = pathlib.Path("tests/golden/cases")
for case in sorted(base.iterdir()):
    if not (case/"input").is_dir(): continue
    o = _default_opts()
    cfg = case/"opts.json"
    if cfg.is_file():
        d = json.loads(cfg.read_text("utf-8"))
        repl = {k: d[k] for k in ("follow_symlinks","output_encoding","resume") if k in d}
        o = dataclasses.replace(o, **repl)
    out = case/".regen"
    run(input_dir=case/"input", output_dir=out, source_root=case/"src", opts=o)
    sr = str((case/"src").resolve())
    for tsv in (case/"expected").glob("*.tsv"):
        m = out/f"{tsv.stem}.manifest.json"
        enc = json.loads(m.read_text("utf-8")).get("encoding","utf-8-sig") if m.is_file() else "utf-8-sig"
        raw = (out/tsv.name).read_text(enc)
        txt = "".join((ln.replace(sr+"/","{SOURCE_ROOT}/",1) if (sr+"/") in ln else ln)
                      for ln in raw.splitlines(keepends=True))   # 行単位（spec §11(b)）
        tsv.write_text(txt, "utf-8-sig")
    shutil.rmtree(out)
print("regenerated")
PY
```

- [ ] **Step 3: 3要因別に diff をレビュー（spec §15 手順4・正本=diff）**

`git diff tests/golden/cases` を全件確認し、各ケースの変化を **A:file 絶対化（全件・`file` 列が `{SOURCE_ROOT}/<rel>`）／B:snippet 多行化（snippet 列が構文単位）／C:ソート順（indirect 含む6件で chain 集約により行順変化したもの）** の3要因で**すべて説明できること**を確認。説明不能な変化（＝バグ）があれば該当 Task（3-8）へ戻る。spec §9「Phase 影響」と整合（行順変化/byte のみ変化の内訳を記述）。

- [ ] **Step 4: golden green** — `python -m pytest tests/golden -q` → **14 passed**（新ベースライン）

- [ ] **Step 5: Commit（3要因の説明文をコミットメッセージへ）**

```bash
git add tests/golden/cases
git -c commit.gpgsign=false commit -m "test(phase4): golden expected 全件再生成（A:file絶対/B:snippet多行/C:ソート順・spec §15 手順4・意図的Inv-1再ベースライン）"
```

---

## Task 11: spec §11 v9 名指し新規 golden ケース（src/input/expected を手作成）

**Files:** Create `tests/golden/cases/{multiline_if,multiline_where,sameline_stmt,proc_exec_snippet,parsefail_fallback,sanitize_ctrl,symlink_dedup,cp932_resume}/`

> 反射的 regen で alarm を殺さないため、各ケースは **src/input を手作成し、期待 snippet/file セルを spec §9 ロジックから手計算**。再生成スクリプトは整形一致確認にのみ使い、手計算値と一致することを必ず目視。

- [ ] **Step 1: 各ケースを作成（最小代表・手計算期待つき）**

各ケース `input/<kw>.grep`・`src/<file>`・`expected/<kw>.tsv`（先頭 BOM＋ヘッダ行は既存 golden と同形式）。**全新規ケースは単一 part（`max_rows_per_part` 未満）かつ cp932 ラウンドトリップ不可逆文字を含めない**（`cp932_resume` 含む。`txt.encode("cp932").decode("cp932")==txt` を Step2 で確認）。手計算の要点（snippet 列・確定値・実環境実行で検証済）:

- `multiline_if/`：`src/A.java`= `class A{ void m(int s){\n  if (s\n      == 1) {\n    g();\n  }\n}}\n`、`input` ヒット行=2。期待 snippet=`  if (s \n       == 1) {`（ts_span (1,2)＝条件**行**スパン。行2末尾 ` {` は同一物理行ゆえ含む／本体 `g();` 後続行は非包含＝spec §9 表）。
- `multiline_where/`：`src/q.sql`= `SELECT *\nFROM t\nWHERE a=1\n  AND b=2;\n`、ヒット=3。期待 snippet（heuristic_span→(1,3)）=`FROM t \n WHERE a=1 \n   AND b=2;`。
- `sameline_stmt/`：`src/A.java`= `class A{ void m(){\n a(); b(); c();\n}}\n`、ヒット=2。期待 snippet=` a(); b(); c();`（行頭 statement＝ts_span (1,1)・§8.4 既知粒度）。
- `proc_exec_snippet/`：`src/p.pc`= `int x;\nEXEC SQL INSERT INTO t\n  VALUES (';', :y) ;\nint z;\n`、ヒット=2。期待 snippet=`EXEC SQL INSERT INTO t \n   VALUES (';', :y) ;`（区間[1,2]・文字列内 ; で誤切断しない）。
- `parsefail_fallback/`：`src/B.java`= `@@@@@\n`、ヒット=1。期待 snippet=`@@@@@`（ts_span None→java/c フォールバック=ヒット1行＝spec §9・shell ヒューリスティック不適用）。
- `sanitize_ctrl/`：`src/s.sh`= `a \\n b\tc\n`（` \n ` 4文字並び＋タブを含む 1 行）、ヒット=1。期待 snippet=`a \\\\n b c`（規約①タブ→空白・②`\`二重化）。
- `symlink_dedup/`：`opts.json`=`{"follow_symlinks": true}`。`src/` に実体 `a.sh` と同一実体への symlink を含む構成（dedup 発火）。期待 `file`=`{SOURCE_ROOT}/<代表relpath>`（§8.2 relpath 辞書順で先勝ち）。
- `cp932_resume/`：`opts.json`=`{"output_encoding":"cp932","resume":true,"assert_resume_complete":true}`。複数行 snippet を生む `src`（日本語コメント可・cp932 表現可）。期待 TSV は cp932 で保存し `{SOURCE_ROOT}` 正規化。`assert_resume_complete` で `is_complete==True`（区切り ` \n ` が ASCII で round-trip＝sha 一致）。

- [ ] **Step 2: 期待値の手計算と再生成の一致確認**

各ケースを Task 10 スクリプトの単一ケース版で生成し、生成 `expected` の snippet/file セルが **Step 1 の手計算値と一致**することを目視。一致しなければ実装（Task 3-8）のバグ＝戻る。一致したら手計算側を正として採用。

- [ ] **Step 3: Run & commit** — `python -m pytest tests/golden -q` → 全 green（既存14＋新規8）

```bash
git add tests/golden/cases
git -c commit.gpgsign=false commit -m "test(phase4): spec §11 v9 名指し新規 golden 8件（手作成src/input＋手計算expected）"
```

---

## Task 12: unit/integration 再生成＋Inv-1 新ベースライン＋perf 再較正

**Files:** Modify `tests/unit/*.py`,`tests/integration/*.py`・`docs/superpowers/plans/phase0-gate-result.md`・`src/grep_analyzer/budget.py`

- [ ] **Step 1: 影響 unit/integration を再生成**

`python -m pytest tests/unit tests/integration -q` で落ちたもののうち「`file`/`snippet`/順序のリテラル期待」を新規約へ最小修正（ロジック assert・Hit 構築は不変）。主対象 `test_pipeline.py`/`test_fixedpoint.py`/`test_output_writer.py`/`test_encoding_wiring.py`。各修正は「A:file 絶対化／B:snippet 多行化／C:ソート順」のどれに起因するか diff コメントで説明できること。

- [ ] **Step 2: Inv-1 新ベースライン確立** — `python -m pytest -q` → 全 green（golden 14＋新規8＋unit/integration）。これが v8/v9 後の新 Inv-1。

- [ ] **Step 3: phase0-gate-result.md に再ベースライン注記（凍結記録は書き換えない）**

```bash
grep -n "Inv-1" docs/superpowers/plans/phase0-gate-result.md   # 記録節の現在行を同定
```
同定した Inv-1 記録節（spec §15 が凍結参照する L312-316／L385-389 相当）の**末尾に追記のみ**（既存行は改変しない）:

```markdown
> **[v8/v9 再ベースライン注記 2026-05-18]** 上記 Inv-1 byte 不変は v7 スキーマ時点の凍結証跡（数値はテスト件数等を含み spec §15 が「byte 数値として再記述しない」と明記）。spec v9 §15 フェーズ4（意図的破壊的スキーマ変更）により golden/unit/integration expected を A:file絶対化・B:snippet多行化・C:ソート順の3要因で再生成し、v8/v9 後の新ベースラインで Inv-1 を再確立した（本計画 Task 10/12）。
```

- [ ] **Step 4: perf/_ITEMS_PER_MB 再較正（非ゲート・spec §8.2/§11）**

`python -m pytest tests/perf -q -m perf` を実行。`docs/superpowers/plans/phase3-perf-report.md` の較正方式に従い、計測 bytes/item 中央値から `src/grep_analyzer/budget.py` の `_ITEMS_PER_MB` を**一度だけ**更新（perf 証跡を同 report に追記）。非ゲートのため CI 停止しない。snippet 多行化で1レコード最大バイト増＝過小評価是正が目的。

- [ ] **Step 5: 最終確認とコミット** — `python -m pytest -q && python -m grep_analyzer --help` → 全 green・exit 0

```bash
git add tests src docs/superpowers/plans/phase0-gate-result.md
git -c commit.gpgsign=false commit -m "test(phase4): unit/integration 再生成＋Inv-1 新ベースライン＋_ITEMS_PER_MB 再較正（spec §15）"
```

---

## Self-Review（spec v9 との突合）

- **§9 file 絶対化**: Task 8（finalize 直前 `dataclasses.replace` で `f"{resolve()}/rel"`・**Hit 構築・fixedpoint・chain・diagnostics は relpath 維持**＝層分離）／Task 9-10（`{SOURCE_ROOT}` 逆置換ハーネス・全 expected 移行）。✓ 反復1 Critical#1（fixedpoint seed relpath 破壊）解消＝絶対化を出力境界へ移動。
- **§9 ソートキー**: Task 1（13要素キー・全順序）。✓
- **§9 サニタイズ規約①②**: Task 2（①対象集合）＋Task 7（②`_escape_sep`＋各行 `_sanitize` を build_snippet 本文に具体実装＋衝突テスト）。✓ 反復1 Critical（規約②未具体化・未定義 escape_sep）解消。
- **§9 snippet（段1/段2・括弧AST本体非包含・同一行=行頭・フォールバック順・上限縮約上/下マーカ・ヒット行単独切詰）**: Task 3-7、全アルゴリズム実環境実行検証済。✓ 反復1 Critical（clamp マーカ書式/off-by-one/_measure、heuristic ヒット行早期停止、split 末尾空行、_paren_span 文字列内括弧、ts_span ERROR 未検出）すべて修正・検証。
- **§7 Pro\*C EXEC（リテラル空白化検出・原ソース span）**: Task 6。✓
- **§8.2 relpath 辞書順代表 / §10.3 diagnostics relpath**: Task 8（walk.py/diagnostics 不変・絶対化は file 列出力のみ）。✓
- **§11 比較機構・名指し回帰・opts**: Task 9（機構＋opts 配線を最初から）／Task 11（手作成 src/input＋手計算 expected・cp932/symlink/parsefail/proc-exec/sanitize/多行 if/where/sameline）。✓ 反復1 Important（opts 二重作業・反射 regen alarm 殺し）解消。
- **§15 フェーズ4 手順1-5・churn は意図的**: Task 10（3要因 diff レビュー）／Task 12（grep で記録節同定後の凍結注記・新ベースライン・perf 再較正具体手順）。golden 固定は本計画の成果物（着手循環なし）。✓ 反復1 Minor（phase0 行同定）解消。

プレースホルダ・未定義シンボル・型/シグネチャ不整合の走査済（`clamp_lines(lines,hit,line_max,char_max)` / `build_snippet(language,dialect,file_text,lineno)` / `ts_span`/`heuristic_span`/`exec_spans`/`proc_exec_span`/`_escape_sep` 全て定義と呼出一致）。残課題なし。

---

## Execution Handoff

実行はユーザ既定により **subagent-driven-development**（タスクごとに fresh subagent＋2段レビュー）。本計画は spec と同じ批判的AIレビューゲート（3観点×収束まで）を通してから着手する。
