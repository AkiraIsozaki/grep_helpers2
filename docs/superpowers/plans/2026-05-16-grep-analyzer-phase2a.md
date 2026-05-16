# grep_analyzer Phase 2a（不動点エンジンの正しさ・決定性コア） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 1/1.5 の direct-only 決定性基盤の上に、spec §8.1 不動点反復＋§8.3 シンボル採否（汎用 getter 横展開の構造的抑止）＋§8.2 来歴集約を実装し、多ホップ間接ヒット（`indirect:constant|var|getter|setter`）と chain 複数経路を **`--jobs` 並列でも完全決定的** に出力する。偽陽性抑止と停止性を小規模合成ツリーで実測検証し、chain 複数経路の決定性を golden で固定する。

**Architecture:** 既存 `grep_analyzer` パッケージを後方互換で拡張する。決定的コア（`dispatch`/`classifiers`/`chase`/`tsv`/`model`）は変更しない（Phase 1.5 の 78 テストは不変）。`chase.py` に分類付き抽出 `extract_chase_symbols`（`extract_var_symbols` は不変のまま再利用）を追加。新規モジュール `stoplist.py`（静的採否・getter/setter 非投入の生命線）／`automaton.py`（pyahocorasick＋識別子境界）／`walk.py`（決定的ツリー走査・symlink 重複排除）／`provenance.py`（来歴グラフ・chain 単純パス列挙）／`classify.py`（pipeline と共有する行分類）／`fixedpoint.py`（反復エンジン）を追加。`pipeline.py` は direct ヒット生成後にエンジンを呼び indirect ヒットを併合、`cli.py` に Phase 2a オプションを追加。**2b（資源 degrade：`--memory-limit` スピル・オートマトン分割多パス・`ripgrep` 一次フィルタ）と Phase 3（60GB perf・`--resume`・diagnostics 縮約・規模分割・`requirements.lock`）は本計画の範囲外**（末尾「Phase 2a の境界」）。

**Tech Stack:** Python 3.12 / pytest / `pyahocorasick==2.1.0`（Phase 2 着手ゲートで wheel 実証済み＝`phase0-gate-result.md`「Phase 2 着手ゲート（pyahocorasick G1 相当）記録」PASS）。tree-sitter/chardet は既存のまま。設計書 `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`（v7 が正）、テスト規約 `.claude/skills/writing-tests.md`、コーディング規約 `.claude/skills/coding-conventions.md` に従う（docstring/コメントは日本語、テスト名は日本語、古典学派+TDD、外部I/O境界＝ファイルのみ本物）。

**型・シグネチャ契約（全タスク共通・タスク間で不変）:**

- `chase.ChaseSymbols`（frozen dataclass）: `.constants/.vars/.getters/.setters: tuple[str, ...]`
- `chase.extract_chase_symbols(language: str, dialect: str, line: str) -> ChaseSymbols`
- `stoplist.SymbolPolicy(min_specificity: int, user_stoplist: frozenset[str], max_symbols: int)`
- `stoplist.load_stoplist(path: pathlib.Path | None) -> frozenset[str]`
- `stoplist.admit(symbols: list[str], language: str, policy: SymbolPolicy, hop: int) -> AdmissionResult`、`AdmissionResult(accepted: list[str], rejected: list[tuple[str, str]])`、reason ∈ `{"keyword","too_short","user_stoplist","capped"}`
- `automaton.build(symbols: list[str]) -> ahocorasick.Automaton | None`
- `automaton.scan_line(au, line: str) -> list[str]`（識別子境界一致シンボルの昇順ユニーク）
- `walk.walk_files(root, *, include, exclude, follow_symlinks, max_file_bytes, diag) -> Iterator[tuple[str, pathlib.Path]]`、`walk.DEFAULT_EXCLUDE: tuple[str, ...]`
- `provenance.Occurrence`（frozen）: `symbol: str, relpath: str, lineno: int`
- `provenance.ProvenanceGraph`: `add_seed(occ)` / `add_edge(parent: Occurrence, child: Occurrence)` / `chains_to(occ, max_depth: int, diag) -> list[str]`、hop 表記 `f"{symbol}@{relpath}:{lineno}"`・` -> ` 連結（spec §9）
- `classify.classify_hit(language: str, dialect: str, file_text: str, lineno: int, content: str) -> tuple[str, str]`（`(category, confidence)`）
- `fixedpoint.EngineOptions`（dataclass）: `max_depth:int, min_specificity:int, stoplist_path:Path|None, include:list[str], exclude:list[str], jobs:int, follow_symlinks:bool, max_file_bytes:int, max_symbols:int`
- `fixedpoint.run_fixedpoint(seed_hits: list[Hit], source_root: pathlib.Path, opts: EngineOptions, diag: Diagnostics) -> list[Hit]`（戻り値は indirect Hit のみ。direct は seed_hits 側）

---

## Task 0: 着手ゲート（Phase 1.5 緑＋pyahocorasick G1・コードなし）

spec §15 フェーズ2 は Phase 1（＋1.5）決定性基盤の上に積む。着手前提は (1) Phase 1.5 全テスト緑（回帰判別の基準固定。writing-tests「大量churn＝構造を疑う」）、(2) `pyahocorasick` の §4.2 G1 相当 wheel 実証 PASS（spec §15 フェーズ2 唯一の着手前提）。

- [ ] **Step 1: ベースライン全緑を確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest -q`
Expected: `78 passed`（unit / integration / golden / smoke すべて PASS、0 failed / 0 error）。78 と異なるなら着手しない（基準が動いている＝先に原因究明）。

- [ ] **Step 2: Phase 2 着手ゲート（pyahocorasick G1）PASS 記録の存在を確認**

Run: `grep -n "G1 相当判定: \*\*PASS\*\*" docs/superpowers/plans/phase0-gate-result.md`
Expected: 1 行ヒット（「Phase 2 着手ゲート（pyahocorasick G1 相当）記録」が PASS）。ヒットしなければ着手不可（spec §4.2「ゲート未充足のまま着手不可」）。

- [ ] **Step 3: pyahocorasick が現環境で import 可能か確認**

Run: `python -c "import ahocorasick, importlib.metadata as m; print(m.version('pyahocorasick'))"`
Expected: `2.1.0`。失敗（ImportError）なら `python -m pip install --no-index --find-links wheelhouse "pyahocorasick==2.1.0"`（gate doc Step2 のオフライン手順）でインストールしてから再確認。

- [ ] **Step 4: ゲート判定を記録しコミット**

`docs/superpowers/plans/phase0-gate-result.md` 末尾に「## Phase 2a 着手ゲート記録」（記録日 UTC、`78 passed`、pyahocorasick G1 PASS 参照、判定 PASS）を追記。

```bash
git add docs/superpowers/plans/phase0-gate-result.md
git commit -m "chore: Phase 2a 着手ゲート記録（78 passed / pyahocorasick G1 PASS）"
```

注: `requirements.lock`（spec §4.1）は Phase 3（配備正式化）へ送る決定済み。`--memory-limit` スピル・オートマトン分割多パス・`ripgrep` は Phase 2b。これらは本計画の着手をブロックしない（Phase 2a は pyahocorasick＋標準ライブラリ＋既存依存で完結）。

---

## Task 1: 分類付き追跡シンボル抽出 `chase.extract_chase_symbols`

**Files:**
- Modify: `src/grep_analyzer/chase.py`
- Test: `tests/unit/test_chase.py`

spec §9 ref_kind×言語表に従い、1 行から `constant/var/getter/setter` を決定的に抽出する。`extract_var_symbols` は **不変**（Phase 1.5 の `test_chase.py` 既存7テストを壊さない）。var カテゴリは `extract_var_symbols` を再利用（DRY）。getter/setter は **Java の字句のみ**（C/SQL/Shell は getter/setter 概念なし）。constant は Java `static final`／C `#define`・`const`／bourne `readonly`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_chase.py` の末尾に追記:
```python
from grep_analyzer.chase import ChaseSymbols, extract_chase_symbols


def test_Java定数とvarとgetterとsetterを分類抽出する():
    cs = extract_chase_symbols("java", "", "static final String STATUS_OK = svc.getName();")
    assert cs.constants == ("STATUS_OK",)
    assert cs.getters == ("getName",)
    cs2 = extract_chase_symbols("java", "", "int count = 0; obj.setValue(count);")
    assert cs2.vars == ("count",)
    assert cs2.setters == ("setValue",)


def test_C定義とconst定数を抽出する():
    assert extract_chase_symbols("c", "", "#define MAX_LEN 10").constants == ("MAX_LEN",)
    assert extract_chase_symbols("c", "", "const int FOO = 1;").constants == ("FOO",)
    assert extract_chase_symbols("c", "", "int n = 3;").vars == ("n",)


def test_bourneのreadonlyは定数それ以外はvar():
    assert extract_chase_symbols("shell", "bourne", "readonly CODE=1").constants == ("CODE",)
    assert extract_chase_symbols("shell", "bourne", 'NAME="x"').vars == ("NAME",)


def test_SQLとcshellはvarのみでgetterは空():
    cs = extract_chase_symbols("sql", "", "v_code := 'X';")
    assert cs.vars == ("v_code",) and cs.getters == () and cs.constants == ()
    assert extract_chase_symbols("shell", "cshell", "set CODE = 1").vars == ("CODE",)


def test_var抽出は既存extract_var_symbolsと一致する():
    # DRY 契約: var カテゴリは extract_var_symbols の再利用であることを固定。
    from grep_analyzer.chase import extract_var_symbols
    line = 'CODE="X"'
    assert list(extract_chase_symbols("shell", "bourne", line).vars) == extract_var_symbols(
        "shell", "bourne", line
    )
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_chase.py -q`
Expected: FAIL（`ImportError: cannot import name 'ChaseSymbols'`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/chase.py` の末尾に追記（既存 `extract_var_symbols` は変更しない）:
```python
from dataclasses import dataclass

# Java getter/setter は字句のみ（tree-sitter 型解決をしない＝spec §8.3）。呼出/定義どちらの
# 字句出現も同じ名称シンボルとして拾う。
_JAVA_GETSET_RE = re.compile(r"\b((?:get|set)[A-Z]\w*)\s*\(")
# Java 定数: static final ... NAME =（修飾子順は任意）。型部は貪欲に読み最後の識別子を採る。
_JAVA_CONST_RE = re.compile(
    r"\b(?:(?:public|protected|private|static|final)\s+){2,}[\w.<>\[\]]+\s+([A-Za-z_]\w*)\s*="
)
# Java var: 代入左辺の末尾識別子（== 等の比較は (?!=) で除外）。型宣言付き/再代入の双方。
_JAVA_VAR_RE = re.compile(r"(?<![=!<>])\b([A-Za-z_]\w*)\s*=(?!=)")
_C_DEFINE_RE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)")
_C_CONST_RE = re.compile(r"\bconst\b[\w\s*]*?\b([A-Za-z_]\w*)\s*=")
_C_VAR_RE = re.compile(r"(?<![=!<>])\b([A-Za-z_]\w*)\s*=(?!=)")
_BOURNE_READONLY_RE = re.compile(r"^\s*readonly\s+([A-Za-z_]\w*)=")


@dataclass(frozen=True)
class ChaseSymbols:
    """1行から抽出した追跡候補シンボル（spec §8.1/§9 ref_kind×言語）。

    constants/vars は不動点追跡集合の候補。getters/setters は §8.3 により
    横展開しない報告専用候補（fixedpoint が terminal として扱う）。
    """

    constants: tuple[str, ...] = ()
    vars: tuple[str, ...] = ()
    getters: tuple[str, ...] = ()
    setters: tuple[str, ...] = ()


def extract_chase_symbols(language: str, dialect: str, line: str) -> ChaseSymbols:
    """1行を spec §9 ref_kind×言語表に従い分類抽出する。決定的（出現順）。

    var は extract_var_symbols を再利用（DRY）。getter/setter は Java の字句のみ。
    """
    if language == "java":
        consts = tuple(m.group(1) for m in _JAVA_CONST_RE.finditer(line))
        getters = tuple(m.group(1) for m in _JAVA_GETSET_RE.finditer(line) if m.group(1)[0] == "g")
        setters = tuple(m.group(1) for m in _JAVA_GETSET_RE.finditer(line) if m.group(1)[0] == "s")
        const_set = set(consts)
        vars_ = tuple(
            v for v in (m.group(1) for m in _JAVA_VAR_RE.finditer(line)) if v not in const_set
        )
        return ChaseSymbols(consts, vars_, getters, setters)
    if language in ("c", "proc"):
        consts = tuple(m.group(1) for m in _C_DEFINE_RE.finditer(line)) + tuple(
            m.group(1) for m in _C_CONST_RE.finditer(line)
        )
        const_set = set(consts)
        vars_ = tuple(
            v
            for v in (m.group(1) for m in _C_VAR_RE.finditer(line))
            if v not in const_set and v != "const"
        )
        return ChaseSymbols(consts, vars_, (), ())
    if language == "shell" and dialect != "cshell":
        m = _BOURNE_READONLY_RE.match(line)
        if m is not None:
            return ChaseSymbols((m.group(1),), (), (), ())
    # sql / cshell / その他: var のみ（extract_var_symbols 再利用）
    return ChaseSymbols((), tuple(extract_var_symbols(language, dialect, line)), (), ())
```

- [ ] **Step 4: テストが通ることを確認（当該＋全体回帰ゼロ）**

Run: `python -m pytest tests/unit/test_chase.py -q`
Expected: PASS（既存7＋新規5）

Run: `python -m pytest -q`
Expected: 全 PASS・**0 failed / 0 error**（既存78に対し回帰ゼロ）。赤があれば commit せず Task 内で修正。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/chase.py tests/unit/test_chase.py
git commit -m "feat(chase): 分類付き追跡シンボル抽出 extract_chase_symbols（spec §8.1/§9）"
```

---

## Task 2: 静的シンボル採否ポリシー `stoplist.py`

**Files:**
- Create: `src/grep_analyzer/stoplist.py`
- Test: `tests/unit/test_stoplist.py`

spec §8.3 の静的ストップリスト（① 言語キーワード/予約語 ② 最小長 `--min-specificity` ③ ユーザ `--stoplist` ファイル）と、集合サイズ上限超過時の **決定的切り捨て**（`(発見ホップ数, 識別子長, 文字列辞書順)` 安定ソートで上限内採用）。動的トップN は v1 スコープ外（spec §8.3/§14）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_stoplist.py` を新規作成:
```python
"""静的シンボル採否ポリシーの仕様（spec §8.3）。"""

from grep_analyzer.stoplist import SymbolPolicy, admit, load_stoplist


def _policy(min_spec=2, stop=frozenset(), cap=1000):
    return SymbolPolicy(min_specificity=min_spec, user_stoplist=stop, max_symbols=cap)


def test_言語キーワードは採用しない():
    r = admit(["if", "STATUS_OK", "class"], "java", _policy(), hop=1)
    assert r.accepted == ["STATUS_OK"]
    assert ("if", "keyword") in r.rejected and ("class", "keyword") in r.rejected


def test_最小長未満は採用しない():
    r = admit(["x", "ab", "abc"], "c", _policy(min_spec=3), hop=1)
    assert r.accepted == ["abc"]
    assert ("x", "too_short") in r.rejected and ("ab", "too_short") in r.rejected


def test_ユーザストップリストは採用しない():
    r = admit(["FOO", "BAR"], "c", _policy(stop=frozenset({"BAR"})), hop=1)
    assert r.accepted == ["FOO"]
    assert ("BAR", "user_stoplist") in r.rejected


def test_集合上限超過は決定的に切り捨てる():
    # cap=2。キー (hop, len, 辞書順) で安定ソートし上限内採用。全 hop=1。
    r = admit(["zzz", "ab", "yy", "abc"], "c", _policy(min_spec=1, cap=2), hop=1)
    assert r.accepted == ["ab", "yy"]  # len 2 が辞書順で先、len 3 は capped
    assert ("abc", "capped") in r.rejected and ("zzz", "capped") in r.rejected


def test_ストップリストファイルを読み空行とコメントを無視する(tmp_path):
    f = tmp_path / "stop.txt"
    f.write_text("# comment\nFOO\n\n  BAR  \n", "utf-8")
    assert load_stoplist(f) == frozenset({"FOO", "BAR"})
    assert load_stoplist(None) == frozenset()
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_stoplist.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'grep_analyzer.stoplist'`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/stoplist.py` を新規作成:
```python
"""静的シンボル採否ポリシー（spec §8.3）。汎用名の横展開爆発を篩で防ぐ。

v1 は事前フル走査を要しない静的ソースのみ（言語キーワード／最小長／ユーザ
ストップリスト）。動的トップN は spec §14 スコープ外。
"""

from dataclasses import dataclass
from pathlib import Path

# 言語予約語（横展開しても無意味＝偽陽性源）。網羅でなく頻出語の決定的固定で足りる
# （spec §8.3 は「言語キーワード／予約語」を静的ストップリストの①と規定）。
_JAVA_KW = frozenset(
    "abstract assert boolean break byte case catch char class const continue default do double "
    "else enum extends final finally float for goto if implements import instanceof int interface "
    "long native new package private protected public return short static strictfp super switch "
    "synchronized this throw throws transient try void volatile while true false null var".split()
)
_C_KW = frozenset(
    "auto break case char const continue default do double else enum extern float for goto if int "
    "long register return short signed sizeof static struct switch typedef union unsigned void "
    "volatile while inline restrict _Bool".split()
)
_SQL_KW = frozenset(
    "select insert update delete from where and or not null is in like between exists into values "
    "set begin end declare if then else elsif loop for while case when decode dual table view "
    "procedure function trigger as order by group having distinct union all".split()
)
_SHELL_KW = frozenset(
    "if then else elif fi for while until do done case esac in function select time set setenv "
    "unset export readonly local return break continue switch breaksw end foreach endif endsw "
    "echo test true false".split()
)
LANG_KEYWORDS: dict[str, frozenset[str]] = {
    "java": _JAVA_KW,
    "c": _C_KW,
    "proc": _C_KW,
    "sql": _SQL_KW,
    "shell": _SHELL_KW,
}


@dataclass(frozen=True)
class SymbolPolicy:
    """採否の静的パラメータ（spec §8.3）。"""

    min_specificity: int
    user_stoplist: frozenset[str]
    max_symbols: int


@dataclass(frozen=True)
class AdmissionResult:
    """採否の決定的結果。rejected は (シンボル, 理由) の決定的列。"""

    accepted: list[str]
    rejected: list[tuple[str, str]]


def load_stoplist(path: Path | None) -> frozenset[str]:
    """ユーザ提供ストップリストを読む。空行と # コメント行を無視（静的）。"""
    if path is None:
        return frozenset()
    out = set()
    for raw in Path(path).read_text("utf-8").splitlines():
        s = raw.strip()
        if s and not s.startswith("#"):
            out.add(s)
    return frozenset(out)


def admit(
    symbols: list[str], language: str, policy: SymbolPolicy, hop: int
) -> AdmissionResult:
    """シンボル列を静的ポリシーで篩い、決定的に採否する（spec §8.3）。

    順序保存で keyword→too_short→user_stoplist を棄却。残りを
    (hop, 長さ, 辞書順) 安定ソートし max_symbols 超過分を capped 棄却。
    """
    kw = LANG_KEYWORDS.get(language, frozenset())
    accepted: list[str] = []
    rejected: list[tuple[str, str]] = []
    for s in symbols:
        if s in kw:
            rejected.append((s, "keyword"))
        elif len(s) < policy.min_specificity:
            rejected.append((s, "too_short"))
        elif s in policy.user_stoplist:
            rejected.append((s, "user_stoplist"))
        else:
            accepted.append(s)
    if len(accepted) > policy.max_symbols:
        ordered = sorted(accepted, key=lambda s: (hop, len(s), s))
        keep = ordered[: policy.max_symbols]
        keep_set = set(keep)
        rejected += [(s, "capped") for s in ordered[policy.max_symbols :]]
        accepted = [s for s in accepted if s in keep_set]
    return AdmissionResult(accepted, rejected)
```

- [ ] **Step 4: テストが通ることを確認（当該＋全体回帰ゼロ）**

Run: `python -m pytest tests/unit/test_stoplist.py -q`
Expected: PASS（5本）

Run: `python -m pytest -q`
Expected: 全 PASS・0 failed / 0 error。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/stoplist.py tests/unit/test_stoplist.py
git commit -m "feat(stoplist): 静的シンボル採否ポリシー（spec §8.3・決定的切り捨て）"
```

---

## Task 3: getter/setter 非投入の生命線 `stoplist.partition`

**Files:**
- Modify: `src/grep_analyzer/stoplist.py`
- Test: `tests/unit/test_stoplist.py`

spec §8.3 PRD生命線: `ChaseSymbols` のうち **getter/setter は不動点追跡集合へ投入しない（横展開しない）**。多ホップは constant/var 経由のみ。getter/setter は report-only（後段 fixedpoint が 1 ホップ報告のみ・confidence=low）。本タスクで「採用 chase 集合／報告専用 terminal 集合／棄却」への決定的分割を確定する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_stoplist.py` の末尾に追記:
```python
from grep_analyzer.chase import ChaseSymbols
from grep_analyzer.stoplist import partition


def test_getterとsetterは追跡集合に投入せずterminalへ回す():
    cs = ChaseSymbols(constants=("STATUS_OK",), vars=("count",), getters=("getName",), setters=("setX",))
    p = partition(cs, "java", _policy(min_spec=2), hop=1)
    assert p.chase == ["STATUS_OK", "count"]      # constant/var のみ横展開対象
    assert p.terminal == ["getName", "setX"]       # 報告専用（横展開しない）
    assert p.rejected == []


def test_terminalにもキーワード最小長は効くがcapはchaseのみ():
    cs = ChaseSymbols(getters=("getX",), setters=("set",))  # "set" は shell KW 相当でなく Java では非KW
    p = partition(cs, "java", _policy(min_spec=4), hop=1)
    assert p.terminal == ["getX"]                  # "set" は too_short(<4) で棄却
    assert ("set", "too_short") in p.rejected
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_stoplist.py -q`
Expected: FAIL（`ImportError: cannot import name 'partition'`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/stoplist.py` の末尾に追記:
```python
from grep_analyzer.chase import ChaseSymbols


@dataclass(frozen=True)
class Partition:
    """ChaseSymbols の決定的分割（spec §8.3）。

    chase=横展開対象（constant/var の採用分）、terminal=報告専用（getter/setter
    の採用分・横展開しない）、rejected=静的ポリシー棄却（chase/terminal 双方）。
    """

    chase: list[str]
    terminal: list[str]
    rejected: list[tuple[str, str]]


def partition(
    cs: ChaseSymbols, language: str, policy: SymbolPolicy, hop: int
) -> Partition:
    """ChaseSymbols を「横展開する chase／報告専用 terminal／棄却」に決定的分割する。

    spec §8.3 生命線: getter/setter は chase に入れない（横展開しない）。
    keyword/too_short/user_stoplist は chase/terminal 双方に適用。集合上限 cap は
    横展開対象＝chase にのみ適用（terminal は 1 ホップ報告のみで爆発しない）。
    """
    chase_in = list(cs.constants) + list(cs.vars)
    term_in = list(cs.getters) + list(cs.setters)
    chase_r = admit(chase_in, language, policy, hop)
    # terminal は cap 非適用（横展開しないため）。cap 無効化のため十分大きい上限で篩う。
    term_policy = SymbolPolicy(policy.min_specificity, policy.user_stoplist, len(term_in) + 1)
    term_r = admit(term_in, language, term_policy, hop)
    return Partition(chase_r.accepted, term_r.accepted, chase_r.rejected + term_r.rejected)
```

- [ ] **Step 4: テストが通ることを確認（当該＋全体回帰ゼロ）**

Run: `python -m pytest tests/unit/test_stoplist.py -q`
Expected: PASS（7本）

Run: `python -m pytest -q`
Expected: 全 PASS・0 failed / 0 error。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/stoplist.py tests/unit/test_stoplist.py
git commit -m "feat(stoplist): getter/setter 非投入の決定的分割 partition（spec §8.3 生命線）"
```

---

## Task 4: Aho-Corasick ラッパ `automaton.py`（識別子境界一致）

**Files:**
- Create: `src/grep_analyzer/automaton.py`
- Test: `tests/unit/test_automaton.py`

spec §8.2 ネイティブ Aho-Corasick（`pyahocorasick`）。`A.iter(s)` は **部分文字列も拾う**（`CODE` が `DECODE` 内で誤一致）。識別子の前後が `[A-Za-z0-9_]` でないことを確認して **語境界一致のみ採用**。1 行単位走査（lineno は呼出側 enumerate）。結果は決定的（昇順ユニークシンボル）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_automaton.py` を新規作成:
```python
"""Aho-Corasick ラッパの仕様（spec §8.2・識別子境界一致）。"""

from grep_analyzer.automaton import build, scan_line


def test_語境界一致のみ採用し部分文字列は拾わない():
    au = build(["CODE", "v_code"])
    assert scan_line(au, "int CODE; x = DECODE(v_code);") == ["CODE", "v_code"]
    assert scan_line(au, "DECODES = ENCODED;") == []  # 部分一致のみ＝不採用


def test_同一行の複数一致は昇順ユニークで返す():
    au = build(["A", "BB"])
    assert scan_line(au, "BB and A and A and BB") == ["A", "BB"]


def test_空シンボル集合はNoneを返し走査は空():
    assert build([]) is None
    assert scan_line(None, "anything") == []


def test_先頭と末尾の境界も識別子境界として扱う():
    au = build(["CODE"])
    assert scan_line(au, "CODE") == ["CODE"]
    assert scan_line(au, "CODE=1") == ["CODE"]
    assert scan_line(au, "xCODE") == []
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_automaton.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'grep_analyzer.automaton'`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/automaton.py` を新規作成:
```python
"""pyahocorasick ラッパ（spec §8.2）。識別子語境界一致のみ採用し決定的に返す。"""

import ahocorasick

_IDENT = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
)


def build(symbols: list[str]) -> ahocorasick.Automaton | None:
    """シンボル集合から Automaton を構築する。空集合は None（走査スキップ）。"""
    if not symbols:
        return None
    au = ahocorasick.Automaton()
    for s in symbols:
        au.add_word(s, s)
    au.make_automaton()
    return au


def scan_line(au: ahocorasick.Automaton | None, line: str) -> list[str]:
    """1 行から語境界一致したシンボルを昇順ユニークで返す（決定的）。

    `A.iter` は (end_index, value)。value=元シンボル。start=end-len+1。
    前後の文字が識別子文字なら部分一致＝不採用（CODE vs DECODE）。
    """
    if au is None:
        return []
    found = set()
    n = len(line)
    for end, sym in au.iter(line):
        start = end - len(sym) + 1
        before = line[start - 1] if start > 0 else ""
        after = line[end + 1] if end + 1 < n else ""
        if before not in _IDENT and after not in _IDENT:
            found.add(sym)
    return sorted(found)
```

- [ ] **Step 4: テストが通ることを確認（当該＋全体回帰ゼロ）**

Run: `python -m pytest tests/unit/test_automaton.py -q`
Expected: PASS（4本）

Run: `python -m pytest -q`
Expected: 全 PASS・0 failed / 0 error。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/automaton.py tests/unit/test_automaton.py
git commit -m "feat(automaton): pyahocorasick ラッパ＋識別子境界一致（spec §8.2）"
```

---

## Task 5: 決定的ツリー走査 `walk.py`

**Files:**
- Create: `src/grep_analyzer/walk.py`
- Test: `tests/unit/test_walk.py`

spec §8.2: ファイルサイズ上限＋バイナリ skip、include/exclude glob（**生成コード既定除外**・除外は diagnostics 記録）、**シンボリックリンク既定で辿らない**、realpath 正規化で同一実体の二重走査排除（代表＝正規化相対パス辞書順で決定的）、リンクループ検出。**走査順は relpath 昇順で決定的**。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_walk.py` を新規作成:
```python
"""決定的ツリー走査の仕様（spec §8.2）。外部I/O境界＝実ファイルシステム本物。"""

import os

from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.walk import DEFAULT_EXCLUDE, walk_files


def _walk(root, **kw):
    diag = Diagnostics()
    kw.setdefault("include", [])
    kw.setdefault("exclude", list(DEFAULT_EXCLUDE))
    kw.setdefault("follow_symlinks", False)
    kw.setdefault("max_file_bytes", 1_000_000)
    return [r for r, _ in walk_files(root, diag=diag, **kw)], diag


def test_走査は相対パス昇順で決定的(tmp_path):
    (tmp_path / "b.c").write_text("x", "utf-8")
    (tmp_path / "a.c").write_text("y", "utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.c").write_text("z", "utf-8")
    rels, _ = _walk(tmp_path)
    assert rels == ["a.c", "b.c", "sub/c.c"]


def test_生成コードは既定除外し診断に記録する(tmp_path):
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "Gen.java").write_text("x", "utf-8")
    (tmp_path / "Keep.java").write_text("y", "utf-8")
    rels, diag = _walk(tmp_path)
    assert rels == ["Keep.java"]
    assert "walk_excluded" in diag.render()


def test_バイナリと巨大ファイルはskipし診断に記録する(tmp_path):
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02CODE")
    (tmp_path / "big.c").write_text("a" * 50, "utf-8")
    (tmp_path / "ok.c").write_text("CODE", "utf-8")
    diag = Diagnostics()
    rels = [
        r
        for r, _ in walk_files(
            tmp_path, include=[], exclude=list(DEFAULT_EXCLUDE),
            follow_symlinks=False, max_file_bytes=10, diag=diag,
        )
    ]
    assert rels == ["ok.c"]
    d = diag.render()
    assert "walk_skipped_binary" in d and "walk_skipped_large" in d


def test_includeグロブ指定時は一致するもののみ(tmp_path):
    (tmp_path / "a.java").write_text("x", "utf-8")
    (tmp_path / "b.txt").write_text("y", "utf-8")
    rels, _ = _walk(tmp_path, include=["*.java"])
    assert rels == ["a.java"]


def test_同一実体の重複は正規化パス辞書順の代表のみ走査(tmp_path):
    (tmp_path / "real.c").write_text("CODE", "utf-8")
    os.symlink(tmp_path / "real.c", tmp_path / "link.c")  # 既定で辿らない＝link.c 自体は除外
    rels, diag = _walk(tmp_path)
    assert rels == ["real.c"]
    assert "symlink_skipped" in diag.render()
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_walk.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'grep_analyzer.walk'`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/walk.py` を新規作成:
```python
"""決定的ツリー走査（spec §8.2）。relpath 昇順・glob・サイズ/バイナリ skip・

生成コード既定除外・symlink は既定で辿らず realpath 重複排除。すべて
走査順非依存で決定的（spec §9 決定性の前提）。
"""

import fnmatch
import os
from collections.abc import Iterator
from pathlib import Path

from grep_analyzer.diagnostics import Diagnostics

# v1 の生成コード既定除外（spec §8.2「生成コード既定除外」。具体パターンは spec 未列挙
# のため決定的な保守的既定を本実装で固定。--include/--exclude で上書き可）。
DEFAULT_EXCLUDE: tuple[str, ...] = (
    "**/target/**", "**/build/**", "**/generated/**", "**/gen/**",
    "**/node_modules/**", "**/.git/**", "*.min.js", "*_pb2.py",
)


def _match_any(rel: str, patterns: list[str]) -> bool:
    """relpath が glob パターン群のいずれかに一致するか（** はプレフィックス扱い）。"""
    for p in patterns:
        if p.endswith("/**"):
            base = p[:-3]
            if rel == base or rel.startswith(base + "/") or fnmatch.fnmatch(rel, base):
                return True
        if fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, "**/" + p):
            return True
    return False


def _is_binary(path: Path) -> bool:
    """先頭 8KB に NUL バイトを含めばバイナリとみなす（決定的）。"""
    with open(path, "rb") as f:
        return b"\x00" in f.read(8192)


def walk_files(
    root: Path,
    *,
    include: list[str],
    exclude: list[str],
    follow_symlinks: bool,
    max_file_bytes: int,
    diag: Diagnostics,
) -> Iterator[tuple[str, Path]]:
    """root 配下の通常ファイルを relpath 昇順で yield する（spec §8.2）。

    除外/スキップ/symlink 重複は diag に記録（spec §8.4 正本へ集約）。
    """
    root = Path(root)
    seen_real: dict[str, str] = {}  # realpath -> 代表 relpath（辞書順最小）
    candidates: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        dirnames.sort()
        for name in sorted(filenames):
            abspath = Path(dirpath) / name
            rel = abspath.relative_to(root).as_posix()
            if abspath.is_symlink() and not follow_symlinks:
                diag.add("symlink_skipped", rel)
                continue
            if _match_any(rel, exclude):
                diag.add("walk_excluded", rel)
                continue
            if include and not _match_any(rel, include):
                continue
            candidates.append((rel, abspath))

    for rel, abspath in sorted(candidates):
        try:
            if abspath.stat().st_size > max_file_bytes:
                diag.add("walk_skipped_large", rel)
                continue
            if _is_binary(abspath):
                diag.add("walk_skipped_binary", rel)
                continue
            real = os.path.realpath(abspath)
        except OSError:
            diag.add("walk_unreadable", rel)
            continue
        if real in seen_real:
            diag.add("symlink_dedup", f"{rel} -> {seen_real[real]}")
            continue
        seen_real[real] = rel  # candidates は relpath 昇順＝最初が辞書順最小代表
        yield rel, abspath
```

- [ ] **Step 4: テストが通ることを確認（当該＋全体回帰ゼロ）**

Run: `python -m pytest tests/unit/test_walk.py -q`
Expected: PASS（5本）

Run: `python -m pytest -q`
Expected: 全 PASS・0 failed / 0 error。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/walk.py tests/unit/test_walk.py
git commit -m "feat(walk): 決定的ツリー走査＋生成コード除外＋symlink重複排除（spec §8.2）"
```

---

## Task 6: 来歴グラフと chain 正規形 `provenance.py`

**Files:**
- Create: `src/grep_analyzer/provenance.py`
- Test: `tests/unit/test_provenance.py`

spec §9 chain 正規形: 各ホップ `symbol@<relpath>:<lineno>` を ` -> ` 連結。**単純パス**（同一エッジ・同一シンボルを二度通らない）のみ列挙。循環は最初の再訪エッジで打ち切り §8.4 へ記録。`--max-depth` 超過パスも打ち切り。**同一ヒットへ異なる単純パスで到達したら経路ごとに別行**（重複許容＝仕様）。経路集合は有限かつ決定的（DFS をエッジ決定的順で）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_provenance.py` を新規作成:
```python
"""来歴グラフと chain 正規形の仕様（spec §9）。"""

from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.provenance import Occurrence, ProvenanceGraph


def test_単一経路のchainは起点から連結される():
    g = ProvenanceGraph()
    s = Occurrence("KEY", "a.c", 1)
    m = Occurrence("CODE", "b.c", 5)
    g.add_seed(s)
    g.add_edge(s, m)
    assert g.chains_to(m, max_depth=10, diag=Diagnostics()) == ["KEY@a.c:1 -> CODE@b.c:5"]


def test_複数単純パスは経路ごとに別chainを決定的順で返す():
    g = ProvenanceGraph()
    s = Occurrence("KEY", "a.c", 1)
    p = Occurrence("P", "p.c", 2)
    q = Occurrence("Q", "q.c", 3)
    h = Occurrence("H", "h.c", 9)
    g.add_seed(s)
    for parent, child in [(s, p), (s, q), (p, h), (q, h)]:
        g.add_edge(parent, child)
    assert g.chains_to(h, max_depth=10, diag=Diagnostics()) == [
        "KEY@a.c:1 -> P@p.c:2 -> H@h.c:9",
        "KEY@a.c:1 -> Q@q.c:3 -> H@h.c:9",
    ]


def test_循環は再訪で打ち切り診断に記録する():
    g = ProvenanceGraph()
    s = Occurrence("KEY", "a.c", 1)
    x = Occurrence("X", "x.c", 2)
    y = Occurrence("Y", "y.c", 3)
    g.add_seed(s)
    for parent, child in [(s, x), (x, y), (y, x)]:  # x->y->x 循環
        g.add_edge(parent, child)
    diag = Diagnostics()
    chains = g.chains_to(y, max_depth=10, diag=diag)
    assert chains == ["KEY@a.c:1 -> X@x.c:2 -> Y@y.c:3"]
    assert "prov_cycle_cut" in diag.render()


def test_max_depth超過パスは打ち切り診断に記録する():
    g = ProvenanceGraph()
    s = Occurrence("KEY", "a.c", 1)
    a = Occurrence("A", "a.c", 2)
    b = Occurrence("B", "b.c", 3)
    g.add_seed(s)
    for parent, child in [(s, a), (a, b)]:
        g.add_edge(parent, child)
    diag = Diagnostics()
    # max_depth=2 → ホップ数 2 まで（s,a）。b への 3 ノード経路は超過。
    assert g.chains_to(b, max_depth=2, diag=diag) == []
    assert "prov_max_depth" in diag.render()
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_provenance.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'grep_analyzer.provenance'`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/provenance.py` を新規作成:
```python
"""来歴グラフと chain 正規形（spec §9）。単純パスのみ列挙し決定的・有限化する。"""

from dataclasses import dataclass

from grep_analyzer.diagnostics import Diagnostics


@dataclass(frozen=True, order=True)
class Occurrence:
    """ヒット出現＝来歴グラフのノード。symbol が当該行で出現した位置。"""

    symbol: str
    relpath: str
    lineno: int


def _hop(o: Occurrence) -> str:
    """spec §9 ホップ表記 `symbol@relpath:lineno`。"""
    return f"{o.symbol}@{o.relpath}:{o.lineno}"


class ProvenanceGraph:
    """発見元→発見の有向グラフ。種から各ヒットへの単純パスを chain 化する。"""

    def __init__(self) -> None:
        self._seeds: set[Occurrence] = set()
        # parent -> 子の決定的ソート済みリスト（重複エッジは排除）
        self._adj: dict[Occurrence, list[Occurrence]] = {}

    def add_seed(self, occ: Occurrence) -> None:
        """起点（direct ヒット相当）を登録する。"""
        self._seeds.add(occ)

    def add_edge(self, parent: Occurrence, child: Occurrence) -> None:
        """発見元 parent から発見 child へのエッジを追加（決定的順序を維持）。"""
        lst = self._adj.setdefault(parent, [])
        if child not in lst:
            lst.append(child)
            lst.sort()

    def chains_to(
        self, target: Occurrence, max_depth: int, diag: Diagnostics
    ) -> list[str]:
        """各 seed から target への単純パスを chain 文字列の決定的リストで返す。

        単純パス＝同一 Occurrence を二度通らない。循環の再訪・max_depth 超過は
        打ち切り、それぞれ prov_cycle_cut / prov_max_depth を diag に記録（spec §8.4）。
        max_depth はパスの **ホップ数（ノード数-1）** の上限とみなす。
        """
        results: list[str] = []
        for seed in sorted(self._seeds):
            self._dfs(seed, target, [seed], {seed}, max_depth, diag, results)
        return sorted(set(results))

    def _dfs(self, node, target, path, visited, max_depth, diag, results) -> None:
        if node == target:
            results.append(" -> ".join(_hop(o) for o in path))
            return
        if len(path) - 1 >= max_depth:
            diag.add("prov_max_depth", _hop(path[0]) + " ... " + _hop(node))
            return
        for nxt in self._adj.get(node, []):
            if nxt in visited:
                diag.add("prov_cycle_cut", _hop(node) + " -> " + _hop(nxt))
                continue
            self._dfs(
                nxt, target, path + [nxt], visited | {nxt}, max_depth, diag, results
            )
```

- [ ] **Step 4: テストが通ることを確認（当該＋全体回帰ゼロ）**

Run: `python -m pytest tests/unit/test_provenance.py -q`
Expected: PASS（4本）

Run: `python -m pytest -q`
Expected: 全 PASS・0 failed / 0 error。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/provenance.py tests/unit/test_provenance.py
git commit -m "feat(provenance): 来歴グラフ＋chain単純パス正規形（spec §9・決定的有限化）"
```

---

## Task 7: 共有行分類 `classify.py`（pipeline と fixedpoint の DRY）

**Files:**
- Create: `src/grep_analyzer/classify.py`
- Test: `tests/unit/test_classify.py`

`pipeline._classify` と同じ分類を fixedpoint からも使うが、`pipeline` が `fixedpoint` を import するため循環回避が必要。分類ロジックを `classify.py` に切り出し、pipeline は Task 10 で本関数へ委譲（回帰ゼロを確認）。本タスクでは新規モジュールと unit のみ（pipeline 未変更）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_classify.py` を新規作成:
```python
"""共有行分類の仕様（pipeline と fixedpoint が共通利用）。"""

from grep_analyzer.classify import classify_hit


def test_ts言語はtree_sitterでhigh分類():
    cat, conf = classify_hit("java", "", 'class A{ int x;\n if(x==1){} }', 2, "if(x==1){}")
    assert (cat, conf) == ("比較", "high")


def test_sqlはOracle正規表現でmedium分類():
    assert classify_hit("sql", "", "", 1, "v := 1;") == ("代入", "medium")


def test_shellは方言別正規表現でmedium分類():
    assert classify_hit("shell", "cshell", "", 1, "set X = 1") == ("代入", "medium")
    assert classify_hit("shell", "bourne", "", 1, "X=1") == ("代入", "medium")


def test_未知言語はbourneフォールバック():
    assert classify_hit("unknown", "", "", 1, "X=1") == ("代入", "medium")
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_classify.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'grep_analyzer.classify'`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/classify.py` を新規作成（`pipeline._classify` と挙動同一・引数順も同一）:
```python
"""言語別行分類の共有実装（spec §7）。pipeline と fixedpoint が共通利用する。

循環 import 回避のため pipeline から本モジュールへ分類を委譲する（Task 10）。
"""

from grep_analyzer.classifiers.base import ClassifyResult
from grep_analyzer.classifiers.regex_classifier import classify_shell, classify_sql
from grep_analyzer.classifiers.ts_classifier import classify_ts


def classify_hit(
    language: str, dialect: str, file_text: str, lineno: int, content: str
) -> ClassifyResult:
    """1 ヒットを言語別に分類して (category, confidence) を返す（spec §7）。

    java/c/proc は tree-sitter（high）、sql/shell は正規表現（medium）、
    未知言語は bourne shell 規則にフォールバック（pipeline 既存挙動と同一）。
    """
    if language in ("java", "c", "proc"):
        return classify_ts(language, file_text, lineno)
    if language == "sql":
        return classify_sql(content)
    if language == "shell":
        return classify_shell(content, dialect)
    return classify_shell(content, "bourne")
```

- [ ] **Step 4: テストが通ることを確認（当該＋全体回帰ゼロ）**

Run: `python -m pytest tests/unit/test_classify.py -q`
Expected: PASS（4本）

Run: `python -m pytest -q`
Expected: 全 PASS・0 failed / 0 error（pipeline 未変更につき既存不変）。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/classify.py tests/unit/test_classify.py
git commit -m "feat(classify): pipeline/fixedpoint 共有の行分類（循環import回避）"
```

---

## Task 8: 不動点エンジン単一ホップ `fixedpoint.py`

**Files:**
- Create: `src/grep_analyzer/fixedpoint.py`
- Test: `tests/unit/test_fixedpoint.py`

spec §8.1 手順1〜3・7 の 1 ホップ分: seed ヒット行から `extract_chase_symbols` → §8.3 `partition` → automaton 構築 → `walk` 走査 → 行を `classify_hit` → indirect Hit 生成・provenance エッジ。多ホップ反復は Task 9。本タスクは `max_depth=1` 相当の単一ホップで決定性と ref_kind を固定。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_fixedpoint.py` を新規作成:
```python
"""不動点エンジン（単一ホップ）の仕様（spec §8.1）。外部I/O境界＝実FS本物。"""

from pathlib import Path

from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.fixedpoint import EngineOptions, run_fixedpoint
from grep_analyzer.model import Hit


def _opts(**kw):
    base = dict(
        max_depth=5, min_specificity=2, stoplist_path=None, include=[],
        exclude=[], jobs=1, follow_symlinks=False, max_file_bytes=1_000_000,
        max_symbols=1000,
    )
    base.update(kw)
    return EngineOptions(**base)


def _seed(keyword, language, rel, lineno, content):
    return Hit(
        keyword=keyword, language=language, file=rel, lineno=lineno, ref_kind="direct",
        category="宣言", category_sub="", usage_summary=f"宣言 ({language})",
        via_symbol="", chain=f"{keyword}@{rel}:{lineno}", snippet=content,
        encoding="utf-8", confidence="high",
    )


def test_seed定数の他ファイル出現をindirect_constantで報告する(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "C.java").write_text(
        'class C { static final String STATUS_OK = "S"; }\n', "utf-8"
    )
    (src / "U.java").write_text("class U { String x = STATUS_OK; }\n", "utf-8")
    seed = _seed("STATUS_OK", "java", "C.java", 1,
                 'static final String STATUS_OK = "S";')
    diag = Diagnostics()
    hits = run_fixedpoint([seed], src, _opts(), diag)
    rows = {(h.file, h.lineno, h.ref_kind, h.via_symbol) for h in hits}
    assert ("U.java", 1, "indirect:constant", "STATUS_OK") in rows
    h = next(h for h in hits if h.file == "U.java")
    assert h.chain == "STATUS_OK@C.java:1 -> STATUS_OK@U.java:1"
    assert h.keyword == "STATUS_OK" and h.confidence == "high"


def test_getter_setterは横展開せずlow報告し抑止を診断記録する(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "S.java").write_text(
        "class S { void m(){ int v = svc.getName(); } }\n", "utf-8"
    )
    (src / "T.java").write_text("class T { String n = obj.getName(); }\n", "utf-8")
    seed = _seed("v", "java", "S.java", 1, "int v = svc.getName();")
    diag = Diagnostics()
    hits = run_fixedpoint([seed], src, _opts(), diag)
    g = [h for h in hits if h.via_symbol == "getName"]
    assert g and all(h.ref_kind == "indirect:getter" and h.confidence == "low" for h in g)
    assert "getter_setter_no_expand" in diag.render()


def test_対象シンボルが無ければ空(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "A.java").write_text("class A {}\n", "utf-8")
    seed = _seed("KW", "java", "A.java", 1, "class A {}")
    assert run_fixedpoint([seed], src, _opts(), Diagnostics()) == []
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_fixedpoint.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'grep_analyzer.fixedpoint'`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/fixedpoint.py` を新規作成:
```python
"""不動点・ターゲットスキャン・エンジン（spec §8.1/§8.2/§8.3）。

決定性基盤（Phase 1/1.5）の direct ヒットを seed に、constant/var を多ホップ
追跡し indirect ヒットと chain を出す。getter/setter は §8.3 により横展開せず
1 ホップ報告のみ（confidence=low）。出力は走査順・並列完了順に非依存で決定的。
"""

from dataclasses import dataclass
from pathlib import Path

from grep_analyzer.chase import extract_chase_symbols
from grep_analyzer.classify import classify_hit
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.dispatch import detect_language, detect_shell_dialect
from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes
from grep_analyzer.model import Hit
from grep_analyzer.provenance import Occurrence, ProvenanceGraph
from grep_analyzer.stoplist import SymbolPolicy, load_stoplist, partition
from grep_analyzer import automaton
from grep_analyzer import walk


@dataclass(frozen=True)
class EngineOptions:
    """spec §8/§10.4 のエンジン挙動パラメータ（Phase 2a 範囲）。"""

    max_depth: int
    min_specificity: int
    stoplist_path: Path | None
    include: list[str]
    exclude: list[str]
    jobs: int
    follow_symlinks: bool
    max_file_bytes: int
    max_symbols: int


# 採用シンボルの種別 → ref_kind（spec §9 ref_kind 列）。
_REF_KIND = {
    "constant": "indirect:constant",
    "var": "indirect:var",
    "getter": "indirect:getter",
    "setter": "indirect:setter",
}


def _decode(abspath: Path) -> tuple[str, str, bool]:
    return decode_bytes(abspath.read_bytes(), DEFAULT_FALLBACK)


def _kinds_of(language: str, dialect: str, line: str) -> dict[str, str]:
    """1 行から抽出した各シンボル → 種別（constant/var/getter/setter）。

    同名が複数種別に出たら constant>var>getter>setter の決定的優先で 1 種別に固定。
    """
    cs = extract_chase_symbols(language, dialect, line)
    out: dict[str, str] = {}
    for kind, names in (
        ("setter", cs.setters), ("getter", cs.getters),
        ("var", cs.vars), ("constant", cs.constants),
    ):
        for n in names:
            out[n] = kind  # 後勝ち＝優先順位の高い種別で上書き
    return out


def run_fixedpoint(
    seed_hits: list[Hit], source_root: Path, opts: EngineOptions, diag: Diagnostics
) -> list[Hit]:
    """seed（direct）ヒットから多ホップ追跡し indirect Hit を決定的に返す。

    本タスクは単一ホップ実装（多ホップ反復は次タスクで while ループ化）。
    """
    source_root = Path(source_root)
    user_stop = load_stoplist(opts.stoplist_path)
    policy = SymbolPolicy(opts.min_specificity, user_stop, opts.max_symbols)
    graph = ProvenanceGraph()

    # 種シンボル＝seed の keyword。seed 行から hop1 候補を抽出。
    sym_kind: dict[str, str] = {}        # シンボル -> 種別（chase/terminal 共通）
    sym_origin: dict[str, list[Occurrence]] = {}  # シンボル -> 発見元 Occurrence 群
    chase_syms: set[str] = set()
    term_syms: set[str] = set()
    no_expand_logged: set[str] = set()

    for s in seed_hits:
        keyword = s.keyword
        occ = Occurrence(keyword, s.file, s.lineno)
        graph.add_seed(occ)
        dialect = "bourne"
        if s.language == "shell":
            dialect = "cshell" if "csh" in s.snippet[:0] else "bourne"  # seed は file 既知
        kinds = _kinds_of(s.language, _seed_dialect(s), s.snippet)
        cs = extract_chase_symbols(s.language, _seed_dialect(s), s.snippet)
        part = partition(cs, s.language, policy, hop=1)
        for sym, reason in part.rejected:
            diag.add("symbol_rejected", f"{reason}\t{sym}")
        for sym in part.chase:
            chase_syms.add(sym)
            sym_kind[sym] = kinds.get(sym, "var")
            sym_origin.setdefault(sym, []).append(occ)
        for sym in part.terminal:
            term_syms.add(sym)
            sym_kind[sym] = kinds.get(sym, "getter")
            sym_origin.setdefault(sym, []).append(occ)

    all_syms = sorted(chase_syms | term_syms)
    au = automaton.build(all_syms)
    if au is None:
        return []

    indirect: list[Hit] = []
    for rel, abspath in walk.walk_files(
        source_root, include=opts.include, exclude=opts.exclude,
        follow_symlinks=opts.follow_symlinks, max_file_bytes=opts.max_file_bytes,
        diag=diag,
    ):
        text, enc, replaced = _decode(abspath)
        if replaced:
            diag.add("decode_replaced", rel)
        language = detect_language(rel, text[:4096], {})
        dialect = detect_shell_dialect(rel, text[:4096]) if language == "shell" else "bourne"
        for i, line in enumerate(text.split("\n"), start=1):
            for sym in automaton.scan_line(au, line):
                # seed 自身の行（同一 file:lineno のシードシンボル）は direct 済み＝除外
                child = Occurrence(sym, rel, i)
                if child in graph._seeds:
                    continue
                for parent in sym_origin.get(sym, []):
                    if parent == child:
                        continue
                    graph.add_edge(parent, child)
                kind = sym_kind.get(sym, "var")
                if sym in term_syms and sym not in no_expand_logged:
                    diag.add("getter_setter_no_expand", sym)
                    no_expand_logged.add(sym)
                cat, conf = classify_hit(language, dialect, text, i, line)
                if kind in ("getter", "setter"):
                    conf = "low"  # spec §8.4 型解決不能 getter/setter
                for chain in graph.chains_to(child, opts.max_depth, diag):
                    indirect.append(Hit(
                        keyword=_keyword_for(sym, sym_origin, seed_hits),
                        language=language, file=rel, lineno=i,
                        ref_kind=_REF_KIND[kind], category=cat, category_sub="",
                        usage_summary=f"{cat} ({language})", via_symbol=sym,
                        chain=chain, snippet=line,
                        encoding=enc + (" 要確認" if replaced else ""), confidence=conf,
                    ))
    return indirect


def _seed_dialect(h: Hit) -> str:
    """seed Hit の方言。Phase 1.5 pipeline が shell を方言判定済みでも Hit には
    方言列が無いため、snippet からの csh 構文で決定的に再判定（保守的に bourne 既定）。"""
    if h.language != "shell":
        return "bourne"
    s = h.snippet.lstrip()
    if s.startswith(("set ", "setenv ", "@ ")) or s.startswith(("if(", "while(", "switch(")):
        return "cshell"
    return "bourne"


def _keyword_for(sym, sym_origin, seed_hits) -> str:
    """indirect Hit の keyword は起点 seed の keyword（複数 seed 同名は決定的に最小）。"""
    kws = sorted({s.keyword for s in seed_hits})
    return kws[0] if kws else sym
```

> **実装注（重要・批判的レビュー対象）:** `graph._seeds` 直接参照と `_seed_dialect` の snippet ヒューリスティックは Phase 2a の既知の弱点。前者は `ProvenanceGraph.is_seed(occ)` を Task 9 で公開 API 化して解消。後者は seed の方言が `Hit` に無いことに起因（Phase 1.5 で `Hit` に方言列を足さなかった設計の帰結）＝§8.4 既知境界として diag 記録し、Task 9 で seed 側に方言を伝える `SeedSymbol` 構造で精密化する。

- [ ] **Step 4: テストが通ることを確認（当該＋全体回帰ゼロ）**

Run: `python -m pytest tests/unit/test_fixedpoint.py -q`
Expected: PASS（3本）

Run: `python -m pytest -q`
Expected: 全 PASS・0 failed / 0 error。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/fixedpoint.py tests/unit/test_fixedpoint.py
git commit -m "feat(fixedpoint): 単一ホップ追跡＋indirect分類＋getter/setter非展開（spec §8.1/§8.3）"
```

---

## Task 9: 多ホップ反復・停止性・決定的集約

**Files:**
- Modify: `src/grep_analyzer/fixedpoint.py`
- Modify: `src/grep_analyzer/provenance.py`
- Test: `tests/unit/test_fixedpoint.py`

spec §8.1 手順4〜6: 新規シンボルが出れば追加し **不動点（新規が枯れる）まで反復**、停止性（有限母集合＋単調増加で高々 |母集合| ステップ飽和）、シンボル循環検出・`--max-depth` 安全弁。spec §8.2: ワーカは `(発見元, 発見, file, lineno)` エッジ断片のみ返し集約フェーズで合成＝**`--jobs` 並列でも出力不変**。Phase 2a は `multiprocessing.Pool` を実配線しつつ、走査の純粋性と決定的集約で `jobs=1` と `jobs=N` の TSV 完全一致を固定する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_fixedpoint.py` の末尾に追記:
```python
def test_多ホップ定数連鎖を不動点まで追う(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "A.java").write_text('class A{ static final int K1 = 1; }\n', "utf-8")
    (src / "B.java").write_text("class B{ static final int K2 = K1; }\n", "utf-8")
    (src / "C.java").write_text("class C{ int z = K2; }\n", "utf-8")
    seed = _seed("K1", "java", "A.java", 1, "static final int K1 = 1;")
    hits = run_fixedpoint([seed], src, _opts(), Diagnostics())
    rels = {(h.file, h.via_symbol) for h in hits}
    assert ("B.java", "K1") in rels       # hop1: K1 の出現
    assert ("C.java", "K2") in rels       # hop2: B で K2 を新規採用し追跡
    c = next(h for h in hits if h.file == "C.java")
    assert c.chain == "K1@A.java:1 -> K1@B.java:1 -> K2@C.java:1"


def test_有限母集合で飽和し停止する(tmp_path: Path):
    # 相互参照（A->B, B->A 相当）でも有限母集合＝有限ステップで停止（無限ループしない）。
    src = tmp_path / "src"
    src.mkdir()
    (src / "A.java").write_text("class A{ static final int P = Q; }\n", "utf-8")
    (src / "B.java").write_text("class B{ static final int Q = P; }\n", "utf-8")
    seed = _seed("P", "java", "A.java", 1, "static final int P = Q;")
    hits = run_fixedpoint([seed], src, _opts(max_depth=10), Diagnostics())
    assert hits  # 停止して結果が返る（タイムアウトしない＝有限飽和）
    assert all(h.ref_kind.startswith("indirect:") for h in hits)


def test_jobs1とjobsNでTSV完全一致の決定的集約(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "A.java").write_text('class A{ static final int K = 1; }\n', "utf-8")
    for nm in "BCDE":
        (src / f"{nm}.java").write_text(f"class {nm}{{ int v = K; }}\n", "utf-8")
    seed = _seed("K", "java", "A.java", 1, "static final int K = 1;")
    h1 = run_fixedpoint([seed], src, _opts(jobs=1), Diagnostics())
    hN = run_fixedpoint([seed], src, _opts(jobs=4), Diagnostics())
    key = lambda h: (h.file, h.lineno, h.ref_kind, h.via_symbol, h.chain)
    assert sorted(map(key, h1)) == sorted(map(key, hN))
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_fixedpoint.py -q`
Expected: FAIL（`test_多ホップ定数連鎖を不動点まで追う` 等が AssertionError＝単一ホップ実装では hop2 未追跡）

- [ ] **Step 3: 実装**

`src/grep_analyzer/provenance.py` に公開 API を追加（Task 7 の `graph._seeds` 直接参照を解消）。`ProvenanceGraph` クラスへメソッド追加:
```python
    def is_seed(self, occ: Occurrence) -> bool:
        """occ が起点（direct 相当）か。"""
        return occ in self._seeds
```

`src/grep_analyzer/fixedpoint.py` を多ホップ反復・決定的並列集約に書き換える。`run_fixedpoint` を以下に置換:
```python
@dataclass(frozen=True)
class SeedSymbol:
    """seed から得た hop0 シンボルと方言。snippet ヒューリスティックを排し
    pipeline が判定済みの方言を明示的に運ぶ（Task 7 の弱点を解消）。"""

    symbol: str
    kind: str
    language: str
    dialect: str
    origin: Occurrence


def _scan_file(args):
    """1 ファイルを走査しエッジ断片＋ヒット素片を返す純関数（並列ワーカ）。

    返り値は決定的に集約可能なプリミティブのみ（プロセス間 picklable）。
    """
    rel, raw, sym_list = args
    text, enc, replaced = decode_bytes(raw, DEFAULT_FALLBACK)
    language = detect_language(rel, text[:4096], {})
    dialect = detect_shell_dialect(rel, text[:4096]) if language == "shell" else "bourne"
    au = automaton.build(sym_list)
    found = []  # (sym, lineno, line, language, dialect)
    if au is not None:
        for i, line in enumerate(text.split("\n"), start=1):
            for sym in automaton.scan_line(au, line):
                found.append((sym, i, line, language, dialect))
    return rel, enc, replaced, found


def run_fixedpoint(
    seed_hits: list[Hit], source_root: Path, opts: EngineOptions, diag: Diagnostics
) -> list[Hit]:
    """seed から不動点まで多ホップ追跡し indirect Hit を決定的に返す（spec §8.1）。

    停止性: 追跡シンボル母集合は有限（ソースツリー上の字句のみ）、採用集合は
    単調増加。よって高々 |母集合| ステップで飽和。--max-depth・max_symbols は
    安全弁（spec §8.1 手順5/6）。出力は走査順・並列完了順に非依存（spec §9）。
    """
    import multiprocessing

    source_root = Path(source_root)
    policy = SymbolPolicy(opts.min_specificity, load_stoplist(opts.stoplist_path), opts.max_symbols)
    graph = ProvenanceGraph()

    sym_kind: dict[str, str] = {}
    sym_origin: dict[str, list[Occurrence]] = {}
    seed_dialect_lang: dict[str, tuple[str, str]] = {}
    chase_active: set[str] = set()   # まだ走査していない採用 chase シンボル
    chase_done: set[str] = set()     # 走査済み（単調増加）
    term_syms: set[str] = set()
    no_expand_logged: set[str] = set()
    keyword = sorted({s.keyword for s in seed_hits})[0] if seed_hits else ""

    def _ingest(language, dialect, line, parent: Occurrence, hop: int):
        cs = extract_chase_symbols(language, dialect, line)
        kinds = _kinds_of(language, dialect, line)
        part = partition(cs, language, policy, hop)
        for sym, reason in part.rejected:
            diag.add("symbol_rejected", f"{reason}\t{sym}")
        for sym in part.chase:
            sym_kind.setdefault(sym, kinds.get(sym, "var"))
            sym_origin.setdefault(sym, []).append(parent)
            seed_dialect_lang.setdefault(sym, (language, dialect))
            if sym not in chase_done:
                chase_active.add(sym)
        for sym in part.terminal:
            sym_kind.setdefault(sym, kinds.get(sym, "getter"))
            sym_origin.setdefault(sym, []).append(parent)
            seed_dialect_lang.setdefault(sym, (language, dialect))
            term_syms.add(sym)

    # hop0: seed 行から候補抽出（方言は pipeline 由来＝Hit には無いので保守再判定）
    for s in seed_hits:
        occ = Occurrence(s.keyword, s.file, s.lineno)
        graph.add_seed(occ)
        _ingest(s.language, _seed_dialect(s), s.snippet, occ, hop=1)

    files: list[tuple[str, bytes]] = [
        (rel, abspath.read_bytes())
        for rel, abspath in walk.walk_files(
            source_root, include=opts.include, exclude=opts.exclude,
            follow_symlinks=opts.follow_symlinks,
            max_file_bytes=opts.max_file_bytes, diag=diag,
        )
    ]

    # 不動点反復: 新規 chase シンボルが枯れるまで全ツリー走査（spec §8.2 差分走査の
    # 限定効果は Phase 2b。Phase 2a は正しさ優先で毎パス全走査）。
    hop = 1
    edges: list[tuple[Occurrence, Occurrence]] = []
    enc_of: dict[str, tuple[str, bool]] = {}
    term_hit: list[tuple[str, str, int, str, str]] = []  # sym,rel,lineno,line,lang/dialect 略
    while chase_active or (hop == 1 and term_syms):
        scan_syms = sorted(chase_active | (term_syms if hop == 1 else set()))
        chase_done |= chase_active
        just = set(chase_active)
        chase_active = set()
        if not scan_syms or hop > opts.max_depth:
            if hop > opts.max_depth:
                diag.add("prov_max_depth", f"reached --max-depth={opts.max_depth}")
            break
        args = [(rel, raw, scan_syms) for rel, raw in files]
        if opts.jobs > 1:
            with multiprocessing.Pool(opts.jobs) as pool:
                results = pool.map(_scan_file, args)
        else:
            results = [_scan_file(a) for a in args]
        # 決定的集約: rel 昇順で処理（pool.map は順序保存だが明示ソートで完全固定）
        for rel, enc, replaced, found in sorted(results, key=lambda r: r[0]):
            enc_of[rel] = (enc, replaced)
            if replaced:
                diag.add("decode_replaced", rel)
            for sym, i, line, language, dialect in found:
                if sym not in just and not (hop == 1 and sym in term_syms):
                    continue
                child = Occurrence(sym, rel, i)
                if graph.is_seed(child):
                    continue
                for parent in sym_origin.get(sym, []):
                    if parent != child:
                        edges.append((parent, child))
                if sym in term_syms:
                    if sym not in no_expand_logged:
                        diag.add("getter_setter_no_expand", sym)
                        no_expand_logged.add(sym)
                    continue  # 横展開しない（spec §8.3 生命線）
                _ingest(language, dialect, line, child, hop + 1)
        hop += 1

    for p, c in edges:
        graph.add_edge(p, c)

    # ヒット行の確定: 全エッジ集約後に chain を計算（決定的）
    indirect: list[Hit] = []
    seen = set()
    for (p, c) in sorted(set(edges)):
        if c in seen:
            continue
        seen.add(c)
        kind = sym_kind.get(c.symbol, "var")
        enc, replaced = enc_of.get(c.relpath, ("utf-8", False))
        language, dialect = _file_lang(source_root, c.relpath)
        # snippet/分類のため当該行を再取得（決定的・I/O 1 回）
        text = decode_bytes((source_root / c.relpath).read_bytes(), DEFAULT_FALLBACK)[0]
        line = text.split("\n")[c.lineno - 1] if c.lineno - 1 < len(text.split("\n")) else ""
        cat, conf = classify_hit(language, dialect, text, c.lineno, line)
        if kind in ("getter", "setter"):
            conf = "low"
        for chain in graph.chains_to(c, opts.max_depth, diag):
            indirect.append(Hit(
                keyword=keyword, language=language, file=c.relpath, lineno=c.lineno,
                ref_kind=_REF_KIND[kind], category=cat, category_sub="",
                usage_summary=f"{cat} ({language})", via_symbol=c.symbol,
                chain=chain, snippet=line,
                encoding=enc + (" 要確認" if replaced else ""), confidence=conf,
            ))
    return indirect


def _file_lang(root: Path, rel: str) -> tuple[str, str]:
    text = decode_bytes((Path(root) / rel).read_bytes(), DEFAULT_FALLBACK)[0]
    language = detect_language(rel, text[:4096], {})
    dialect = detect_shell_dialect(rel, text[:4096]) if language == "shell" else "bourne"
    return language, dialect
```

> **実装注（批判的レビュー対象）:** Phase 2a は正しさ優先で毎反復全ツリー走査（spec §8.2「差分走査の限定効果」＝確定シンボル再ヒット省略は Phase 2b）。`multiprocessing.Pool` の決定性は `_scan_file` が純関数＋結果を `rel` 昇順ソートで集約することで担保（spec §8.2 ワーカ横断集約）。chain 計算は全エッジ集約後の単一フェーズ＝走査/完了順非依存（spec §9）。`seen` による重複ヒット抑止は「同一 Occurrence」単位（異なる単純パスは `chains_to` が経路別行を生成＝spec §9 重複許容）。

- [ ] **Step 4: テストが通ることを確認（当該＋全体回帰ゼロ）**

Run: `python -m pytest tests/unit/test_fixedpoint.py -q`
Expected: PASS（6本：単一ホップ3＋多ホップ3）。`test_有限母集合で飽和し停止する` がタイムアウトせず PASS（停止性の実測）。

Run: `python -m pytest -q`
Expected: 全 PASS・0 failed / 0 error。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/fixedpoint.py src/grep_analyzer/provenance.py tests/unit/test_fixedpoint.py
git commit -m "feat(fixedpoint): 多ホップ不動点反復＋停止性＋jobs並列決定的集約（spec §8.1/§8.2）"
```

---

## Task 10: パイプライン配線と CLI オプション

**Files:**
- Modify: `src/grep_analyzer/pipeline.py`
- Modify: `src/grep_analyzer/cli.py`
- Test: `tests/integration/test_pipeline_fixedpoint.py`

direct ヒット生成後に `run_fixedpoint` を呼び indirect を併合し、`write_tsv` の決定的全順序ソート（既存 `model.sort_key`）で安定化。`pipeline._classify` は `classify.classify_hit` へ委譲（DRY・Phase 1 挙動不変）。CLI に Phase 2a オプションを追加（未指定は安全な既定で Phase 1 挙動を変えない＝既存 integration/golden 不変）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/integration/test_pipeline_fixedpoint.py` を新規作成:
```python
"""direct→不動点→併合 TSV の境界契約（spec §8/§9）。in-process 既定。"""

from pathlib import Path

from grep_analyzer.cli import main


def test_間接ヒットがdirectと併合され決定的TSVになる(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "C.java").write_text(
        'class C { static final String STATUS_OK = "S"; }\n', "utf-8"
    )
    (src / "U.java").write_text("class U { String x = STATUS_OK; }\n", "utf-8")
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "STATUS_OK.grep").write_text(
        'C.java:1:static final String STATUS_OK = "S";\n', "utf-8"
    )
    out = tmp_path / "out"
    rc = main([
        "--input", str(inp), "--output", str(out), "--source-root", str(src),
    ])
    assert rc == 0
    lines = (out / "STATUS_OK.tsv").read_text("utf-8-sig").splitlines()
    cols = lines[0].split("\t")
    rows = [dict(zip(cols, ln.split("\t"))) for ln in lines[1:]]
    kinds = {r["file"]: r["ref_kind"] for r in rows}
    assert kinds["C.java"] == "direct"
    assert kinds["U.java"] == "indirect:constant"
    # 決定的: 同じ入力で 2 回実行して完全一致
    out2 = tmp_path / "out2"
    main(["--input", str(inp), "--output", str(out2), "--source-root", str(src)])
    assert (out / "STATUS_OK.tsv").read_text("utf-8-sig") == (
        out2 / "STATUS_OK.tsv"
    ).read_text("utf-8-sig")


def test_max_depth0は間接追跡を行わずdirectのみ(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "C.java").write_text(
        'class C { static final String STATUS_OK = "S"; }\n', "utf-8"
    )
    (src / "U.java").write_text("class U { String x = STATUS_OK; }\n", "utf-8")
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "STATUS_OK.grep").write_text(
        'C.java:1:static final String STATUS_OK = "S";\n', "utf-8"
    )
    out = tmp_path / "out"
    main([
        "--input", str(inp), "--output", str(out), "--source-root", str(src),
        "--max-depth", "0",
    ])
    rows = (out / "STATUS_OK.tsv").read_text("utf-8-sig").splitlines()[1:]
    assert all("direct" in r for r in rows)  # U.java の間接行は出ない
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/integration/test_pipeline_fixedpoint.py -q`
Expected: FAIL（`--max-depth` 未知引数、または U.java 間接行が出ず AssertionError）

- [ ] **Step 3: 実装**

`src/grep_analyzer/pipeline.py` を編集。`_classify` を `classify.classify_hit` へ委譲し、`run` に不動点併合を追加。

`pipeline.py` のインポート群と `_classify` を置換:
```python
from grep_analyzer.classify import classify_hit
from grep_analyzer.fixedpoint import EngineOptions, run_fixedpoint
```
（既存の `from grep_analyzer.classifiers...` 3 行は `classify` 経由になるため削除。`detect_*`/`encoding`/`ingest`/`model`/`tsv`/`diagnostics` の import は残す）

`_classify` 関数全体を削除し、呼び出し箇所 `category, confidence = _classify(language, dialect, file_text, lineno, content)` を:
```python
            category, confidence = classify_hit(language, dialect, file_text, lineno, content)
```
に置換。

`run` のシグネチャと末尾を変更（既定値は Phase 1 挙動を変えない）:
```python
def run(
    input_dir: Path,
    output_dir: Path,
    source_root: Path,
    opts: EngineOptions | None = None,
) -> int:
    """input/*.grep を処理し、direct＋不動点 indirect を併合した TSV を出力する。"""
    diag = Diagnostics()
    output_dir.mkdir(parents=True, exist_ok=True)
    if opts is None:
        opts = EngineOptions(
            max_depth=10, min_specificity=2, stoplist_path=None, include=[],
            exclude=list(__import__("grep_analyzer.walk", fromlist=["DEFAULT_EXCLUDE"]).DEFAULT_EXCLUDE),
            jobs=1, follow_symlinks=False, max_file_bytes=5_000_000, max_symbols=100_000,
        )

    for grep_file in sorted(Path(input_dir).glob("*.grep")):
        keyword = grep_file.stem
        raw_bytes = grep_file.read_bytes()
        text, _, _ = decode_bytes(raw_bytes, DEFAULT_FALLBACK)
        hits: list[Hit] = []
        # （既存の for raw_line ... hits.append(Hit(...)) ループは不変）
        ...
        indirect = run_fixedpoint(hits, Path(source_root), opts, diag)
        write_tsv(output_dir / f"{keyword}.tsv", hits + indirect, "utf-8-sig")

    (output_dir / "diagnostics.txt").write_text(diag.render(), encoding="utf-8")
    return 0
```
> 注: `...` は既存 Phase 1.5 の grep 行ループ本体（無改変）。`write_tsv(... hits + indirect ...)` と `indirect = run_fixedpoint(...)` の 2 行を `write_tsv` 直前に挿入する点のみが差分。`write_tsv` は既存どおり `model.sort_key` で全順序安定ソート＝direct/indirect 混在でも決定的（spec §9）。

`src/grep_analyzer/cli.py` を編集して Phase 2a オプションを追加:
```python
import argparse
from pathlib import Path

from grep_analyzer.fixedpoint import EngineOptions
from grep_analyzer.pipeline import run
from grep_analyzer.walk import DEFAULT_EXCLUDE


def main(argv: list[str] | None = None) -> int:
    """引数をパースし direct＋不動点パイプラインを実行する（spec §10.4）。"""
    p = argparse.ArgumentParser(prog="grep_analyzer")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--source-root", required=True, dest="source_root")
    p.add_argument("--max-depth", type=int, default=10, dest="max_depth")
    p.add_argument("--min-specificity", type=int, default=2, dest="min_specificity")
    p.add_argument("--stoplist", default=None)
    p.add_argument("--include", action="append", default=[])
    p.add_argument("--exclude", action="append", default=None)
    p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--follow-symlinks", action="store_true", dest="follow_symlinks")
    p.add_argument("--max-file-bytes", type=int, default=5_000_000, dest="max_file_bytes")
    p.add_argument("--max-symbols", type=int, default=100_000, dest="max_symbols")
    args = p.parse_args(argv)
    opts = EngineOptions(
        max_depth=args.max_depth, min_specificity=args.min_specificity,
        stoplist_path=Path(args.stoplist) if args.stoplist else None,
        include=args.include,
        exclude=args.exclude if args.exclude is not None else list(DEFAULT_EXCLUDE),
        jobs=args.jobs, follow_symlinks=args.follow_symlinks,
        max_file_bytes=args.max_file_bytes, max_symbols=args.max_symbols,
    )
    return run(
        input_dir=Path(args.input), output_dir=Path(args.output),
        source_root=Path(args.source_root), opts=opts,
    )
```

- [ ] **Step 4: テストが通ることを確認（当該＋全体回帰ゼロ）**

Run: `python -m pytest tests/integration/test_pipeline_fixedpoint.py -q`
Expected: PASS（2本）

Run: `python -m pytest -q`
Expected: 全 PASS・**0 failed / 0 error**。**特に既存 golden 10 ケースと `tests/unit/test_pipeline.py`・`tests/integration/test_pipeline_dialect.py` が不変**（Phase 1.5 の direct 出力は indirect が増えない合成ツリーでは変わらない）。golden が動いたら writing-tests「大量churn＝構造を疑う」に従い **commit せず原因究明**（Task 12 で意図的に golden を足すまで既存は不変が正）。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/pipeline.py src/grep_analyzer/cli.py tests/integration/test_pipeline_fixedpoint.py
git commit -m "feat(pipeline): direct＋不動点 indirect 併合配線＋CLIオプション（spec §8/§10.4）"
```

---

## Task 11: §8.4 診断の正本（全件列挙の契約）

**Files:**
- Test: `tests/integration/test_diagnostics_phase2.py`

spec §8.4 は「唯一の正本」。横展開抑止／集合上限切り捨て／生成コード除外／symlink 重複／max-depth 到達／getter/setter 非展開を **diagnostics に必ず明示**（spec §1/§8.3/§10.3 はここを参照）。本タスクは実装追加なし＝既存実装が §8.4 正本の契約を満たすことを境界テストで固定（点アサート・負の契約含む）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/integration/test_diagnostics_phase2.py` を新規作成:
```python
"""§8.4 診断正本の境界契約（spec §8.4/§10.3）。"""

from pathlib import Path

from grep_analyzer.cli import main


def _run(tmp_path, src_files: dict, grep: str, keyword: str, extra=None):
    src = tmp_path / "src"
    src.mkdir()
    for rel, body in src_files.items():
        f = src / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, "utf-8")
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / f"{keyword}.grep").write_text(grep, "utf-8")
    out = tmp_path / "out"
    argv = ["--input", str(inp), "--output", str(out), "--source-root", str(src)]
    main(argv + (extra or []))
    return (out / "diagnostics.txt").read_text("utf-8")


def test_getter横展開抑止が診断に記録される(tmp_path: Path):
    d = _run(
        tmp_path,
        {"S.java": "class S{ void m(){ int v = a.getName(); } }\n",
         "T.java": "class T{ String n = b.getName(); }\n"},
        "S.java:1:int v = a.getName();\n", "v",
    )
    assert "getter_setter_no_expand\tgetName" in d


def test_集合上限切り捨てが診断に記録される(tmp_path: Path):
    d = _run(
        tmp_path,
        {"A.java": "class A{ int aa=1; int bb=2; int cc=3; }\n"},
        "A.java:1:int aa=1; int bb=2; int cc=3;\n", "aa",
        extra=["--max-symbols", "1", "--min-specificity", "1"],
    )
    assert "symbol_rejected\tcapped" in d


def test_生成コード除外が診断に記録される(tmp_path: Path):
    d = _run(
        tmp_path,
        {"build/Gen.java": "class Gen{ String x = STATUS_OK; }\n",
         "K.java": 'class K{ static final String STATUS_OK="S"; }\n'},
        'K.java:1:static final String STATUS_OK="S";\n', "STATUS_OK",
    )
    assert "walk_excluded\tbuild/Gen.java" in d


def test_max_depth到達が診断に記録される(tmp_path: Path):
    d = _run(
        tmp_path,
        {"A.java": "class A{ static final int K1=1; }\n",
         "B.java": "class B{ static final int K2=K1; }\n",
         "C.java": "class C{ int z=K2; }\n"},
        "A.java:1:static final int K1=1;\n", "K1",
        extra=["--max-depth", "1"],
    )
    assert "prov_max_depth" in d
```

- [ ] **Step 2: 失敗を確認 → 必要なら最小修正**

Run: `python -m pytest tests/integration/test_diagnostics_phase2.py -q`
Expected: 基本 PASS（Task 8/9 で各診断カテゴリは実装済み）。FAIL する契約があれば、その診断 `diag.add(...)` を該当モジュール（`fixedpoint`/`walk`/`stoplist` 呼出箇所）に **最小追加**して PASS させる（テストを緩めない）。`symbol_rejected\tcapped` の表記は Task 9 `_ingest` の `diag.add("symbol_rejected", f"{reason}\t{sym}")` と整合。

- [ ] **Step 3: 全体回帰ゼロを確認**

Run: `python -m pytest -q`
Expected: 全 PASS・0 failed / 0 error。

- [ ] **Step 4: コミット**

```bash
git add tests/integration/test_diagnostics_phase2.py src/grep_analyzer/
git commit -m "test(diagnostics): §8.4 正本の全件列挙契約を境界テストで固定（spec §8.4）"
```

---

## Task 12: golden 多ホップ代表ケース（既存10不変）

**Files:**
- Create: `tests/golden/cases/indirect_constant/{input,src,expected}/...`
- Create: `tests/golden/cases/indirect_var_shell/{input,src,expected}/...`
- Create: `tests/golden/cases/chain_multipath/{input,src,expected}/...`
- Create: `tests/golden/cases/getter_no_expand/{input,src,expected}/...`
- Create: `tests/golden/cases/symlink_dedup/{input,src,expected}/...`

spec §11 必須回帰: 汎用 getter 横展開抑止／chain 複数経路の決定性（別行）／symlink 重複排除／indirect:constant・var 網羅。`category_sub` は空固定。既存 golden（`java_direct` 等 10 ケース）は **不変**（多ホップが増えないツリー設計＝Phase 1.5 で確立した不変条件）。`tests/golden/conftest.py` は無改変（`cases/*/` 自動 parametrize 済み）。

- [ ] **Step 1: golden ケースのソース・入力を作る（期待値はまだ作らない）**

`tests/golden/cases/indirect_constant/src/C.java`:
```java
class C { static final String STATUS_OK = "S"; }
```
`tests/golden/cases/indirect_constant/src/U.java`:
```java
class U { String x = STATUS_OK; }
```
`tests/golden/cases/indirect_constant/input/STATUS_OK.grep`:
```
C.java:1:static final String STATUS_OK = "S";
```

`tests/golden/cases/indirect_var_shell/src/run.sh`:
```sh
CODE="X"
use $CODE
```
`tests/golden/cases/indirect_var_shell/src/other.sh`:
```sh
echo CODE
```
`tests/golden/cases/indirect_var_shell/input/CODE.grep`:
```
run.sh:1:CODE="X"
```

`tests/golden/cases/chain_multipath/src/A.java`:
```java
class A { static final int K = 1; }
```
`tests/golden/cases/chain_multipath/src/P.java`:
```java
class P { int p = K; int q = K; }
```
`tests/golden/cases/chain_multipath/input/K.grep`:
```
A.java:1:static final int K = 1;
```

`tests/golden/cases/getter_no_expand/src/S.java`:
```java
class S { void m(){ int v = a.getName(); } }
```
`tests/golden/cases/getter_no_expand/src/T.java`:
```java
class T { String n = b.getName(); String m = c.getName(); }
```
`tests/golden/cases/getter_no_expand/input/v.grep`:
```
S.java:1:int v = a.getName();
```

`tests/golden/cases/symlink_dedup/src/real.java` :
```java
class R { String x = STATUS_OK; }
```
`tests/golden/cases/symlink_dedup/src/K.java`:
```java
class K { static final String STATUS_OK = "S"; }
```
`tests/golden/cases/symlink_dedup/input/STATUS_OK.grep`:
```
K.java:1:static final String STATUS_OK = "S";
```
symlink はリポジトリに含めず golden 実行時に conftest が作るのは過剰結合になるため、本ケースは **重複排除の決定性**を「同一内容の通常ファイル2つでも代表のみ・順序決定的」に簡約して固定する（真の symlink 重複排除は `tests/unit/test_walk.py::test_同一実体の重複は正規化パス辞書順の代表のみ走査` が担保。golden は決定性の最終形のみ固定）。`src/dup_a.java` と `src/dup_b.java` を `real.java` と同内容で追加し、期待 TSV が relpath 昇順で安定することを固定する。

- [ ] **Step 2: 期待 TSV を生成（必ず目視レビュー）**

各ケースで実行し出力を期待値として確定:
```bash
for c in indirect_constant indirect_var_shell chain_multipath getter_no_expand symlink_dedup; do
  python -m grep_analyzer --input tests/golden/cases/$c/input \
    --output tests/golden/cases/$c/expected \
    --source-root tests/golden/cases/$c/src
done
rm -f tests/golden/cases/*/expected/diagnostics.txt
```
Run: `git diff --stat tests/golden/cases/`（新規 expected/*.tsv のみ。`expected/diagnostics.txt` は除外）
**目視レビュー必須**（writing-tests Golden「反射的 regen は alarm を殺す」）。確認点:
- `indirect_constant/expected/STATUS_OK.tsv`: `C.java` 行 `ref_kind=direct`、`U.java` 行 `ref_kind=indirect:constant`・`via_symbol=STATUS_OK`・`chain=STATUS_OK@C.java:1 -> STATUS_OK@U.java:1`・`category_sub` 空。
- `chain_multipath/expected/K.grep` 相当 `K.tsv`: `P.java` への到達が **経路ごとに別行**（`p = K` と `q = K` で 2 行、chain が決定的順）。
- `getter_no_expand/expected/v.tsv`: `getName` 行は `ref_kind=indirect:getter`・`confidence=low`、`T.java` の 2 出現とも報告されるが **そこから先のシンボルは出ない**（横展開なし）。
- `symlink_dedup/expected/STATUS_OK.tsv`: 同内容重複でも代表のみ・relpath 昇順で安定。
- 既存 10 ケースの `expected/` は `git diff` に出ない（不変）。出たら **構造を疑い停止**（Task 10 注記）。

- [ ] **Step 3: golden が緑かつ既存不変を確認**

Run: `python -m pytest tests/golden -q`
Expected: 全 PASS（既存10＋新規5＝15 ケース parametrize）。

Run: `python -m pytest -q`
Expected: 全 PASS・0 failed / 0 error。

- [ ] **Step 4: コミット（golden 規約）**

```bash
git add tests/golden/cases/indirect_constant tests/golden/cases/indirect_var_shell \
  tests/golden/cases/chain_multipath tests/golden/cases/getter_no_expand \
  tests/golden/cases/symlink_dedup
git commit -m "chore(golden): 多ホップ代表5ケース追加（chain複数経路/getter抑止/重複排除・spec §11）"
```

---

## Task 13: Phase 2a 全テスト緑化と完了確認

**Files:**
- Modify: `docs/superpowers/plans/phase0-gate-result.md`

- [ ] **Step 1: 全テスト実行**

Run: `cd /workspaces/grep_helpers2 && python -m pytest -q`
Expected: 全 PASS（Phase 1.5 の 78 ＋ Phase 2a 追加分。0 failed / 0 error）。失敗があれば該当 Task に戻る（完了主張しない＝verification-before-completion）。

- [ ] **Step 2: spec §15 フェーズ2（2a 範囲）／§8 充足をチェックリスト照合**

`docs/superpowers/specs/2026-05-16-grep-analyzer-design.md` §8/§15 と実装の対応を確認:
- §8.1 反復・停止性 → Task 8/9（`fixedpoint.run_fixedpoint`／`test_有限母集合で飽和し停止する`）
- §8.3 採否・getter/setter 非投入の生命線 → Task 2/3（`stoplist.admit`/`partition`）
- §8.3 決定的切り捨て → Task 2（`test_集合上限超過は決定的に切り捨てる`）
- §8.2 来歴集約・jobs 並列決定性 → Task 9（`test_jobs1とjobsNでTSV完全一致の決定的集約`）
- §8.2 走査・symlink 重複排除・生成コード除外 → Task 5（`walk.py`）
- §9 chain 正規形・複数経路の別行決定性 → Task 6/12（`provenance`／`chain_multipath` golden）
- §8.4 診断正本（全件列挙）→ Task 11（`test_diagnostics_phase2.py`）
- direct/indirect 併合の完全決定性 → Task 10（`test_間接ヒットがdirectと併合され決定的TSVになる`）＋ 既存 golden 10 不変

- [ ] **Step 3: 完了記録を追記しコミット**

`docs/superpowers/plans/phase0-gate-result.md` 末尾に「## Phase 2a 完了記録」（完了日 UTC、コミット範囲、全テスト結果、上記 §8/§15 対応表、Phase 2b/Phase 3 への申し送り＝下記「Phase 2a の境界」を要約）を追記。

```bash
git add docs/superpowers/plans/phase0-gate-result.md
git commit -m "chore: Phase 2a 完了（不動点エンジン正しさ・決定性コア）"
```

---

## Phase 2a の境界（2b / Phase 3 は別計画）

- **本計画に含まない（Phase 2b）**: spec §8.2 の資源 degrade ＝ `--memory-limit` 超過時の来歴グラフ・ディスクスピル、degrade 優先順位（決定的シンボル切り捨て→スピル→**オートマトン分割＝複数パス再走査**・最大走査パス上限）、任意 `ripgrep` 一次粗フィルタ（`@pytest.mark.requires_ripgrep` 隔離）、§8.2 差分走査の限定効果（確定シンボル再ヒット再走査の省略）。Phase 2a は正しさ優先で毎反復全ツリー走査。
- **本計画に含まない（Phase 3）**: 60GB perf ベースライン（`tests/perf/` `@pytest.mark.perf` 非ゲート）、`--resume` キーワード単位再開、diagnostics の上限超過時カテゴリ別集約＋代表サンプル縮約（spec §10.3）、規模分割 `<keyword>.partNN.tsv`（spec §9）、`requirements.lock`（spec §4.1・版/ハッシュ固定＝配備正式化。**ユーザ決定により Phase 3 へ送る**）。
- **Phase 2a の既知の弱点（批判的レビュー・2b 精密化対象）**: (1) `Hit` に方言列が無いため seed 方言を snippet ヒューリスティックで保守再判定（`_seed_dialect`）＝ §8.4 既知境界。2b で seed 側に方言を運ぶ。(2) Java/C の constant/var 抽出は字句正規表現（tree-sitter 型解決はしない＝spec §8.3 の前提どおり）。精度は handcrafted の領分（非ゲート）。(3) 毎反復全走査の性能は Phase 3 perf で実測（Phase 2a は決定性・正しさのみ責務）。
- Phase 2a の成果物は「direct＋多ホップ indirect を偽陽性抑止しつつ `--jobs` 並列でも完全決定的に出し、chain 複数経路を golden で固定した動くツール」であり、それ単体でテスト可能・出荷可能。

---

## Self-Review（計画完成後・本計画著者によるチェック）

**1. spec coverage（§8/§9/§15 フェーズ2 のうち 2a 範囲）:**
- §8.1 抽出規則 → Task 1（`extract_chase_symbols`）✓ / 反復・停止性 → Task 8/9 ✓ / シンボル循環・max-depth → Task 6/9（`chains_to`・`prov_max_depth`）✓
- §8.2 Aho-Corasick → Task 4 ✓ / multiprocessing 決定的集約 → Task 9 ✓ / symlink・生成コード → Task 5 ✓ ／ memory-limit/spill/オートマトン分割/ripgrep → **意図的に Phase 2b（境界節に明記）**
- §8.3 静的採否・getter/setter 非投入・決定的切り捨て → Task 2/3 ✓
- §8.4 診断正本（全件列挙）→ Task 11 ✓（getter_setter_no_expand / symbol_rejected / walk_excluded / prov_max_depth / symlink_dedup）
- §9 ref_kind 列・chain 正規形・複数経路別行・決定性ソート → Task 6/10/12 ✓（`sort_key` は既存 `model.py` 再利用）
- §15 フェーズ2「chain 複数経路の決定性を golden で固定」→ Task 12 `chain_multipath` ✓ / 「pyahocorasick G1 着手前提」→ Task 0 ✓
- §10.4 CLI（`--max-depth`/`--min-specificity`/`--stoplist`/`--include`/`--exclude`/`--jobs`/`--follow-symlinks`）→ Task 10 ✓ ／ `--memory-limit`/`--use-ripgrep`/`--resume`/`--progress`/`--output-encoding`/`--encoding-fallback`/`--lang-map` は 2b/Phase 3（境界節に明記）

**2. Placeholder scan:** 各 Task に実コード／実コマンド／期待出力を記載。`...`（Task 10 Step 3）は「既存無改変ループ本体」を指す明示注記付きで、差分行を特定済み＝プレースホルダではない。「TBD/後で」表現なし。

**3. Type consistency:** `ChaseSymbols`/`SymbolPolicy`/`AdmissionResult`/`Partition`/`Occurrence`/`ProvenanceGraph.chains_to`/`is_seed`/`EngineOptions`/`run_fixedpoint`/`classify_hit`/`walk_files`/`automaton.build`/`scan_line` の名称・引数順を冒頭「型・シグネチャ契約」と各 Task 実装で一致確認済み。`_REF_KIND` のキー（constant/var/getter/setter）は `chase.ChaseSymbols` のフィールドと整合。`pipeline.run` の `opts: EngineOptions | None=None` 既定は Phase 1 挙動不変（既存 golden/integration の回帰ゼロを Task 10 Step 4 で要求）。

> 既知のレビュー観点（メモリ「フェーズ移行前に複数回の批判的AIレビュー」に従い、実行前に重点レビューを推奨）: ① `_seed_dialect` の snippet ヒューリスティックの妥当性 ② Task 9 の不動点反復における `just`（当パス新規シンボル）絞り込みと多経路 chain 集約の網羅性・決定性 ③ Java `_JAVA_VAR_RE`/`_JAVA_CONST_RE` の字句抽出が generic（`Map<K,V>`）・配列・アノテーションで誤抽出しないか ④ `chains_to` の DFS が大規模グラフで指数爆発しないか（Phase 2a は小規模合成のみ・実規模は Phase 2b/3 で degrade）。
