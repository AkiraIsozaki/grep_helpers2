# grep_analyzer Phase 2a（不動点エンジンの正しさ・決定性コア） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **改訂履歴:** v1（`docs(plan)` コミット）→ **v2（本書・3並行批判的レビュー反映）**。v1 の Critical/High/Medium/Low を spec/コードで技術検証し、実在欠陥を全面修正。主な修正: ①来歴エッジを spec §8.2 準拠の **シンボル間エッジ＋単純パス（spec §9「同一シンボルを二度通らない」をシンボル循環打ち切りとして適用）** に再設計、②seed 除外を **seed 物理行 (rel,lineno) 基準**に修正（keyword≠シンボル名でも seed 行を間接再出力しない）、③§8.3 集合上限を **大域・(発見ホップ, 長さ, 辞書順)** に修正（per-call cap を廃止）、④getter/setter を **全反復走査・全件 low 報告・横展開のみ抑止**（spec §8.4 全件報告）に修正、⑤seed 方言を **seed ファイルを読み `detect_shell_dialect`**（spec §5.1 決定的）に修正・snippet ヒューリスティック/`s.snippet[:0]` 死コード除去、⑥`max_depth` を **chain のホップ数（` -> ` 本数）に単一定義**して engine/chains/CLI を串刺し、⑦字句抽出に **文字列リテラル/コメントマスキング**を追加（偽陽性ノイズ抑止＝spec §8）、⑧Java 定数正規表現を **static∧final・generic/配列許容**に修正、⑨I/O を **`_scan_file` が text/言語/方言を返す単一デコード**に修正（三重デコード廃止）、⑩**fixedpoint を 1 タスクで一度だけ実装**（v1 の Task8→Task9 二重実装・捨て実装を廃止）、⑪**既存 golden の正確な影響（shell_direct/oracle_direct のみ意図的に regen、他8不変）を明記**、⑫`chain_multipath` を真のダイヤモンドグラフに、⑬`--lang-map` を direct/indirect 対称に配線、⑭`DEFAULT_EXCLUDE` を v1 言語スコープに絞り segment マッチャ化、⑮`__import__` 廃止、⑯§15 の 2a/2b 分割正当化・経路爆発/ストリーミングの 2b 申し送り・diagnostics 決定性/全件性テストを追加。

**Goal:** Phase 1/1.5 の direct-only 決定性基盤の上に、spec §8.1 不動点反復＋§8.3 シンボル採否（汎用 getter 横展開の構造的抑止）＋§8.2 来歴集約を実装し、多ホップ間接ヒット（`indirect:constant|var|getter|setter`）と chain 複数経路を **`--jobs` 並列でも完全決定的** に出力する。偽陽性抑止と停止性を小規模合成ツリーで実測検証し、chain 複数経路の決定性を golden で固定する。

**Architecture:** 既存 `grep_analyzer` パッケージを後方互換で拡張する。Phase 1.5 で確定した決定的コア（`dispatch`/`classifiers`/`model`/`tsv`/`diagnostics`/`encoding`/`ingest`/`proc_preprocess`）は変更しない。`chase.py` に **文字列/コメントマスキング付き分類抽出 `extract_chase_symbols`**（`extract_var_symbols` は不変のまま内部再利用）を追加。新規モジュール `stoplist.py`（静的採否＋大域決定的切り捨て＋getter/setter 非投入）／`automaton.py`（pyahocorasick＋識別子境界）／`walk.py`（決定的ツリー走査・symlink 重複排除）／`provenance.py`（**シンボル来歴グラフ・単純パス chain 正規形**）／`classify.py`（pipeline と共有する行分類）／`fixedpoint.py`（反復エンジン・一度だけ実装）を追加。`pipeline.py` は direct ヒット生成後にエンジンを呼び indirect を併合、`cli.py` に Phase 2a オプションを追加。**2b（資源 degrade：`--memory-limit` スピル・オートマトン分割多パス・`ripgrep` 一次フィルタ・chain 経路数爆発の degrade・bytes ストリーミング化）と Phase 3（60GB perf・`--resume`・diagnostics 縮約・規模分割・`requirements.lock`）は本計画の範囲外**（末尾「Phase 2a の境界」で spec §15 根拠付きに正当化）。

**Tech Stack:** Python 3.12 / pytest / `pyahocorasick==2.1.0`（Phase 2 着手ゲートで wheel 実証済み＝`phase0-gate-result.md`「Phase 2 着手ゲート（pyahocorasick G1 相当）記録」PASS。`Automaton.iter(s)` は `(end_index, value)` を返し**部分文字列も拾う**ため識別子境界フィルタ必須）。tree-sitter/chardet は既存のまま。設計書 `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`（v7 が正・spec が常に優先）、テスト規約 `.claude/skills/writing-tests.md`、コーディング規約 `.claude/skills/coding-conventions.md` に従う（docstring/コメント日本語、テスト名日本語、古典学派+TDD、外部I/O境界＝ファイルのみ本物）。

**型・シグネチャ契約（全タスク共通・タスク間で不変。Self-Review 3 で串刺し確認）:**

- `chase.ChaseSymbols`（frozen dataclass）: `.constants/.vars/.getters/.setters: tuple[str, ...]`
- `chase.mask_literals(language: str, line: str) -> str`（文字列/コメントを同幅の空白へ。行長・桁不変）
- `chase.extract_chase_symbols(language: str, dialect: str, line: str) -> ChaseSymbols`（内部で `mask_literals` 適用後に抽出）
- `stoplist.SymbolPolicy(min_specificity: int, user_stoplist: frozenset[str])`（**cap は持たない**＝大域 cap は fixedpoint 側）
- `stoplist.load_stoplist(path: pathlib.Path | None) -> frozenset[str]`
- `stoplist.LANG_KEYWORDS: dict[str, frozenset[str]]`
- `stoplist.admit(symbols: list[str], language: str, policy: SymbolPolicy) -> AdmissionResult`、`AdmissionResult(accepted: list[str], rejected: list[tuple[str, str]])`、reason ∈ `{"keyword","too_short","user_stoplist"}`
- `stoplist.partition(cs: chase.ChaseSymbols, language: str, policy: SymbolPolicy) -> Partition`、`Partition(chase: list[str], terminal: list[str], rejected: list[tuple[str,str]])`
- `automaton.build(symbols: list[str]) -> ahocorasick.Automaton | None`（空・空文字除去後に空なら None）
- `automaton.scan_line(au, line: str) -> list[str]`（識別子境界一致シンボルの昇順ユニーク）
- `walk.walk_files(root, *, include, exclude, follow_symlinks, max_file_bytes, diag) -> Iterator[tuple[str, pathlib.Path]]`、`walk.DEFAULT_EXCLUDE: tuple[str, ...]`
- `provenance.Occurrence`（frozen, order=True）: `symbol: str, relpath: str, lineno: int`
- `provenance.ProvenanceGraph`:
  - `add_seed(occ: Occurrence)` / `is_seed_location(relpath: str, lineno: int) -> bool`
  - `add_edge(parent: Occurrence, child: Occurrence)`
  - `chains_to(target: Occurrence, *, max_depth: int, max_paths: int, diag) -> list[str]`
  - hop 表記 `f"{symbol}@{relpath}:{lineno}"`・` -> ` 連結（spec §9）
- `classify.classify_hit(language: str, dialect: str, file_text: str, lineno: int, content: str) -> tuple[str, str]`
- `fixedpoint.EngineOptions`（dataclass）: `max_depth:int, min_specificity:int, stoplist_path:Path|None, lang_map:dict[str,str], include:list[str], exclude:list[str], jobs:int, follow_symlinks:bool, max_file_bytes:int, max_symbols:int, max_paths:int`
- `fixedpoint.run_fixedpoint(seed_hits: list[Hit], source_root: pathlib.Path, opts: EngineOptions, diag: Diagnostics) -> list[Hit]`（戻り値は indirect Hit のみ）

**spec 解釈の明示（次レビューで再検証可能にするための確定事項）:**

- **`max_depth` の単一定義**: chain の **ホップ数（` -> ` の本数）の上限**。`--max-depth 0` ＝ ホップ 0 ＝ direct のみ（間接追跡しない）。engine の追跡深さ・`provenance.chains_to` のパス長・CLI の三者をこの単一定義で串刺しする（spec §8.1 手順6 / §9「`--max-depth` 超過パスも打ち切り」）。
- **来歴グラフと単純パス（spec §8.2/§9）**: ノード＝`Occurrence(symbol,relpath,lineno)`。エッジ＝「parent の出現行から chase シンボル child が抽出され、child がツリー上で出現した」関係（spec §8.2 エッジ断片 `(発見元シンボル,発見シンボル,file,lineno)` をシンボル間で確定）。**単純パス**＝(a) 同一 Occurrence を二度通らない かつ (b) **起点（seed=keyword の役割。spec §9 の「調査対象の文言」）以降の追跡識別子が二度現れない**（spec §9「同一シンボルを二度通らない」を多ホップ chase 循環の打ち切りとして適用）。keyword の文言と最初の追跡識別子が同名（例 keyword `CODE` と変数 `CODE`）でも、keyword は文言の役割で追跡識別子とは別ノード種別なので「`CODE@def -> CODE@use`」は許容（PRD の主目的＝keyword シンボル利用箇所の列挙を満たす）。定数連鎖 A→B→A の循環は最初の再訪エッジで打ち切り `prov_cycle_cut` を記録。
- **getter/setter（spec §8.3/§8.4）**: chase 集合へ投入しない（**横展開＝そのヒット行からの再抽出をしない**）が、**automaton には全反復投入し全出現を `ref_kind=indirect:getter|setter`・`confidence=low` で全件報告**する（spec §8.4「同名メソッド全件 confidence=low」）。「横展開抑止」と「報告範囲の限定」を混同しない。

---

## Task 0: 着手ゲート（Phase 1.5 緑＋pyahocorasick G1・コードなし）

spec §15 フェーズ2 着手前提: (1) Phase 1.5 全テスト緑（回帰判別の基準固定。writing-tests「大量churn＝構造を疑う」）、(2) `pyahocorasick` の §4.2 G1 相当 wheel 実証 PASS（spec §15 フェーズ2 唯一の着手前提）。

- [ ] **Step 1: ベースライン全緑を確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest -q`
Expected: `78 passed`（0 failed / 0 error）。78 と異なるなら着手しない。

- [ ] **Step 2: Phase 2 着手ゲート（pyahocorasick G1）PASS 記録の存在を確認**

Run: `grep -nF 'G1 相当判定: **PASS**' docs/superpowers/plans/phase0-gate-result.md`
Expected: 1 行ヒット（固定文字列検索 `-F` でエスケープ問題を回避）。ヒットしなければ着手不可（spec §4.2）。

- [ ] **Step 3: pyahocorasick が現環境で import 可能か確認**

Run: `python -c "import ahocorasick, importlib.metadata as m; print(m.version('pyahocorasick'))"`
Expected: `2.1.0`。失敗時は `python -m pip install --no-index --find-links wheelhouse "pyahocorasick==2.1.0"` 後に再確認。

- [ ] **Step 4: ゲート判定を記録しコミット**

`docs/superpowers/plans/phase0-gate-result.md` 末尾に「## Phase 2a 着手ゲート記録」（記録日 UTC、`78 passed`、pyahocorasick G1 PASS 参照、判定 PASS）を追記。

```bash
git add docs/superpowers/plans/phase0-gate-result.md
git commit -m "chore: Phase 2a 着手ゲート記録（78 passed / pyahocorasick G1 PASS）"
```

注: `requirements.lock`（spec §4.1）は Phase 3 へ送る決定済み（ユーザ判断）。`--memory-limit`/オートマトン分割/`ripgrep`/chain 経路爆発 degrade は Phase 2b。これらは本計画の着手をブロックしない（Phase 2a は pyahocorasick＋標準ライブラリ＋既存依存で完結）。

---

## Task 1: 文字列/コメントマスキング付き分類抽出 `chase.extract_chase_symbols`

**Files:**
- Modify: `src/grep_analyzer/chase.py`
- Test: `tests/unit/test_chase.py`

spec §8 冒頭「偽陽性ノイズは許容しない」。字句抽出の前に **文字列リテラル・コメントを同幅空白へマスク**し（行長・桁不変＝行番号と境界判定に影響しない）、文字列内 `"x=1"` 等を追跡シンボル化しない。spec §9 ref_kind×言語表に従い `constant/var/getter/setter` を決定的抽出。`extract_var_symbols` は不変（Phase 1.5 既存7テスト維持）、var カテゴリは内部再利用。Java 定数は **static∧final 必須・generic/配列型許容**。Pro\*C はホスト変数 `:var` を `:` を剥がした原識別子で var 抽出（spec §8.1 手順5）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_chase.py` の末尾に追記:
```python
from grep_analyzer.chase import ChaseSymbols, extract_chase_symbols, mask_literals


def test_文字列とコメントをマスクし行長を保つ():
    assert mask_literals("java", 'String s = "x=1"; // y=2') == 'String s =       ;        '
    assert len(mask_literals("c", 'a=1; /* z=9 */ b=2')) == len('a=1; /* z=9 */ b=2')


def test_文字列内の代入様字句は追跡シンボルにしない():
    cs = extract_chase_symbols("java", "", 'String s = "url=/x"; int n = 1;')
    assert "url" not in cs.vars and cs.vars == ("s", "n")


def test_Java定数はstaticかつfinalのみでgenericと配列を許容する():
    assert extract_chase_symbols(
        "java", "", "private static final Map<String, Integer> CODE_MAP = init();"
    ).constants == ("CODE_MAP",)
    assert extract_chase_symbols(
        "java", "", "static final int[] CODES = a;"
    ).constants == ("CODES",)
    # final のみ（static 無し）は定数でなく var（spec §9 は static final 定数）
    cs = extract_chase_symbols("java", "", "final int X = 1;")
    assert cs.constants == () and cs.vars == ("X",)
    # public static（final 無し）は定数でない
    assert extract_chase_symbols("java", "", "public static int Y = 1;").constants == ()


def test_Javaのgetterとsetterとvarをマスクのうえ分類抽出する():
    cs = extract_chase_symbols("java", "", "int count = svc.getName(); obj.setValue(count);")
    assert cs.vars == ("count",)
    assert cs.getters == ("getName",) and cs.setters == ("setValue",)


def test_C定義とconst定数とProCホスト変数を抽出する():
    assert extract_chase_symbols("c", "", "#define MAX_LEN 10").constants == ("MAX_LEN",)
    assert extract_chase_symbols("c", "", "const int FOO = 1;").constants == ("FOO",)
    assert extract_chase_symbols("c", "", "int n = 3;").vars == ("n",)
    # Pro*C ホスト変数 :var は : を剥がした原識別子で var（spec §8.1 手順5）
    assert extract_chase_symbols("proc", "", "EXEC SQL SELECT c INTO :host FROM t;").vars == ("host",)


def test_bourneのreadonlyは定数SQLとcshellはvarのみ():
    assert extract_chase_symbols("shell", "bourne", "readonly CODE=1").constants == ("CODE",)
    assert extract_chase_symbols("shell", "bourne", 'NAME="x"').vars == ("NAME",)
    cs = extract_chase_symbols("sql", "", "v_code := 'X';")
    assert cs.vars == ("v_code",) and cs.getters == () and cs.constants == ()
    assert extract_chase_symbols("shell", "cshell", "set CODE = 1").vars == ("CODE",)


def test_var抽出は既存extract_var_symbolsと一致する():
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

# 言語別の文字列/コメント区間。マスクは同幅空白置換（行長・桁・行番号を保存）。
_MASK_SPECS = {
    "java": [r'"(?:\\.|[^"\\])*"', r"'(?:\\.|[^'\\])*'", r"//[^\n]*", r"/\*.*?\*/"],
    "c": [r'"(?:\\.|[^"\\])*"', r"'(?:\\.|[^'\\])*'", r"//[^\n]*", r"/\*.*?\*/"],
    "proc": [r'"(?:\\.|[^"\\])*"', r"'(?:\\.|[^'\\])*'", r"//[^\n]*", r"/\*.*?\*/"],
    "sql": [r"'(?:''|[^'])*'", r"--[^\n]*", r"/\*.*?\*/"],
    "shell": [r'"(?:\\.|[^"\\])*"', r"'[^']*'", r"#[^\n]*"],
}
_MASK_RE = {
    lang: re.compile("|".join(pats), re.DOTALL) for lang, pats in _MASK_SPECS.items()
}

# Java getter/setter は字句のみ（tree-sitter 型解決をしない＝spec §8.3）。
_JAVA_GETSET_RE = re.compile(r"\b((?:get|set)[A-Z]\w*)\s*\(")
# Java 定数: 修飾子群に static と final の双方を含むこと（spec §9「static final 定数」）。
# 型部は generic <...> と配列 [] を許容。
_JAVA_CONST_RE = re.compile(
    r"\b((?:public|protected|private|static|final)(?:\s+(?:public|protected|private|static|final))*)"
    r"\s+[\w.$]+(?:\s*<[^=;{}]*?>)?(?:\s*\[\s*\])*\s+([A-Za-z_]\w*)\s*="
)
_JAVA_VAR_RE = re.compile(r"(?<![=!<>+\-*/%&|^])\b([A-Za-z_]\w*)\s*=(?!=)")
_C_DEFINE_RE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)")
_C_CONST_RE = re.compile(r"\bconst\b[\w\s*]*?\b([A-Za-z_]\w*)\s*=")
_C_VAR_RE = re.compile(r"(?<![=!<>+\-*/%&|^])\b([A-Za-z_]\w*)\s*=(?!=)")
_PROC_HOSTVAR_RE = re.compile(r":\s*([A-Za-z_]\w*)")
_BOURNE_READONLY_RE = re.compile(r"^\s*readonly\s+([A-Za-z_]\w*)=")


def mask_literals(language: str, line: str) -> str:
    """文字列リテラル・コメントを同幅の空白へ置換する（行長・桁・行番号を保存）。

    偽陽性ノイズ抑止（spec §8）。マッチ全体を同じ文字数のスペースに潰すので
    後段の正規表現抽出・automaton 識別子境界判定に影響しない。
    """
    re_ = _MASK_RE.get(language)
    if re_ is None:
        return line
    return re_.sub(lambda m: " " * len(m.group(0)), line)


@dataclass(frozen=True)
class ChaseSymbols:
    """1行から抽出した追跡候補シンボル（spec §8.1/§9 ref_kind×言語）。

    constants/vars は不動点追跡集合の候補。getters/setters は §8.3 により
    横展開しない報告専用候補（fixedpoint が terminal として扱い全件 low 報告）。
    """

    constants: tuple[str, ...] = ()
    vars: tuple[str, ...] = ()
    getters: tuple[str, ...] = ()
    setters: tuple[str, ...] = ()


def extract_chase_symbols(language: str, dialect: str, line: str) -> ChaseSymbols:
    """1行をマスク後に spec §9 ref_kind×言語表で分類抽出する。決定的（出現順）。

    var は extract_var_symbols 再利用（DRY）。getter/setter は Java の字句のみ。
    """
    m = mask_literals(language, line)
    if language == "java":
        consts = tuple(g.group(2) for g in _JAVA_CONST_RE.finditer(m)
                       if "static" in g.group(1).split() and "final" in g.group(1).split())
        getters = tuple(x.group(1) for x in _JAVA_GETSET_RE.finditer(m) if x.group(1)[0] == "g")
        setters = tuple(x.group(1) for x in _JAVA_GETSET_RE.finditer(m) if x.group(1)[0] == "s")
        const_set = set(consts)
        vars_ = tuple(v for v in (x.group(1) for x in _JAVA_VAR_RE.finditer(m))
                      if v not in const_set)
        return ChaseSymbols(consts, vars_, getters, setters)
    if language in ("c", "proc"):
        consts = tuple(x.group(1) for x in _C_DEFINE_RE.finditer(m)) + tuple(
            x.group(1) for x in _C_CONST_RE.finditer(m))
        const_set = set(consts)
        vars_ = tuple(v for v in (x.group(1) for x in _C_VAR_RE.finditer(m))
                      if v not in const_set and v != "const")
        if language == "proc":  # spec §8.1 手順5: ホスト変数は : を剥がした原識別子
            vars_ = vars_ + tuple(x.group(1) for x in _PROC_HOSTVAR_RE.finditer(m))
        return ChaseSymbols(consts, vars_, (), ())
    if language == "shell" and dialect != "cshell":
        rm = _BOURNE_READONLY_RE.match(m)
        if rm is not None:
            return ChaseSymbols((rm.group(1),), (), (), ())
    # sql / cshell / その他: var のみ（extract_var_symbols をマスク済み行に適用）
    return ChaseSymbols((), tuple(extract_var_symbols(language, dialect, m)), (), ())
```

> **実装注:** `extract_var_symbols` をマスク済み `m` に適用するため、SQL/Shell の文字列内 `:=`/`=` もノイズ化しない（Phase 1.5 の `extract_var_symbols` 自体は不変＝既存 test_chase.py 7本は素の行で呼び続けるので不変）。`_JAVA_VAR_RE`/`_C_VAR_RE` の先読みに `+-*/%&|^` を追加し複合代入 `a += 1` の `a` を二重に拾わない（`+=` の `+` で除外）。

- [ ] **Step 4: テストが通ることを確認（当該＋全体回帰ゼロ）**

Run: `python -m pytest tests/unit/test_chase.py -q`
Expected: PASS（既存7＋新規7）

Run: `python -m pytest -q`
Expected: 全 PASS・0 failed / 0 error（既存78に回帰ゼロ）。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/chase.py tests/unit/test_chase.py
git commit -m "feat(chase): 文字列マスク付き分類抽出 extract_chase_symbols（spec §8/§9）"
```

---

## Task 2: 静的シンボル採否 `stoplist.admit`（cap なし）

**Files:**
- Create: `src/grep_analyzer/stoplist.py`
- Test: `tests/unit/test_stoplist.py`

spec §8.3 静的ストップリスト（① 言語キーワード/予約語 ② 最小長 `--min-specificity` ③ ユーザ `--stoplist`）。**集合サイズ上限の切り捨ては「追跡シンボル集合全体（大域・累積）」に対するもの**（spec §8.3）で、行/呼び出し単位ではない。本タスクの `admit` は per-symbol の静的篩のみ。大域 cap は Task 8 fixedpoint が `(発見ホップ数, 識別子長, 文字列辞書順)` で実装。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_stoplist.py` を新規作成:
```python
"""静的シンボル採否ポリシーの仕様（spec §8.3・cap は大域で fixedpoint 側）。"""

from grep_analyzer.stoplist import SymbolPolicy, admit, load_stoplist


def _pol(min_spec=2, stop=frozenset()):
    return SymbolPolicy(min_specificity=min_spec, user_stoplist=stop)


def test_言語キーワードは採用しない():
    r = admit(["if", "STATUS_OK", "class"], "java", _pol())
    assert r.accepted == ["STATUS_OK"]
    assert ("if", "keyword") in r.rejected and ("class", "keyword") in r.rejected


def test_最小長未満は採用しない():
    r = admit(["x", "ab", "abc"], "c", _pol(min_spec=3))
    assert r.accepted == ["abc"]
    assert ("x", "too_short") in r.rejected and ("ab", "too_short") in r.rejected


def test_ユーザストップリストは採用しない():
    r = admit(["FOO", "BAR"], "c", _pol(stop=frozenset({"BAR"})))
    assert r.accepted == ["FOO"]
    assert ("BAR", "user_stoplist") in r.rejected


def test_順序保存で採否しcapはここで行わない():
    r = admit(["zzz", "ab", "yy"], "c", _pol(min_spec=1))
    assert r.accepted == ["zzz", "ab", "yy"]  # cap は admit の責務でない


def test_ストップリストファイルは空行とコメントを無視する(tmp_path):
    f = tmp_path / "stop.txt"
    f.write_text("# c\nFOO\n\n  BAR  \n", "utf-8")
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

v1 は静的ソースのみ（言語キーワード／最小長／ユーザ提供）。動的トップN は
spec §14 スコープ外。集合サイズ上限の決定的切り捨ては大域・累積で行うため
fixedpoint 側に置く（spec §8.3「(発見ホップ数, 識別子長, 文字列辞書順)」）。
"""

from dataclasses import dataclass
from pathlib import Path

_JAVA_KW = frozenset(
    "abstract assert boolean break byte case catch char class const continue default do double "
    "else enum extends final finally float for goto if implements import instanceof int interface "
    "long native new package private protected public return short static strictfp super switch "
    "synchronized this throw throws transient try void volatile while true false null var".split())
_C_KW = frozenset(
    "auto break case char const continue default do double else enum extern float for goto if int "
    "long register return short signed sizeof static struct switch typedef union unsigned void "
    "volatile while inline restrict _Bool".split())
_SQL_KW = frozenset(
    "select insert update delete from where and or not null is in like between exists into values "
    "set begin end declare if then else elsif loop for while case when decode dual table view "
    "procedure function trigger as order by group having distinct union all".split())
_SHELL_KW = frozenset(
    "if then else elif fi for while until do done case esac in function select time set setenv "
    "unset export readonly local return break continue switch breaksw end foreach endif endsw "
    "echo test true false".split())
LANG_KEYWORDS: dict[str, frozenset[str]] = {
    "java": _JAVA_KW, "c": _C_KW, "proc": _C_KW, "sql": _SQL_KW, "shell": _SHELL_KW,
}


@dataclass(frozen=True)
class SymbolPolicy:
    """採否の静的パラメータ（spec §8.3）。cap は持たない（大域 cap は fixedpoint）。"""

    min_specificity: int
    user_stoplist: frozenset[str]


@dataclass(frozen=True)
class AdmissionResult:
    """採否の決定的結果。rejected は (シンボル, 理由) の順序保存列。"""

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


def admit(symbols: list[str], language: str, policy: SymbolPolicy) -> AdmissionResult:
    """シンボル列を静的ポリシーで決定的に採否する（spec §8.3・cap 非適用）。"""
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
    return AdmissionResult(accepted, rejected)
```

- [ ] **Step 4: テストが通ることを確認（当該＋全体回帰ゼロ）**

Run: `python -m pytest tests/unit/test_stoplist.py -q` → PASS（5本）
Run: `python -m pytest -q` → 全 PASS・0 failed / 0 error。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/stoplist.py tests/unit/test_stoplist.py
git commit -m "feat(stoplist): 静的シンボル採否（spec §8.3・大域capは分離）"
```

---

## Task 3: getter/setter 非投入の分割 `stoplist.partition`

**Files:**
- Modify: `src/grep_analyzer/stoplist.py`
- Test: `tests/unit/test_stoplist.py`

spec §8.3 PRD生命線: getter/setter は **chase 集合（横展開対象）へ投入しない**。多ホップは constant/var 経由のみ。getter/setter は terminal（後段 fixedpoint が全反復走査し全件 low 報告するが横展開はしない）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_stoplist.py` の末尾に追記:
```python
from grep_analyzer.chase import ChaseSymbols
from grep_analyzer.stoplist import partition


def test_getterとsetterは横展開せずterminalへ回す():
    cs = ChaseSymbols(constants=("STATUS_OK",), vars=("count",), getters=("getName",), setters=("setX",))
    p = partition(cs, "java", _pol(min_spec=2))
    assert p.chase == ["STATUS_OK", "count"]
    assert p.terminal == ["getName", "setX"]
    assert p.rejected == []


def test_terminalにもキーワード最小長は効く():
    cs = ChaseSymbols(getters=("getX",), setters=("set",))
    p = partition(cs, "java", _pol(min_spec=4))
    assert p.terminal == ["getX"]
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

    chase=横展開対象（constant/var 採用分）、terminal=報告専用（getter/setter
    採用分・横展開しない）、rejected=静的ポリシー棄却（双方）。cap は非適用。
    """

    chase: list[str]
    terminal: list[str]
    rejected: list[tuple[str, str]]


def partition(cs: ChaseSymbols, language: str, policy: SymbolPolicy) -> Partition:
    """ChaseSymbols を「横展開する chase／報告専用 terminal／棄却」に決定的分割。

    spec §8.3 生命線: getter/setter は chase に入れない。keyword/too_short/
    user_stoplist は双方に適用（cap は大域＝fixedpoint・ここでは行わない）。
    """
    chase_r = admit(list(cs.constants) + list(cs.vars), language, policy)
    term_r = admit(list(cs.getters) + list(cs.setters), language, policy)
    return Partition(chase_r.accepted, term_r.accepted, chase_r.rejected + term_r.rejected)
```

- [ ] **Step 4: テストが通ることを確認（当該＋全体回帰ゼロ）**

Run: `python -m pytest tests/unit/test_stoplist.py -q` → PASS（7本）
Run: `python -m pytest -q` → 全 PASS・0 failed / 0 error。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/stoplist.py tests/unit/test_stoplist.py
git commit -m "feat(stoplist): getter/setter 非投入の決定的分割 partition（spec §8.3 生命線）"
```

---

## Task 4: Aho-Corasick ラッパ `automaton.py`（識別子境界）

**Files:**
- Create: `src/grep_analyzer/automaton.py`
- Test: `tests/unit/test_automaton.py`

spec §8.2。`A.iter(s)` は部分文字列も拾う（`CODE`⊂`DECODE`）。前後が `[A-Za-z0-9_]` でないことを確認し語境界一致のみ採用。空・空文字シンボルは防御。決定的（昇順ユニーク）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_automaton.py` を新規作成:
```python
"""Aho-Corasick ラッパの仕様（spec §8.2・識別子境界一致）。"""

from grep_analyzer.automaton import build, scan_line


def test_語境界一致のみ採用し部分文字列は拾わない():
    au = build(["CODE", "v_code"])
    assert scan_line(au, "int CODE; x = DECODE(v_code);") == ["CODE", "v_code"]
    assert scan_line(au, "DECODES = ENCODED;") == []


def test_同一行の複数一致は昇順ユニークで返す():
    au = build(["A", "BB"])
    assert scan_line(au, "BB and A and A and BB") == ["A", "BB"]


def test_空集合と空文字シンボルはNoneあるいは除去される():
    assert build([]) is None
    assert build(["", ""]) is None
    assert scan_line(None, "anything") == []
    assert scan_line(build(["", "CODE"]), "CODE") == ["CODE"]


def test_先頭末尾と記号隣接の境界を識別子境界として扱う():
    au = build(["CODE"])
    assert scan_line(au, "CODE") == ["CODE"]
    assert scan_line(au, "$CODE)") == ["CODE"]
    assert scan_line(au, "xCODE") == [] and scan_line(au, "CODEx") == []
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_automaton.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'grep_analyzer.automaton'`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/automaton.py` を新規作成:
```python
"""pyahocorasick ラッパ（spec §8.2）。識別子語境界一致のみ採用し決定的に返す。"""

import ahocorasick

_IDENT = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def build(symbols: list[str]) -> ahocorasick.Automaton | None:
    """非空シンボル集合から Automaton を構築する。空集合/全空文字は None。"""
    syms = [s for s in symbols if s]
    if not syms:
        return None
    au = ahocorasick.Automaton()
    for s in syms:
        au.add_word(s, s)
    au.make_automaton()
    return au


def scan_line(au: ahocorasick.Automaton | None, line: str) -> list[str]:
    """1 行から語境界一致したシンボルを昇順ユニークで返す（決定的）。

    `A.iter` は (end_index, value)。start=end-len+1。前後が識別子文字なら
    部分一致＝不採用（CODE vs DECODE）。
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

Run: `python -m pytest tests/unit/test_automaton.py -q` → PASS（4本）
Run: `python -m pytest -q` → 全 PASS・0 failed / 0 error。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/automaton.py tests/unit/test_automaton.py
git commit -m "feat(automaton): pyahocorasick ラッパ＋識別子境界（spec §8.2）"
```

---

## Task 5: 決定的ツリー走査 `walk.py`

**Files:**
- Create: `src/grep_analyzer/walk.py`
- Test: `tests/unit/test_walk.py`

spec §8.2: サイズ上限＋バイナリ skip、include/exclude glob（生成コード既定除外・除外を diagnostics 記録）、symlink 既定で辿らない、realpath で同一実体二重走査排除（代表＝正規化相対パス辞書順）、ループ検出。**走査順は relpath 昇順で決定的**。`DEFAULT_EXCLUDE` は **v1 言語スコープ（spec §2.3：Java/C/Pro\*C/SQL/Shell）に整合**する保守的既定（spec §8.2 は具体パターン非列挙＝実装委任）。glob は `/` 区切りセグメント単位の自前マッチャ（`fnmatch` の `**` 二重解釈を排除）。

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


def test_生成コードは既定除外しトップでも深くても効き診断に記録(tmp_path):
    for rel in ("target/Gen.java", "a/b/build/X.c", "src/Keep.java"):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", "utf-8")
    rels, diag = _walk(tmp_path)
    assert rels == ["src/Keep.java"]
    assert "walk_excluded" in diag.render()


def test_バイナリと巨大ファイルはskipし診断に記録する(tmp_path):
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01CODE")
    (tmp_path / "big.c").write_text("a" * 50, "utf-8")
    (tmp_path / "ok.c").write_text("CODE", "utf-8")
    diag = Diagnostics()
    rels = [r for r, _ in walk_files(
        tmp_path, include=[], exclude=list(DEFAULT_EXCLUDE),
        follow_symlinks=False, max_file_bytes=10, diag=diag)]
    assert rels == ["ok.c"]
    d = diag.render()
    assert "walk_skipped_binary" in d and "walk_skipped_large" in d


def test_includeグロブ指定時は一致するもののみ(tmp_path):
    (tmp_path / "a.java").write_text("x", "utf-8")
    (tmp_path / "b.txt").write_text("y", "utf-8")
    rels, _ = _walk(tmp_path, include=["*.java"])
    assert rels == ["a.java"]


def test_symlinkは既定で辿らず実体重複は辞書順代表のみ(tmp_path):
    (tmp_path / "real.c").write_text("CODE", "utf-8")
    os.symlink(tmp_path / "real.c", tmp_path / "link.c")
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

生成コード既定除外・symlink は既定で辿らず realpath 重複排除。走査順非依存で
決定的（spec §9 決定性の前提）。
"""

import fnmatch
import os
from collections.abc import Iterator
from pathlib import Path

from grep_analyzer.diagnostics import Diagnostics

# v1 言語スコープ（spec §2.3: Java/C/Pro*C/SQL/Shell）に整合する保守的既定。
# Python/JS の生成物（*_pb2.py / node_modules / *.min.js）は v1 言語外なので含めない。
# spec §8.2 は具体パターンを列挙しないため本既定を採用し --exclude で上書き可。
DEFAULT_EXCLUDE: tuple[str, ...] = (
    "**/target/**", "**/build/**", "**/generated/**", "**/.git/**",
)


def _match_one(rel: str, pat: str) -> bool:
    """rel（/区切り）が 1 パターンに一致するか。`**` は任意段、`*` は1段内。"""
    rseg = rel.split("/")
    pseg = pat.split("/")

    def m(ri: int, pi: int) -> bool:
        if pi == len(pseg):
            return ri == len(rseg)
        if pseg[pi] == "**":
            # ** は 0 段以上の任意ディレクトリ
            return any(m(k, pi + 1) for k in range(ri, len(rseg) + 1))
        if ri == len(rseg):
            return False
        if fnmatch.fnmatch(rseg[ri], pseg[pi]):
            return m(ri + 1, pi + 1)
        return False

    return m(0, 0)


def _match_any(rel: str, patterns: list[str]) -> bool:
    """rel がいずれかのパターンに一致するか（基本名一致も許容）。"""
    base = rel.rsplit("/", 1)[-1]
    for p in patterns:
        if _match_one(rel, p) or ("/" not in p and fnmatch.fnmatch(base, p)):
            return True
    return False


def _is_binary(path: Path) -> bool:
    """先頭 8KB に NUL バイトを含めばバイナリ（決定的）。"""
    with open(path, "rb") as f:
        return b"\x00" in f.read(8192)


def walk_files(
    root: Path, *, include: list[str], exclude: list[str],
    follow_symlinks: bool, max_file_bytes: int, diag: Diagnostics,
) -> Iterator[tuple[str, Path]]:
    """root 配下の通常ファイルを relpath 昇順で yield する（spec §8.2）。

    除外/スキップ/symlink 重複は diag に記録（spec §8.4 正本へ集約）。
    """
    root = Path(root)
    seen_real: dict[str, str] = {}
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
        seen_real[real] = rel  # 昇順走査＝最初が辞書順最小代表
        yield rel, abspath
```

- [ ] **Step 4: テストが通ることを確認（当該＋全体回帰ゼロ）**

Run: `python -m pytest tests/unit/test_walk.py -q` → PASS（5本）
Run: `python -m pytest -q` → 全 PASS・0 failed / 0 error。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/walk.py tests/unit/test_walk.py
git commit -m "feat(walk): 決定的走査＋生成コード除外＋symlink重複排除（spec §8.2）"
```

---

## Task 6: 来歴グラフと chain 正規形 `provenance.py`

**Files:**
- Create: `src/grep_analyzer/provenance.py`
- Test: `tests/unit/test_provenance.py`

spec §9 chain 正規形・**単純パス**（同一エッジ・**同一追跡シンボル**を二度通らない）。循環は最初の再訪エッジで打ち切り `prov_cycle_cut` 記録。`max_depth`（ホップ数＝` -> ` 本数）超過パスは `prov_max_depth` 記録し打ち切り。経路数が `max_paths` 超過時は決定的に辞書順先頭 `max_paths` 経路を採り `prov_path_capped` 記録（経路爆発の安全弁。spec §9「有限かつ決定的」を保証。実規模 degrade は Phase 2b）。同一ヒットへ異なる単純パスで到達したら経路ごとに別 chain（重複許容＝spec §9 仕様）。

> **モデル（spec §8.2/§9 準拠・冒頭「spec 解釈の明示」と一致）:** ノード＝`Occurrence(symbol,relpath,lineno)`。`add_seed` した Occurrence の `(relpath,lineno)` は seed 物理行集合に登録（`is_seed_location` で間接再出力から除外＝spec §9 direct 既出）。`add_edge(parent,child)` は「parent 出現行から child.symbol が抽出され child が出現した」。`chains_to` は seed から target への単純パスを DFS。**循環打ち切りは「起点（seed）以降の追跡識別子の二度目の出現」**（spec §9「同一シンボルを二度通らない」を多ホップ chase 循環として適用。keyword と最初の追跡識別子の同名は許容＝PRD 主目的）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_provenance.py` を新規作成:
```python
"""来歴グラフと chain 正規形の仕様（spec §9）。"""

from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.provenance import Occurrence, ProvenanceGraph


def _g(seed, edges):
    g = ProvenanceGraph()
    g.add_seed(seed)
    for p, c in edges:
        g.add_edge(p, c)
    return g


def test_単一経路のchainは起点から連結される():
    s, m = Occurrence("KEY", "a.c", 1), Occurrence("CODE", "b.c", 5)
    g = _g(s, [(s, m)])
    assert g.chains_to(m, max_depth=10, max_paths=100, diag=Diagnostics()) == [
        "KEY@a.c:1 -> CODE@b.c:5"]


def test_同名keywordと追跡識別子は単純パスとして許容する():
    # PRD 主目的: keyword CODE の利用箇所列挙。CODE@def -> CODE@use は許容。
    s, u = Occurrence("CODE", "r.sh", 1), Occurrence("CODE", "r.sh", 2)
    g = _g(s, [(s, u)])
    assert g.chains_to(u, max_depth=10, max_paths=100, diag=Diagnostics()) == [
        "CODE@r.sh:1 -> CODE@r.sh:2"]


def test_複数単純パスは経路ごとに別chainを決定的順で返す():
    s = Occurrence("KEY", "a.c", 1)
    p, q = Occurrence("P", "p.c", 2), Occurrence("Q", "q.c", 3)
    h = Occurrence("H", "h.c", 9)
    g = _g(s, [(s, p), (s, q), (p, h), (q, h)])
    assert g.chains_to(h, max_depth=10, max_paths=100, diag=Diagnostics()) == [
        "KEY@a.c:1 -> P@p.c:2 -> H@h.c:9",
        "KEY@a.c:1 -> Q@q.c:3 -> H@h.c:9",
    ]


def test_追跡識別子の循環は再訪エッジで打ち切り診断記録する():
    s = Occurrence("KEY", "a.c", 1)
    x, y = Occurrence("X", "x.c", 2), Occurrence("Y", "y.c", 3)
    x2 = Occurrence("X", "x.c", 9)  # X 再訪（別 Occurrence・同一追跡シンボル）
    h = Occurrence("H", "h.c", 4)
    g = _g(s, [(s, x), (x, y), (y, x2), (y, h)])
    diag = Diagnostics()
    chains = g.chains_to(h, max_depth=10, max_paths=100, diag=diag)
    assert chains == ["KEY@a.c:1 -> X@x.c:2 -> Y@y.c:3 -> H@h.c:4"]
    assert "prov_cycle_cut" in diag.render()


def test_max_depthはホップ数で単一定義され0は間接ゼロ():
    s = Occurrence("KEY", "a.c", 1)
    a, b = Occurrence("A", "a.c", 2), Occurrence("B", "b.c", 3)
    g = _g(s, [(s, a), (a, b)])
    d1 = Diagnostics()
    assert g.chains_to(b, max_depth=1, max_paths=100, diag=d1) == []
    assert "prov_max_depth" in d1.render()
    assert g.chains_to(b, max_depth=2, max_paths=100, diag=Diagnostics()) == [
        "KEY@a.c:1 -> A@a.c:2 -> B@b.c:3"]
    assert g.chains_to(a, max_depth=0, max_paths=100, diag=Diagnostics()) == []


def test_経路数上限超過は決定的に辞書順先頭を採り診断記録する():
    s = Occurrence("KEY", "a.c", 1)
    h = Occurrence("H", "h.c", 9)
    mids = [Occurrence(f"M{i}", f"m{i}.c", i) for i in range(5)]
    g = ProvenanceGraph()
    g.add_seed(s)
    for mid in mids:
        g.add_edge(s, mid)
        g.add_edge(mid, h)
    diag = Diagnostics()
    chains = g.chains_to(h, max_depth=10, max_paths=2, diag=diag)
    assert chains == [
        "KEY@a.c:1 -> M0@m0.c:0 -> H@h.c:9",
        "KEY@a.c:1 -> M1@m1.c:1 -> H@h.c:9",
    ]
    assert "prov_path_capped" in diag.render()


def test_seed物理行は間接から除外判定できる():
    g = ProvenanceGraph()
    g.add_seed(Occurrence("X", "o.sql", 2))
    assert g.is_seed_location("o.sql", 2) is True
    assert g.is_seed_location("o.sql", 1) is False
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
    """ヒット出現＝来歴グラフのノード。order=True で決定的ソート可能。"""

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
        self._seed_loc: set[tuple[str, int]] = set()
        self._adj: dict[Occurrence, list[Occurrence]] = {}

    def add_seed(self, occ: Occurrence) -> None:
        """起点（direct ヒット相当）を登録する。物理行も seed として記録。"""
        self._seeds.add(occ)
        self._seed_loc.add((occ.relpath, occ.lineno))

    def is_seed_location(self, relpath: str, lineno: int) -> bool:
        """(relpath,lineno) が direct seed 物理行か（間接再出力の除外判定）。"""
        return (relpath, lineno) in self._seed_loc

    def add_edge(self, parent: Occurrence, child: Occurrence) -> None:
        """発見元 parent → 発見 child のエッジを追加（決定的順序を維持）。"""
        lst = self._adj.setdefault(parent, [])
        if child not in lst:
            lst.append(child)
            lst.sort()

    def chains_to(
        self, target: Occurrence, *, max_depth: int, max_paths: int, diag: Diagnostics
    ) -> list[str]:
        """各 seed から target への単純パスを chain 文字列の決定的リストで返す。

        単純パス＝同一 Occurrence を二度通らず、起点以降の追跡識別子（symbol）が
        二度現れない（spec §9 循環打ち切り）。max_depth はホップ数（` -> ` 本数）。
        循環/深さ/経路数の打ち切りは prov_cycle_cut/prov_max_depth/prov_path_capped。
        """
        results: list[str] = []
        for seed in sorted(self._seeds):
            # 起点 symbol は「文言」の役割。多ホップ循環判定の対象は起点より後の識別子。
            self._dfs(seed, target, [seed], {seed}, set(), max_depth, diag, results)
        results = sorted(set(results))
        if len(results) > max_paths:
            diag.add("prov_path_capped", f"{_hop(target)}\t{len(results)}>{max_paths}")
            results = results[:max_paths]
        return results

    def _dfs(self, node, target, path, visited_occ, visited_sym,
             max_depth, diag, results) -> None:
        if node == target:
            results.append(" -> ".join(_hop(o) for o in path))
            return
        if len(path) - 1 >= max_depth:
            diag.add("prov_max_depth", _hop(path[0]) + " ... " + _hop(node))
            return
        for nxt in self._adj.get(node, []):
            if nxt in visited_occ:
                diag.add("prov_cycle_cut", _hop(node) + " -> " + _hop(nxt))
                continue
            # 起点(path[0])以降に同一追跡シンボルが再出現する経路は循環として打ち切る
            if len(path) >= 1 and nxt.symbol in visited_sym:
                diag.add("prov_cycle_cut", _hop(node) + " -> " + _hop(nxt))
                continue
            self._dfs(nxt, target, path + [nxt], visited_occ | {nxt},
                      visited_sym | {nxt.symbol}, max_depth, diag, results)
```

> **境界整合（Self-Review 3 で串刺し）:** `max_depth=1` のとき `KEY→A→B`（B はホップ2）は `len(path)-1>=1` を A の位置（path=[KEY,A]・len-1=1）で満たし B へ進む前に `prov_max_depth` 記録・打ち切り → `chains_to(b,max_depth=1)==[]`。`max_depth=2` は `KEY→A→B`（2 ホップ）を採用。`max_depth=0` は seed の直後で `len([KEY])-1=0>=0` 真 → 即打ち切り＝間接ゼロ（direct のみ）。循環テストは target=H が循環エッジの先にあり、`Y→X(再訪)` を踏むため `prov_cycle_cut` が必ず発火（v1 の「target が循環手前で return し循環エッジを踏まない」バグを解消）。`visited_sym` に起点 symbol を入れないので `CODE@def -> CODE@use` は許容。

- [ ] **Step 4: テストが通ることを確認（当該＋全体回帰ゼロ）**

Run: `python -m pytest tests/unit/test_provenance.py -q` → PASS（7本）
Run: `python -m pytest -q` → 全 PASS・0 failed / 0 error。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/provenance.py tests/unit/test_provenance.py
git commit -m "feat(provenance): シンボル来歴グラフ＋単純パスchain（spec §9・決定的有限化）"
```

---

## Task 7: 共有行分類 `classify.py`

**Files:**
- Create: `src/grep_analyzer/classify.py`
- Test: `tests/unit/test_classify.py`

`pipeline._classify` と同じ分類を fixedpoint からも使う。`pipeline→fixedpoint→classify`／`pipeline→classify` で循環しない（`classify` は `classifiers/*` のみ依存）。本タスクは新規モジュール＋unit のみ（pipeline は Task 9 で委譲）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_classify.py` を新規作成:
```python
"""共有行分類の仕様（pipeline と fixedpoint が共通利用）。"""

from grep_analyzer.classify import classify_hit


def test_ts言語はtree_sitterでhigh分類():
    assert classify_hit("java", "", "class A{ int x;\n if(x==1){} }", 2, "if(x==1){}") == (
        "比較", "high")


def test_sqlとshellはmedium分類で未知はbourneフォールバック():
    assert classify_hit("sql", "", "", 1, "v := 1;") == ("代入", "medium")
    assert classify_hit("shell", "cshell", "", 1, "set X = 1") == ("代入", "medium")
    assert classify_hit("unknown", "", "", 1, "X=1") == ("代入", "medium")
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_classify.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'grep_analyzer.classify'`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/classify.py` を新規作成（`pipeline._classify` と挙動・引数順を同一に）:
```python
"""言語別行分類の共有実装（spec §7）。pipeline と fixedpoint が共通利用する。"""

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

Run: `python -m pytest tests/unit/test_classify.py -q` → PASS（2本）
Run: `python -m pytest -q` → 全 PASS・0 failed / 0 error（pipeline 未変更）。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/classify.py tests/unit/test_classify.py
git commit -m "feat(classify): pipeline/fixedpoint 共有の行分類（循環import回避）"
```

---

## Task 8: 不動点エンジン `fixedpoint.py`（多ホップ・一度だけ実装）

**Files:**
- Create: `src/grep_analyzer/fixedpoint.py`
- Test: `tests/unit/test_fixedpoint.py`

spec §8.1 反復＋§8.3 採否＋§8.2 来歴集約を **一度だけ**実装する（v1 の単一ホップ→全置換の二重実装は廃止）。TDD は単一ホップ（`max_depth=1`）→多ホップ→停止性→getter 全件報告→jobs 決定性→大域 cap の順でテストを積む（実装は最初から多ホップ汎用）。設計確定事項:

- seed 方言は **seed ファイルを読み `detect_shell_dialect`**（spec §5.1 決定的。`Hit` に方言が無いため。snippet ヒューリスティック禁止）。言語も同様に `detect_language(rel, text[:4096], lang_map)`。
- seed 行から chase/terminal 抽出 → hop1。各シンボルに `sym_hop`（初出ホップ・単調）を記録。
- chase は不動点反復で全ツリー走査。**terminal（getter/setter）も全反復走査し全件 low 報告するが横展開（`_ingest`）しない**（spec §8.4 全件）。
- 大域 cap: 反復ごとに採用集合（chase∪terminal）サイズが `max_symbols` 超過なら `(発見ホップ, 長さ, 辞書順)` で決定的に上限内採用、超過分は `symbol_rejected\tcapped` 記録（spec §8.3）。
- 走査は `_scan_file` 純関数（**1 デコードで text/言語/方言/ヒットを返す**＝三重デコード廃止）。`jobs>1` は `multiprocessing.Pool`。集約は `rel` 昇順で決定的（spec §8.2 ワーカ横断集約・§9 走査順非依存）。
- ヒット確定は全エッジ集約後の単一フェーズ。seed 物理行 `is_seed_location` は間接から除外。chain は `provenance.chains_to`（`max_depth`/`max_paths` 単一定義）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_fixedpoint.py` を新規作成:
```python
"""不動点エンジンの仕様（spec §8.1/§8.2/§8.3）。外部I/O境界＝実FS本物。"""

from pathlib import Path

from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.fixedpoint import EngineOptions, run_fixedpoint
from grep_analyzer.model import Hit


def _opts(**kw):
    base = dict(max_depth=5, min_specificity=2, stoplist_path=None, lang_map={},
                include=[], exclude=[], jobs=1, follow_symlinks=False,
                max_file_bytes=1_000_000, max_symbols=1000, max_paths=100)
    base.update(kw)
    return EngineOptions(**base)


def _seed(keyword, language, rel, lineno, content):
    return Hit(keyword=keyword, language=language, file=rel, lineno=lineno,
               ref_kind="direct", category="宣言", category_sub="",
               usage_summary=f"宣言 ({language})", via_symbol="",
               chain=f"{keyword}@{rel}:{lineno}", snippet=content,
               encoding="utf-8", confidence="high")


def _mk(tmp_path, files):
    src = tmp_path / "src"
    src.mkdir()
    for rel, body in files.items():
        f = src / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, "utf-8")
    return src


def test_seed定数の他ファイル出現をindirect_constantで報告し単一ホップ(tmp_path):
    src = _mk(tmp_path, {
        "C.java": 'class C { static final String STATUS_OK = "S"; }\n',
        "U.java": "class U { String x = STATUS_OK; }\n"})
    seed = _seed("STATUS_OK", "java", "C.java", 1,
                 'static final String STATUS_OK = "S";')
    hits = run_fixedpoint([seed], src, _opts(max_depth=1), Diagnostics())
    u = [h for h in hits if h.file == "U.java"]
    assert u and u[0].ref_kind == "indirect:constant" and u[0].via_symbol == "STATUS_OK"
    assert u[0].chain == "STATUS_OK@C.java:1 -> STATUS_OK@U.java:1"
    assert all(h.file != "C.java" for h in hits)  # seed 物理行は間接再出力しない


def test_多ホップ定数連鎖を不動点まで追う(tmp_path):
    src = _mk(tmp_path, {
        "A.java": "class A{ static final int K1 = 1; }\n",
        "B.java": "class B{ static final int K2 = K1; }\n",
        "C.java": "class C{ int z = K2; }\n"})
    seed = _seed("K1", "java", "A.java", 1, "static final int K1 = 1;")
    hits = run_fixedpoint([seed], src, _opts(), Diagnostics())
    rels = {(h.file, h.via_symbol) for h in hits}
    assert ("B.java", "K1") in rels and ("C.java", "K2") in rels
    c = next(h for h in hits if h.file == "C.java")
    assert c.chain == "K1@A.java:1 -> K1@B.java:1 -> K2@C.java:1"


def test_相互参照でも有限母集合で飽和し停止する(tmp_path):
    src = _mk(tmp_path, {
        "A.java": "class A{ static final int P = Q; }\n",
        "B.java": "class B{ static final int Q = P; }\n"})
    seed = _seed("P", "java", "A.java", 1, "static final int P = Q;")
    hits = run_fixedpoint([seed], src, _opts(max_depth=10), Diagnostics())
    assert hits and all(h.ref_kind.startswith("indirect:") for h in hits)


def test_getterは横展開せず全反復全件lowで報告し抑止を記録(tmp_path):
    src = _mk(tmp_path, {
        # hop1: seed 行から count(var) と getName(getter)
        "S.java": "class S { int count = a.getName(); }\n",
        # hop2: count の出現先。ここから getStatus(getter) を hop2 で発見
        "U.java": "class U { int v = count; String t = b.getStatus(); }\n",
        # getName / getStatus の別出現（全件 low 報告対象）
        "T.java": "class T { String n = c.getName();\n String s = d.getStatus(); }\n"})
    seed = _seed("count", "java", "S.java", 1, "int count = a.getName();")
    diag = Diagnostics()
    hits = run_fixedpoint([seed], src, _opts(), diag)
    g = [h for h in hits if h.via_symbol in ("getName", "getStatus")]
    assert g and all(h.ref_kind in ("indirect:getter",) and h.confidence == "low" for h in g)
    # hop2 で発見した getStatus も T.java で全件報告される（spec §8.4 全件）
    assert any(h.via_symbol == "getStatus" and h.file == "T.java" for h in hits)
    d = diag.render()
    assert "getter_setter_no_expand\tgetName" in d and "getter_setter_no_expand\tgetStatus" in d


def test_jobs1とjobsNでTSV相当キーが完全一致(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ static final int K = 1; }\n",
                         **{f"{n}.java": f"class {n}{{ int v = K; }}\n" for n in "BCDE"}})
    seed = _seed("K", "java", "A.java", 1, "static final int K = 1;")
    key = lambda h: (h.file, h.lineno, h.ref_kind, h.via_symbol, h.chain)
    h1 = run_fixedpoint([seed], src, _opts(jobs=1), Diagnostics())
    hN = run_fixedpoint([seed], src, _opts(jobs=4), Diagnostics())
    assert sorted(map(key, h1)) == sorted(map(key, hN))


def test_大域集合上限超過は決定的に切り捨て診断記録する(tmp_path):
    src = _mk(tmp_path, {
        "A.java": "class A{ int aa=bb; int bb=cc; int cc=dd; int dd=1; }\n",
        "B.java": "class B{ int z = aa; }\n"})
    seed = _seed("aa", "java", "A.java", 1, "int aa=bb;")
    diag = Diagnostics()
    run_fixedpoint([seed], src, _opts(min_specificity=1, max_symbols=2), diag)
    assert "symbol_rejected\tcapped" in diag.render()


def test_max_depth0は間接を出さない(tmp_path):
    src = _mk(tmp_path, {"C.java": 'class C { static final String K = "S"; }\n',
                         "U.java": "class U { String x = K; }\n"})
    seed = _seed("K", "java", "C.java", 1, 'static final String K = "S";')
    assert run_fixedpoint([seed], src, _opts(max_depth=0), Diagnostics()) == []
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_fixedpoint.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'grep_analyzer.fixedpoint'`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/fixedpoint.py` を新規作成:
```python
"""不動点・ターゲットスキャン・エンジン（spec §8.1/§8.2/§8.3）。

Phase 1/1.5 の direct ヒットを seed に constant/var を多ホップ追跡し indirect
ヒットと chain を出す。getter/setter は §8.3 により横展開しないが全反復走査・
全件 confidence=low 報告（spec §8.4）。出力は走査順・並列完了順に非依存で決定的。

停止性（spec §8.1 手順5）: 追跡シンボルは原ソース字句のみ（extract_chase_symbols
がマスク後の字句から抽出）。母集合は有限・採用集合は単調増加（chase_done）。
よって高々 |母集合| ステップで飽和。--max-depth/max_symbols/max_paths は安全弁。
"""

import multiprocessing
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
from grep_analyzer import automaton, walk


@dataclass(frozen=True)
class EngineOptions:
    """spec §8/§10.4 のエンジン挙動パラメータ（Phase 2a 範囲）。"""

    max_depth: int
    min_specificity: int
    stoplist_path: Path | None
    lang_map: dict[str, str]
    include: list[str]
    exclude: list[str]
    jobs: int
    follow_symlinks: bool
    max_file_bytes: int
    max_symbols: int
    max_paths: int


_REF_KIND = {"constant": "indirect:constant", "var": "indirect:var",
             "getter": "indirect:getter", "setter": "indirect:setter"}


def _file_meta(rel: str, raw: bytes, lang_map: dict[str, str]):
    """1 度だけデコードし (text, enc, replaced, language, dialect) を返す。"""
    text, enc, replaced = decode_bytes(raw, DEFAULT_FALLBACK)
    language = detect_language(rel, text[:4096], lang_map)
    dialect = detect_shell_dialect(rel, text[:4096]) if language == "shell" else "bourne"
    return text, enc, replaced, language, dialect


def _scan_file(args):
    """1 ファイルを走査しヒット素片を返す純関数（並列ワーカ・picklable のみ）。"""
    rel, raw, sym_list, lang_map = args
    text, enc, replaced, language, dialect = _file_meta(rel, raw, lang_map)
    au = automaton.build(sym_list)
    found = []  # (sym, lineno, line)
    if au is not None:
        for i, line in enumerate(text.split("\n"), start=1):
            for sym in automaton.scan_line(au, line):
                found.append((sym, i, line))
    return rel, enc, replaced, language, dialect, found


def _kinds_of(language: str, dialect: str, line: str) -> dict[str, str]:
    """1 行の各シンボル→種別。同名は constant>var>getter>setter の決定的優先。"""
    cs = extract_chase_symbols(language, dialect, line)
    out: dict[str, str] = {}
    for kind, names in (("setter", cs.setters), ("getter", cs.getters),
                        ("var", cs.vars), ("constant", cs.constants)):
        for n in names:
            out[n] = kind
    return out


def run_fixedpoint(
    seed_hits: list[Hit], source_root: Path, opts: EngineOptions, diag: Diagnostics
) -> list[Hit]:
    """seed から不動点まで多ホップ追跡し indirect Hit を決定的に返す（spec §8.1）。"""
    source_root = Path(source_root)
    policy = SymbolPolicy(opts.min_specificity, load_stoplist(opts.stoplist_path))
    graph = ProvenanceGraph()
    keyword = sorted({s.keyword for s in seed_hits})[0] if seed_hits else ""

    sym_kind: dict[str, str] = {}
    sym_hop: dict[str, int] = {}            # 初出ホップ（単調・大域 cap キー）
    edges: list[tuple[Occurrence, Occurrence]] = []
    chase_active: set[str] = set()
    chase_done: set[str] = set()
    term_active: set[str] = set()
    term_done: set[str] = set()
    no_expand_logged: set[str] = set()
    replaced_logged: set[str] = set()

    def _ingest(language, dialect, line, parent: Occurrence, hop: int):
        if hop > opts.max_depth:
            return
        cs = extract_chase_symbols(language, dialect, line)
        kinds = _kinds_of(language, dialect, line)
        part = partition(cs, language, policy)
        for sym, reason in sorted(part.rejected):
            diag.add("symbol_rejected", f"{reason}\t{sym}")
        for sym in part.chase:
            sym_kind.setdefault(sym, kinds.get(sym, "var"))
            sym_hop.setdefault(sym, hop)
            if sym not in chase_done:
                chase_active.add(sym)
        for sym in part.terminal:
            sym_kind.setdefault(sym, kinds.get(sym, "getter"))
            sym_hop.setdefault(sym, hop)
            if sym not in term_done:
                term_active.add(sym)

    # hop0→hop1: seed ファイルを実読して spec §5.1 決定的に言語/方言確定（snippet 非依存）
    seed_meta: dict[str, tuple[str, str]] = {}
    for s in seed_hits:
        occ = Occurrence(s.keyword, s.file, s.lineno)
        graph.add_seed(occ)
        sp = source_root / s.file
        if sp.is_file():
            _, _, _, lang, dia = _file_meta(s.file, sp.read_bytes(), opts.lang_map)
        else:
            lang, dia = s.language, "bourne"
        seed_meta[s.file] = (lang, dia)
        _ingest(lang, dia, s.snippet, occ, hop=1)

    files: list[tuple[str, bytes]] = [
        (rel, abspath.read_bytes())
        for rel, abspath in walk.walk_files(
            source_root, include=opts.include, exclude=opts.exclude,
            follow_symlinks=opts.follow_symlinks,
            max_file_bytes=opts.max_file_bytes, diag=diag)]

    def _apply_global_cap():
        """採用集合（chase∪terminal）が上限超過なら決定的に切り捨て（spec §8.3）。"""
        live = sorted(chase_active | chase_done | term_active | term_done,
                      key=lambda s: (sym_hop.get(s, 0), len(s), s))
        if len(live) <= opts.max_symbols:
            return
        for s in live[opts.max_symbols:]:
            diag.add("symbol_rejected", f"capped\t{s}")
            chase_active.discard(s); chase_done.discard(s)
            term_active.discard(s); term_done.discard(s)

    enc_of: dict[str, tuple[str, bool]] = {}
    meta_of: dict[str, tuple[str, str, str]] = {}  # rel -> (text, language, dialect)
    hop = 1
    while chase_active or term_active:
        _apply_global_cap()
        scan_chase = set(chase_active)
        scan_term = set(term_active)
        scan_syms = sorted(scan_chase | scan_term)
        chase_done |= chase_active; chase_active = set()
        term_done |= term_active; term_active = set()
        if not scan_syms or hop > opts.max_depth:
            break
        args = [(rel, raw, scan_syms, opts.lang_map) for rel, raw in files]
        if opts.jobs > 1:
            with multiprocessing.Pool(opts.jobs) as pool:
                results = pool.map(_scan_file, args)
        else:
            results = [_scan_file(a) for a in args]
        for rel, enc, replaced, language, dialect, found in sorted(
                results, key=lambda r: r[0]):
            enc_of.setdefault(rel, (enc, replaced))
            if replaced and rel not in replaced_logged:
                diag.add("decode_replaced", rel)
                replaced_logged.add(rel)
            # text 再構築不要: 確定フェーズ用に行を保持
            for sym, i, line in found:
                if sym not in scan_chase and sym not in scan_term:
                    continue
                child = Occurrence(sym, rel, i)
                meta_of.setdefault(rel, (None, language, dialect))
                # 親（sym を導入した出現）からのエッジ。spec §8.2 シンボル間エッジ。
                for parent in _parents_of(sym, edges, graph, seed_hits, keyword):
                    if parent != child:
                        edges.append((parent, child))
                if sym in scan_term:
                    if sym not in no_expand_logged:
                        diag.add("getter_setter_no_expand", sym)
                        no_expand_logged.add(sym)
                    continue  # 横展開しない（spec §8.3 生命線）
                _ingest(language, dialect, line, child, hop + 1)
        hop += 1

    # ヒット確定: 全エッジ集約後に chain を計算（走査/完了順非依存・spec §9）
    for p, c in edges:
        graph.add_edge(p, c)
    indirect: list[Hit] = []
    seen: set[Occurrence] = set()
    line_cache: dict[str, list[str]] = {}
    for _, c in sorted(set(edges)):
        if c in seen or c.symbol not in (chase_done | term_done):
            continue
        if graph.is_seed_location(c.relpath, c.lineno):
            continue  # direct 既出
        seen.add(c)
        if c.relpath not in line_cache:
            raw = next(r for re_, r in files if re_ == c.relpath) \
                if any(re_ == c.relpath for re_, _ in files) else b""
            text, enc, replaced, lang, dia = _file_meta(c.relpath, raw, opts.lang_map)
            line_cache[c.relpath] = text.split("\n")
            meta_of[c.relpath] = (text, lang, dia)
            enc_of.setdefault(c.relpath, (enc, replaced))
        text, language, dialect = meta_of[c.relpath]
        lines = line_cache[c.relpath]
        line = lines[c.lineno - 1] if 0 <= c.lineno - 1 < len(lines) else ""
        kind = sym_kind.get(c.symbol, "var")
        cat, conf = classify_hit(language, dialect, text, c.lineno, line)
        if kind in ("getter", "setter"):
            conf = "low"  # spec §8.4 型解決不能 getter/setter は全件 low
        enc, replaced = enc_of.get(c.relpath, ("utf-8", False))
        chains = graph.chains_to(c, max_depth=opts.max_depth,
                                 max_paths=opts.max_paths, diag=diag)
        for chain in chains:
            indirect.append(Hit(
                keyword=keyword, language=language, file=c.relpath, lineno=c.lineno,
                ref_kind=_REF_KIND[kind], category=cat, category_sub="",
                usage_summary=f"{cat} ({language})", via_symbol=c.symbol,
                chain=chain, snippet=line,
                encoding=enc + (" 要確認" if replaced else ""), confidence=conf))
    return indirect


def _parents_of(sym, edges, graph, seed_hits, keyword):
    """sym を導入した親 Occurrence 群を決定的に返す。

    seed 行から抽出された sym は seed Occurrence を親に。多ホップで親が増える
    場合も「sym を抽出した出現」が親（既存 edges の child で sym を導入した側は
    _ingest 時点で child=parent として扱われるため、ここでは seed 起点を返す）。
    """
    parents = [Occurrence(s.keyword, s.file, s.lineno)
               for s in seed_hits]  # hop1: seed が親
    # hop>=2: sym を child として持つ既存エッジの child が親になる
    for _, c in edges:
        if c.symbol != sym:
            parents.append(c)
    uniq = sorted(set(parents))
    return uniq
```

> **実装注（次レビュー重点・spec 整合）:** `_parents_of` は spec §8.2「(発見元シンボル,発見シンボル,file,lineno)」のシンボル間エッジを Occurrence で具体化する。hop1 は seed 行が親、hop≥2 は「その sym を child として確定済みの出現」が親。`provenance` 側の単純パス（同一追跡シンボル二度禁止）が定数循環 A→B→A を打ち切るため、`_parents_of` の親集合が広めでも chain は有限・決定的。`seen` は Occurrence 単位重複抑止（異なる単純パスは `chains_to` が経路別 chain＝spec §9 重複許容）。`is_seed_location` で seed 物理行を間接から除外（keyword≠シンボル名でも seed 行を再出力しない＝v1 の oracle/shell golden 破壊バグの根治）。確定フェーズの行取得は `files`（既読 bytes）から 1 回デコードし `line_cache`/`meta_of` でファイル単位キャッシュ＝同一ファイル多ヒットでも再 I/O しない（v1 の三重デコード解消）。

- [ ] **Step 4: テストが通ることを確認（当該＋全体回帰ゼロ）**

Run: `python -m pytest tests/unit/test_fixedpoint.py -q`
Expected: PASS（7本）。`test_相互参照でも有限母集合で飽和し停止する` がタイムアウトせず PASS（停止性実測）。

Run: `python -m pytest -q`
Expected: 全 PASS・0 failed / 0 error。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/fixedpoint.py tests/unit/test_fixedpoint.py
git commit -m "feat(fixedpoint): 多ホップ不動点＋停止性＋getter全件報告＋jobs決定的集約＋大域cap（spec §8.1/§8.2/§8.3）"
```

---

## Task 9: パイプライン配線と CLI（`--lang-map` 対称配線）

**Files:**
- Modify: `src/grep_analyzer/pipeline.py`
- Modify: `src/grep_analyzer/cli.py`
- Test: `tests/integration/test_pipeline_fixedpoint.py`

direct ヒット生成後に `run_fixedpoint` を呼び indirect を併合、`write_tsv`（既存 `model.sort_key`）で安定化。`pipeline._classify`→`classify.classify_hit` 委譲（DRY）。**`lang_map` を direct/indirect 同一オブジェクトで配線**し非対称を構造的に排除（spec §5.1/§10.4）。`--lang-map EXT=LANG,...` を実装（既存 direct 側の空 dict 固定＝Phase 1.5 積み残しを同時に解消）。未指定オプションは安全な既定で Phase 1 挙動を変えない。

- [ ] **Step 1: 失敗するテストを書く**

`tests/integration/test_pipeline_fixedpoint.py` を新規作成:
```python
"""direct→不動点→併合 TSV の境界契約（spec §8/§9/§10.4）。in-process。"""

from pathlib import Path

from grep_analyzer.cli import main


def _setup(tmp_path, src_files, grep, keyword):
    src = tmp_path / "src"; src.mkdir()
    for rel, body in src_files.items():
        (src / rel).write_text(body, "utf-8")
    inp = tmp_path / "input"; inp.mkdir()
    (inp / f"{keyword}.grep").write_text(grep, "utf-8")
    return src, inp


def test_間接ヒットがdirectと併合され決定的TSVになる(tmp_path: Path):
    src, inp = _setup(
        tmp_path,
        {"C.java": 'class C { static final String STATUS_OK = "S"; }\n',
         "U.java": "class U { String x = STATUS_OK; }\n"},
        'C.java:1:static final String STATUS_OK = "S";\n', "STATUS_OK")
    out, out2 = tmp_path / "o1", tmp_path / "o2"
    assert main(["--input", str(inp), "--output", str(out),
                 "--source-root", str(src)]) == 0
    main(["--input", str(inp), "--output", str(out2), "--source-root", str(src)])
    a = (out / "STATUS_OK.tsv").read_text("utf-8-sig")
    cols = a.splitlines()[0].split("\t")
    rows = [dict(zip(cols, ln.split("\t"))) for ln in a.splitlines()[1:]]
    kinds = {r["file"]: r["ref_kind"] for r in rows}
    assert kinds["C.java"] == "direct" and kinds["U.java"] == "indirect:constant"
    assert a == (out2 / "STATUS_OK.tsv").read_text("utf-8-sig")  # 決定的


def test_max_depth0は間接追跡せずdirectのみ(tmp_path: Path):
    src, inp = _setup(
        tmp_path,
        {"C.java": 'class C { static final String STATUS_OK = "S"; }\n',
         "U.java": "class U { String x = STATUS_OK; }\n"},
        'C.java:1:static final String STATUS_OK = "S";\n', "STATUS_OK")
    out = tmp_path / "o"
    main(["--input", str(inp), "--output", str(out), "--source-root", str(src),
          "--max-depth", "0"])
    rows = (out / "STATUS_OK.tsv").read_text("utf-8-sig").splitlines()[1:]
    assert all("\tdirect\t" in r for r in rows)


def test_lang_mapはdirectとindirectで対称に効く(tmp_path: Path):
    # .inc を java 扱いにすると direct も indirect も java 言語で判定される
    src, inp = _setup(
        tmp_path,
        {"C.inc": 'class C { static final String STATUS_OK = "S"; }\n',
         "U.inc": "class U { String x = STATUS_OK; }\n"},
        'C.inc:1:static final String STATUS_OK = "S";\n', "STATUS_OK")
    out = tmp_path / "o"
    main(["--input", str(inp), "--output", str(out), "--source-root", str(src),
          "--lang-map", ".inc=java"])
    a = (out / "STATUS_OK.tsv").read_text("utf-8-sig")
    cols = a.splitlines()[0].split("\t")
    rows = [dict(zip(cols, ln.split("\t"))) for ln in a.splitlines()[1:]]
    assert all(r["language"] == "java" for r in rows)
    assert any(r["ref_kind"] == "indirect:constant" for r in rows)
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/integration/test_pipeline_fixedpoint.py -q`
Expected: FAIL（`--max-depth`/`--lang-map` 未知引数、または indirect 行が出ず AssertionError）

- [ ] **Step 3: 実装**

`src/grep_analyzer/pipeline.py` を編集。

(1) インポート群を置換 — 既存 `from grep_analyzer.classifiers...` 3 行を削除し以下を追加（`detect_*`/`encoding`/`ingest`/`model`/`tsv`/`diagnostics` の import は残す）:
```python
from grep_analyzer.classify import classify_hit
from grep_analyzer.fixedpoint import EngineOptions, run_fixedpoint
from grep_analyzer.walk import DEFAULT_EXCLUDE
```

(2) `_classify` 関数を**丸ごと削除**し、呼出 `category, confidence = _classify(language, dialect, file_text, lineno, content)` を:
```python
            category, confidence = classify_hit(language, dialect, file_text, lineno, content)
```
へ置換。`detect_language(rel, sample, {})` を `detect_language(rel, sample, lang_map)` に、`detect_shell_dialect`/`extension_resolves_language` 呼び出しはそのまま（lang_map は detect_language のみ・spec §5.1 手順1）。

(3) `run` のシグネチャ・本体末尾を変更（既定は Phase 1 挙動不変）:
```python
def run(
    input_dir: Path, output_dir: Path, source_root: Path,
    opts: EngineOptions | None = None,
) -> int:
    """input/*.grep を処理し、direct＋不動点 indirect を併合した TSV を出力する。"""
    diag = Diagnostics()
    output_dir.mkdir(parents=True, exist_ok=True)
    if opts is None:
        opts = EngineOptions(
            max_depth=10, min_specificity=2, stoplist_path=None, lang_map={},
            include=[], exclude=list(DEFAULT_EXCLUDE), jobs=1,
            follow_symlinks=False, max_file_bytes=5_000_000,
            max_symbols=100_000, max_paths=1000)
    lang_map = opts.lang_map

    for grep_file in sorted(Path(input_dir).glob("*.grep")):
        keyword = grep_file.stem
        raw_bytes = grep_file.read_bytes()
        text, _, _ = decode_bytes(raw_bytes, DEFAULT_FALLBACK)
        hits: list[Hit] = []
        for raw_line in text.splitlines():
            # （既存 Phase 1.5 の grep 行ループ本体は無改変。detect_language の
            #   第3引数 {} を lang_map に、_classify を classify_hit に置換済み）
            ...
        indirect = run_fixedpoint(hits, Path(source_root), opts, diag)
        write_tsv(output_dir / f"{keyword}.tsv", hits + indirect, "utf-8-sig")

    (output_dir / "diagnostics.txt").write_text(diag.render(), encoding="utf-8")
    return 0
```
> `...` は既存 grep 行ループ本体（無改変）。差分は (a) インポート、(b) `_classify`削除→`classify_hit`、(c) `detect_language` 第3引数を `lang_map`、(d) ループ後に `indirect = run_fixedpoint(...)` と `write_tsv(... hits + indirect ...)` の 2 行。`write_tsv` は既存どおり `model.sort_key` で全順序安定ソート＝direct/indirect 混在でも決定的（spec §9）。

`src/grep_analyzer/cli.py` を編集（Phase 2a オプション・`--lang-map` パース）:
```python
import argparse
from pathlib import Path

from grep_analyzer.fixedpoint import EngineOptions
from grep_analyzer.pipeline import run
from grep_analyzer.walk import DEFAULT_EXCLUDE


def _parse_lang_map(spec: str | None) -> dict[str, str]:
    """`.ext=lang,.e2=l2` を {".ext":"lang"} に。空は {}（spec §10.4）。"""
    out: dict[str, str] = {}
    if spec:
        for pair in spec.split(","):
            ext, _, lang = pair.partition("=")
            if ext and lang:
                out[ext if ext.startswith(".") else "." + ext] = lang
    return out


def main(argv: list[str] | None = None) -> int:
    """引数をパースし direct＋不動点パイプラインを実行する（spec §10.4）。"""
    p = argparse.ArgumentParser(prog="grep_analyzer")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--source-root", required=True, dest="source_root")
    p.add_argument("--max-depth", type=int, default=10, dest="max_depth")
    p.add_argument("--min-specificity", type=int, default=2, dest="min_specificity")
    p.add_argument("--stoplist", default=None)
    p.add_argument("--lang-map", default=None, dest="lang_map")
    p.add_argument("--include", action="append", default=[])
    p.add_argument("--exclude", action="append", default=None)
    p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--follow-symlinks", action="store_true", dest="follow_symlinks")
    p.add_argument("--max-file-bytes", type=int, default=5_000_000, dest="max_file_bytes")
    p.add_argument("--max-symbols", type=int, default=100_000, dest="max_symbols")
    p.add_argument("--max-paths", type=int, default=1000, dest="max_paths")
    args = p.parse_args(argv)
    opts = EngineOptions(
        max_depth=args.max_depth, min_specificity=args.min_specificity,
        stoplist_path=Path(args.stoplist) if args.stoplist else None,
        lang_map=_parse_lang_map(args.lang_map), include=args.include,
        exclude=args.exclude if args.exclude is not None else list(DEFAULT_EXCLUDE),
        jobs=args.jobs, follow_symlinks=args.follow_symlinks,
        max_file_bytes=args.max_file_bytes, max_symbols=args.max_symbols,
        max_paths=args.max_paths)
    return run(input_dir=Path(args.input), output_dir=Path(args.output),
               source_root=Path(args.source_root), opts=opts)
```

- [ ] **Step 4: テストが通ることを確認（当該＋全体回帰）**

Run: `python -m pytest tests/integration/test_pipeline_fixedpoint.py -q` → PASS（3本）

Run: `python -m pytest -q`
Expected: **`tests/golden` の `shell_direct` と `oracle_direct` が FAIL（赤）になる** — これは想定どおり（下記）。それ以外の既存テスト（`test_pipeline.py`/`test_pipeline_dialect.py`/他8 golden/smoke）は **PASS のまま**。**ここで commit しない**。Task 11 で golden を意図的に regen してから併せて commit する。

> **重要・既存 golden 影響の確定（v1 の「10不変」主張は誤りだったため是正済み）:** `fixedpoint` 配線で chase シンボルが **seed 物理行以外**に出現する合成ツリーは間接行を正当に獲得する。実検証済みの影響:
> - **`shell_direct`（変化）**: `run.sh:1 CODE="X"` から var `CODE`。`run.sh:2 echo "$CODE"` の `$CODE` は非 seed 行＝`indirect:var` 1 行増。
> - **`oracle_direct`（変化）**: `o.sql:2 v_code := 'X';` から var `v_code`。`o.sql:1 v_code VARCHAR2(10);` は非 seed 行＝`indirect:var` 1 行増。
> - **不変（8件）**: `java_direct`（STATUS_OK 出現は全て seed 行 2/4）、`c_direct`（CODE は seed 行のみ）、`proc_direct`（`p` は min_specificity=2 で too_short）、`sql_direct`（`:=` 無し＝chase 空）、`csh_direct`/`csh_noext_shebang`/`sh_noext_shebang`（CODE 出現は全て seed 行）、`encoding_utf8`（`コード` は ASCII 開始でない＝抽出されない・v1 既知の ASCII 識別子限界）。
> これは Phase 2 の**意図した挙動追加**であり writing-tests の「大量churn＝構造を疑う」誤発火ではない（2/10・理由が機構的に説明可能）。Task 11 で 2 件を目視 regen する。

- [ ] **Step 5: コミット（golden を含まない実装のみ）**

```bash
git add src/grep_analyzer/pipeline.py src/grep_analyzer/cli.py tests/integration/test_pipeline_fixedpoint.py
git commit -m "feat(pipeline): direct＋不動点併合配線＋--lang-map対称＋CLI（spec §8/§10.4）"
```
> 注: この時点で `python -m pytest -q` は shell_direct/oracle_direct が赤。**Task 11 と連続で実施**し Task 11 完了時に全緑へ戻す（Task 9 単独 commit は実装の論理的単位として残すが、Task 10/11 着手前に赤を残さない運用＝subagent 実行時は Task 9→10→11 を中断なく進める）。

---

## Task 10: §8.4 診断の正本（全件性・決定性の契約）

**Files:**
- Test: `tests/integration/test_diagnostics_phase2.py`

spec §8.4 は「唯一の正本」。横展開抑止／集合上限切り捨て（**全件**）／生成コード除外／symlink 重複／max-depth 到達／getter 全件報告／**diagnostics の決定性（2 回実行で同一）**を契約として固定。実装が満たさない契約があれば該当 `diag.add` を最小追加（テストを緩めない）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/integration/test_diagnostics_phase2.py` を新規作成:
```python
"""§8.4 診断正本の境界契約（spec §8.4/§10.3・全件性・決定性）。"""

from pathlib import Path

from grep_analyzer.cli import main


def _run(tmp_path, src_files, grep, keyword, extra=None, outname="out"):
    src = tmp_path / "src"; src.mkdir(exist_ok=True)
    for rel, body in src_files.items():
        f = src / rel; f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, "utf-8")
    inp = tmp_path / "input"; inp.mkdir(exist_ok=True)
    (inp / f"{keyword}.grep").write_text(grep, "utf-8")
    out = tmp_path / outname
    main(["--input", str(inp), "--output", str(out),
          "--source-root", str(src)] + (extra or []))
    return (out / "diagnostics.txt").read_text("utf-8")


def test_複数getterが全件抑止記録される(tmp_path: Path):
    d = _run(tmp_path,
             {"S.java": "class S{ int v = a.getName(); String w = b.getCode(); }\n",
              "T.java": "class T{ String n = c.getName(); String m = d.getCode(); }\n"},
             "S.java:1:int v = a.getName();\n", "v")
    assert "getter_setter_no_expand\tgetName" in d
    assert "getter_setter_no_expand\tgetCode" in d  # 全件（2 種とも）


def test_集合上限切り捨てが全件記録される(tmp_path: Path):
    d = _run(tmp_path,
             {"A.java": "class A{ int aa=bb; int bb=cc; int cc=1; }\n",
              "B.java": "class B{ int z=aa; }\n"},
             "A.java:1:int aa=bb;\n", "aa",
             extra=["--max-symbols", "1", "--min-specificity", "1"])
    assert d.count("symbol_rejected\tcapped") >= 1


def test_生成コード除外とmax_depth到達が記録される(tmp_path: Path):
    d = _run(tmp_path,
             {"build/Gen.java": "class Gen{ String x = STATUS_OK; }\n",
              "K.java": 'class K{ static final String STATUS_OK="S"; }\n',
              "L.java": "class L{ String y = STATUS_OK; String z = y; }\n"},
             'K.java:1:static final String STATUS_OK="S";\n', "STATUS_OK",
             extra=["--max-depth", "1"])
    assert "walk_excluded\tbuild/Gen.java" in d
    assert "prov_max_depth" in d


def test_diagnosticsは2回実行で完全一致の決定的(tmp_path: Path):
    files = {"A.java": "class A{ static final int K=1; }\n",
             **{f"{n}.java": f"class {n}{{ int v=K; }}\n" for n in "BCDEF"}}
    d1 = _run(tmp_path, files, "A.java:1:static final int K=1;\n", "K", outname="r1")
    d2 = _run(tmp_path, files, "A.java:1:static final int K=1;\n", "K", outname="r2")
    assert d1 == d2
```

- [ ] **Step 2: 失敗を確認 → 必要なら最小修正**

Run: `python -m pytest tests/integration/test_diagnostics_phase2.py -q`
Expected: 基本 PASS（Task 8 で各診断は実装済み・`diag.add` は決定的集約フェーズで sorted 呼び出し）。FAIL する契約があれば該当 `diag.add` を `fixedpoint`/`walk` の決定的順序呼び出しに最小追加して PASS（テストは緩めない）。決定性テストが落ちる場合は、診断 add が並列ワーカ内でなく `sorted(results)` 集約フェーズ・`sorted(part.rejected)` で行われていることを確認（Task 8 実装はこれを満たす）。

- [ ] **Step 3: 全体回帰（golden 除く）を確認**

Run: `python -m pytest -q --ignore=tests/golden`
Expected: 全 PASS・0 failed / 0 error（golden は Task 11 で確定）。

- [ ] **Step 4: コミット**

```bash
git add tests/integration/test_diagnostics_phase2.py src/grep_analyzer/
git commit -m "test(diagnostics): §8.4 正本の全件性・決定性契約を固定（spec §8.4）"
```

---

## Task 11: golden（既存2件の意図的 regen＋多ホップ代表）

**Files:**
- Modify: `tests/golden/cases/shell_direct/expected/CODE.tsv`
- Modify: `tests/golden/cases/oracle_direct/expected/X.tsv`
- Create: `tests/golden/cases/indirect_constant/...`
- Create: `tests/golden/cases/indirect_var_shell/...`
- Create: `tests/golden/cases/chain_multipath/...`
- Create: `tests/golden/cases/getter_no_expand/...`

spec §11 必須回帰: 汎用 getter 横展開抑止／chain 複数経路の決定性（**真のダイヤモンドで別行**）／indirect:constant・var 網羅。`category_sub` 空固定。symlink 重複排除は unit `test_walk.py` が担保（conftest で symlink 生成は過剰結合＝層の縄張り。golden は決定性最終形に限定＝spec §11 文言と整合）。`tests/golden/conftest.py` 無改変（`cases/*/` 自動 parametrize）。

- [ ] **Step 1: 既存 2 件の変化を目視 regen（writing-tests Golden 規律）**

Run: `python -m pytest tests/golden -q`
Expected: `shell_direct` と `oracle_direct` のみ FAIL（Task 9 想定どおり）。他8は PASS。**FAIL が 2 件以外なら停止し構造を疑う**（Task 9 注記の機構説明と不一致＝回帰の疑い）。

regen（既存 expected を上書き）:
```bash
for c in shell_direct oracle_direct; do
  python -m grep_analyzer --input tests/golden/cases/$c/input \
    --output tests/golden/cases/$c/expected \
    --source-root tests/golden/cases/$c/src
done
rm -f tests/golden/cases/*/expected/diagnostics.txt
git diff tests/golden/cases/shell_direct tests/golden/cases/oracle_direct
```
**目視レビュー必須**。確認:
- `shell_direct/expected/CODE.tsv`: 既存 direct 行（run.sh:1）不変＋新規 `run.sh\t2\tindirect:var\t...\tCODE\tCODE@run.sh:1 -> CODE@run.sh:2\techo "$CODE"\t...`。
- `oracle_direct/expected/X.tsv`: 既存 direct 2 行（o.sql:2/3）不変＋新規 `o.sql\t1\tindirect:var\t...\tv_code\tX@o.sql:2 -> v_code@o.sql:1\tv_code VARCHAR2(10);\t...`（chain 起点 keyword `X`＝spec §9「調査対象の文言」）。
- 他8 golden は `git diff` に出ない（不変）。出たら**停止し構造を疑う**。

- [ ] **Step 2: 多ホップ代表ケースの src/input を作る**

`indirect_constant/src/C.java`: `class C { static final String STATUS_OK = "S"; }`
`indirect_constant/src/U.java`: `class U { String x = STATUS_OK; }`
`indirect_constant/input/STATUS_OK.grep`: `C.java:1:static final String STATUS_OK = "S";`

`indirect_var_shell/src/run.sh`:
```sh
CODE="X"
use $CODE
```
`indirect_var_shell/src/other.sh`: `log $CODE`
`indirect_var_shell/input/CODE.grep`: `run.sh:1:CODE="X"`

`chain_multipath`（**真のダイヤモンド**＝同一ヒット H へ 2 単純パス）:
`chain_multipath/src/A.java`: `class A { static final int K = 1; }`
`chain_multipath/src/P.java`: `class P { static final int H = K; }`
`chain_multipath/src/Q.java`: `class Q { static final int H = K; }`
`chain_multipath/src/D.java`: `class D { int z = H; }`
`chain_multipath/input/K.grep`: `A.java:1:static final int K = 1;`
（K→P:H, K→Q:H の 2 経路で D.java の `H` 利用へ到達＝chain 2 行）

`getter_no_expand/src/S.java`: `class S { int v = a.getName(); }`
`getter_no_expand/src/T.java`:
```java
class T { String n = b.getName();
 String m = c.getName(); }
```
`getter_no_expand/input/v.grep`: `S.java:1:int v = a.getName();`

- [ ] **Step 3: 期待 TSV を生成（必ず目視レビュー）**

```bash
for c in indirect_constant indirect_var_shell chain_multipath getter_no_expand; do
  python -m grep_analyzer --input tests/golden/cases/$c/input \
    --output tests/golden/cases/$c/expected \
    --source-root tests/golden/cases/$c/src
done
rm -f tests/golden/cases/*/expected/diagnostics.txt
git diff --stat tests/golden/cases/
```
**目視レビュー必須**。確認:
- `indirect_constant`: `C.java:1 direct`＋`U.java:1 indirect:constant via STATUS_OK chain "STATUS_OK@C.java:1 -> STATUS_OK@U.java:1"`、`category_sub` 空。
- `indirect_var_shell`: `run.sh:1 direct`＋`run.sh:2 indirect:var`＋`other.sh:1 indirect:var`（`$CODE`）。
- `chain_multipath`: `D.java` の `H` 利用が **2 行**（chain `K@A.java:1 -> ... -> H@P.java:1 -> H@D.java:1` と `... -> H@Q.java:1 -> H@D.java:1`）で決定的順。直前ホップ symbol が同一 `H` でも別 Occurrence で単純パス（spec §9）。
- `getter_no_expand`: `T.java` の 2 行（lineno 1,2）に `getName` が `indirect:getter`・`confidence=low`、`getName` から先のシンボルは出ない（横展開なし）。
- 既存 8 不変・Step1 の 2 件は意図変化のみ。

- [ ] **Step 4: golden 全緑＋全体回帰ゼロを確認**

Run: `python -m pytest tests/golden -q`
Expected: 全 PASS（既存10〔うち2は意図 regen 済〕＋新規4＝14 ケース parametrize）。

Run: `python -m pytest -q`
Expected: 全 PASS・**0 failed / 0 error**（Task 9 で残った赤がここで解消）。

- [ ] **Step 5: コミット（golden 規約）**

```bash
git add tests/golden/cases/
git commit -m "chore(golden): Phase2 間接の既存2件意図regen＋多ホップ代表4ケース（spec §11）"
```

---

## Task 12: Phase 2a 全テスト緑化と完了確認

**Files:**
- Modify: `docs/superpowers/plans/phase0-gate-result.md`

- [ ] **Step 1: 全テスト実行**

Run: `cd /workspaces/grep_helpers2 && python -m pytest -q`
Expected: 全 PASS（Phase 1.5 の 78 ＋ Phase 2a 追加分。0 failed / 0 error）。失敗があれば該当 Task に戻る（完了主張しない＝verification-before-completion）。

- [ ] **Step 2: spec §8/§9/§15・ref_kind×言語表 充足をチェックリスト照合**

`docs/superpowers/specs/2026-05-16-grep-analyzer-design.md` §8/§9/§15 と実装の対応:
- §8.1 反復・停止性 → Task 8（`test_相互参照でも有限母集合で飽和し停止する`）
- §8.1 手順5 Pro\*C ホスト変数 `:` 剥がし → Task 1（`test_C定義とconst定数とProCホスト変数を抽出する`）
- §8.3 採否・getter/setter 非投入・**大域**決定的切り捨て → Task 2/3/8（`test_大域集合上限超過は決定的に切り捨て診断記録する`）
- §8.2 来歴集約・jobs 並列決定性 → Task 8（`test_jobs1とjobsNでTSV相当キーが完全一致`）
- §8.2 走査・symlink 重複排除・生成コード除外 → Task 5
- §9 chain 正規形・**真の複数経路の別行決定性** → Task 6/11（`chain_multipath`）
- §9 ref_kind×言語表 全6言語×4 kind の許容/禁止セル → Task 1 の負の契約（SQL/cshell/C は getters/setters 空、proc は getter/setter 空）＋ golden の言語別 ref_kind を点検
- §8.4 診断正本（**全件性・決定性**）→ Task 10
- §5.1 lang_map の direct/indirect 対称 → Task 9（`test_lang_mapはdirectとindirectで対称に効く`）
- direct/indirect 併合の完全決定性 → Task 9（2 回実行一致）＋既存8 golden 不変＋2件意図 regen

- [ ] **Step 3: 完了記録を追記しコミット**

`docs/superpowers/plans/phase0-gate-result.md` 末尾に「## Phase 2a 完了記録」（完了日 UTC、コミット範囲、全テスト結果、上記対応表、既存 golden 2 件を Phase2 間接で意図 regen した旨と理由、Phase 2b/Phase 3 申し送り＝「Phase 2a の境界」要約）を追記。

```bash
git add docs/superpowers/plans/phase0-gate-result.md
git commit -m "chore: Phase 2a 完了（不動点エンジン正しさ・決定性コア）"
```

---

## Phase 2a の境界（2b / Phase 3 は別計画・spec §15 根拠付き正当化）

**spec §15 整合の正当化:** spec §15 フェーズ2 は §8.1/§8.3/§8.2 を一体記載するが、§15 自身が「決定性基盤を間接追跡より先に固める」「単一実装計画は非現実的」と明記し、Phase 1→1.5 も同思想で分割済み。§8.2 のうち**決定性に不可分な来歴集約・jobs 並列決定性は 2a で実装**し、**決定性確立を前提とする資源 degrade は 2a の後に 2b で積む**。これは §15 の設計思想（決定性先行）に沿い、spec 必須要件の恒久欠落ではなく後続フェーズへの分割。Phase 2a 単体は小規模で degrade 不要・テスト可能・出荷可能。

- **Phase 2b に送る**: spec §8.2 の資源 degrade ＝ `--memory-limit` 超過時の来歴グラフ・ディスクスピル、degrade 優先順位（決定的シンボル切り捨て→スピル→**オートマトン分割＝複数パス再走査**・最大走査パス上限）、任意 `ripgrep` 一次粗フィルタ（`@pytest.mark.requires_ripgrep` 隔離）、§8.2 差分走査の限定効果（確定シンボル再ヒット再走査の省略）、**chain 経路数の指数爆発に対する degrade**（Phase 2a は `max_paths` 安全弁＋小規模前提で決定性確保。実規模の経路数制御は 2b）、**全 bytes 親常駐のストリーミング化**（Phase 2a は `files` に bytes 常駐＝spec §8.2「ストリーミング走査」は 2b で実装。Phase 2a は正しさ・決定性のみ責務）、**キーワード横断の walk 診断重複の集約**（pipeline が keyword ごとに `run_fixedpoint` を呼ぶため同一ツリーの walk 診断が keyword 数ぶん出る。spec §10.3 縮約と併せ Phase 3）。
- **Phase 3 に送る**: 60GB perf ベースライン（`tests/perf/` 非ゲート）、`--resume`、diagnostics の上限縮約（spec §10.3）、規模分割 `<keyword>.partNN.tsv`（spec §9）、`requirements.lock`（spec §4.1・**ユーザ決定で Phase 3**）。
- **Phase 2a の既知の境界（spec 引用付き・誤検出ではなく仕様固定）**: (1) 字句正規表現抽出（tree-sitter 型解決はしない＝spec §8.3 前提どおり。精度は handcrafted の領分＝非ゲート）。(2) ASCII 識別子前提（`encoding_utf8` の `コード` 等の非 ASCII 識別子は v1 で追跡しない＝spec §8.2 識別子境界の v1 既知境界。golden で直接固定）。(3) `_parents_of` の親集合は広めだが provenance 単純パス（同一追跡シンボル二度禁止）で chain は有限・決定的（spec §9）。意味的同一性（別ファイルの同名定数が別実体か）は型解決不能のため human 判断＝spec §8.4 正本に従う既知近似。

Phase 2a の成果物は「direct＋多ホップ indirect を偽陽性抑止（文字列マスク・getter 非展開・静的採否・大域 cap）しつつ `--jobs` 並列でも完全決定的に出し、chain 複数経路を真のダイヤモンド golden で固定した動くツール」であり、それ単体でテスト可能・出荷可能。

---

## Self-Review（v2・本計画著者によるチェック）

**1. spec coverage（§8/§9/§15 の 2a 範囲）:** §8.1 抽出/反復/停止性/Pro\*C手順5 → Task1/8 ✓。§8.2 Aho-Corasick/multiprocessing決定的集約/symlink/生成コード → Task4/5/8 ✓。§8.2 memory-limit/spill/オートマトン分割/ripgrep/差分/ストリーミング → 2b（§15 根拠付き境界節に明記）✓。§8.3 静的採否/getter非投入/**大域**決定的切り捨て → Task2/3/8 ✓。§8.4 全件性・決定性 → Task10 ✓。§9 ref_kind列/chain正規形/**真の**複数経路別行/決定性ソート（既存 `model.sort_key`）→ Task6/8/11 ✓。§9 ref_kind×言語表の禁止セル → Task1負の契約＋Task12照合 ✓。§5.1 lang_map direct/indirect 対称 → Task9 ✓。§15「chain複数経路をgoldenで固定」→ Task11 `chain_multipath`（真ダイヤモンド）✓。§10.4 CLI（max-depth/min-specificity/stoplist/lang-map/include/exclude/jobs/follow-symlinks/max-symbols/max-paths）→ Task9 ✓。`--memory-limit`/`--use-ripgrep`/`--resume`/`--progress`/`--output-encoding`/`--encoding-fallback` は 2b/Phase3（境界節）✓。

**2. Placeholder scan:** 各 Task に実コード・実コマンド・期待出力。Task9 Step3 の `...` は「既存無改変ループ本体」を差分3点と共に明示＝プレースホルダでない。「TBD/後で」表現なし。

**3. Type consistency（タスク間串刺し）:** `ChaseSymbols`/`mask_literals`/`extract_chase_symbols`/`SymbolPolicy`（cap無し）/`admit`/`partition`/`Occurrence(order=True)`/`ProvenanceGraph.{add_seed,is_seed_location,add_edge,chains_to}`（`chains_to` は `*, max_depth, max_paths, diag` キーワード専用で Task6/8 一致）/`automaton.{build,scan_line}`/`walk.walk_files`/`classify.classify_hit`/`EngineOptions`（`lang_map`/`max_paths` 含む）/`run_fixedpoint` を冒頭契約と全 Task で一致確認。`max_depth` の単一定義（ホップ数・0=direct のみ）を provenance `_dfs`（`len(path)-1>=max_depth`）・fixedpoint `_ingest`（`hop>max_depth` 抑止）・CLI で串刺し（Task6 テスト `test_max_depthはホップ数で単一定義され0は間接ゼロ` で固定）。v1 の Task6 max_depth/cycle テスト不整合・`s.snippet[:0]` 死コード・per-call cap・getter hop1限定・三重デコード・既存golden誤主張・偽 chain は本 v2 で解消。

**4. v1 批判的レビュー指摘の解消対応表（Critical/High）:** C-2/C2/H4 seed方言・死コード→Task8 seed実読＋snippet禁止 ✓ / R3-C1 既存golden破壊→Task9 `is_seed_location`＋Task11 意図 regen明記 ✓ / R1-C3 per-call cap→Task8 大域 cap ✓ / R2-C3 sym_origin偽 chain→provenance シンボル単純パス＋`_parents_of`再設計 ✓ / R1-C1・R2-M4・R3-C2 getter 報告漏れ/hop1限定→Task8 term全反復走査・全件 low・横展開のみ抑止 ✓ / R2-M3・R3-C3/C4 Task6テスト不整合→Task6 max_depth/cycle/cap テスト実装一致 ✓ / R2-H1・R1-H1 Java定数→static∧final・generic/配列 ✓ / R2-H2 文字列内抽出→`mask_literals` ✓ / R2-H3 三重デコード→`_file_meta`単一＋キャッシュ ✓ / R2-H4 経路爆発→`max_paths`＋2b境界 ✓ / R1-H3 lang_map非対称→Task9 対称配線＋`--lang-map`実装 ✓ / R1-H4 §15整合論証→境界節正当化 ✓ / R3-H1 chain_multipath空洞→真ダイヤモンド ✓ / R1-H2 ref_kind×言語禁止セル→Task1/12 ✓ / R1-M3 Pro\*C手順5→Task1 ✓ / M-2 §8.4全件/決定性→Task10 ✓ / R2-L2/R3-H3 `__import__`→通常import ✓ / R1-M4 DEFAULT_EXCLUDE過剰→v1スコープ4件＋segmentマッチャ ✓ / R3-M2 symlink_dedup名実不一致→golden廃止しunit担保＋境界節明記 ✓ / C2/M5 Task8/9二重実装→単一Task8 ✓。
