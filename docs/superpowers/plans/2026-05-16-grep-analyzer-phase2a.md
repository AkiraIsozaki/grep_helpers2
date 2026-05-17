# grep_analyzer Phase 2a（不動点エンジンの正しさ・決定性コア） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **コミットは全て末尾に `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` を付す（ハーネス規約。各 Task の `git commit` 例では簡潔化のため省略表記しているが必ず付与）。**

> **改訂履歴:** v1（`docs(plan)`）→ v2（1巡目）→ v3（2巡目）→ **v4（本書・3巡目3並行レビュー反映）**。3巡目は全観点が **No-Go→条件付き Go**（中核設計＝intro 精密エッジ/provenance/停止性/jobs決定性/大域cap単調性/Pro\*C非投入/マスク非対称を実走トレースで全面健全と確認、2巡目 Critical 全件解消を実証）。v4 で残る局所欠陥を是正:
> - **Task7 テスト入力是正**: 不正 Java（クラス本体直下の `if`）が tree-sitter ERROR 化し確実 RED → 既存 test_ts_classifier/test_pipeline と同形（メソッド内・`if` 単独行・正 lineno）に差替。
> - **chain_multipath 純化**: `D.java` を `check(HUB)`（代入なし）にし `use@D` var ノイズ行を排除。Task11 Step3 を実出力厳密 9 行に書換（実装者が正しい決定的出力で誤って「構造を疑う」停止するのを防止）。
> - **intro 自己汚染根治**: `_ingest` に `is_seed` を追加し、非 seed 親の自己定義行が自分自身を再抽出しても発見元にしない（spec §8.2「発見元≠発見」。3巡目 R1-High2）。出力は不変だが invariant を honest 化・グラフ純化。
> - **spec §8.1 手順5 を本体明確化**（コミット `8c21227`）: 手順5「ホスト変数は `:` を剥がした原識別子を採用」が手順1「非投入」と字義衝突し v1→v2→v3 で投入/非投入が反転した決定性プロセス瑕疵を、§9 改訂（`07e81bb`）と同作法で解消（手順5＝停止性字句形のみ・投入是非は手順1）。
> - §9 ref_kind×言語表の禁止セル負の契約テスト追加（Task1）、getter 報告量 vs PRD のリスク開示・マスク非対称の spec 引用是正（§8.4→§7+§8）・cap 単調性/prov_max_depth 二重記録/csh_direct 差分理由を実装注・境界に明記。
>
> （以下 v3 までの是正履歴）2巡目の Critical/High を spec/コードで技術検証し是正:
> - **来歴エッジを `intro`（実抽出元 Occurrence）ベースに再設計**し v1/v2 で未解消だった偽 chain（`_parents_of` の全 seed 無条件親化・無関係 child 親化）を根治。`_parents_of` は廃止。
> - **Pro\*C ホスト変数 `:var` は追跡投入しない**に是正（spec §8.1 手順1「バインド/置換変数は外部・ホスト境界のため追跡投入しない＝Pro\*C ホスト変数と同様」を精読確認。v2 の `_PROC_HOSTVAR_RE` 投入は v1 指摘の過剰修正だった）。
> - **テストフィクスチャの実害バグ修正**: Task1 マスク期待文字列を実長（24字）に、Task8 停止性/jobs/chain_multipath の 1 文字識別子を多文字化（既定 `min_specificity=2` で空 PASS していた）、Task10 `prov_max_depth` を fixedpoint 側で記録し充足可能化。
> - **大域 cap の単調性保持**: `chase_done` から discard せず恒久除外集合 `capped` で scan 除外（spec §8.1 手順5 単調増加を保つ）。
> - **spec §9 改訂を反映**: 「同一シンボル＝追跡識別子・起点 keyword は対象外」が spec 本体に明文化済（コミット `07e81bb`「spec(§9): 単純パスの『同一シンボル』を明確化」）。本計画はそれに従属。
> - getter「direct一致のみ」の主語を spec §8.1 手順1「seed/既存ヒットから抽出」で根拠付け、`pipeline.py` を全文掲載（`...` 廃止）、マスク非対称（抽出=マスク／走査=raw）の根拠を明記。

**Goal:** Phase 1/1.5 の direct-only 決定性基盤の上に、spec §8.1 不動点反復＋§8.3 シンボル採否（汎用 getter 横展開の構造的抑止）＋§8.2 来歴集約を実装し、多ホップ間接ヒット（`indirect:constant|var|getter|setter`）と chain 複数経路を **`--jobs` 並列でも完全決定的** に出力する。偽陽性抑止と停止性を小規模合成ツリーで実測検証し、chain 複数経路の決定性を golden で固定する。

**Architecture:** 既存 `grep_analyzer` を後方互換拡張。Phase 1.5 決定的コア（`dispatch`/`classifiers`/`model`/`tsv`/`diagnostics`/`encoding`/`ingest`/`proc_preprocess`）は不変。`chase.py` に文字列/コメントマスキング付き分類抽出を追加。新規 `stoplist.py`／`automaton.py`／`walk.py`／`provenance.py`／`classify.py`／`fixedpoint.py` を追加。`pipeline.py` は direct 後にエンジンを呼び indirect 併合、`cli.py` に Phase 2a オプション追加。**2b（資源 degrade：`--memory-limit` スピル・オートマトン分割多パス・`ripgrep`・chain 経路爆発 degrade・bytes ストリーミング化）／Phase 3（60GB perf・`--resume`・diagnostics 縮約・規模分割・`requirements.lock`）は範囲外**（末尾「境界」で spec §15 根拠付き正当化）。

**Tech Stack:** Python 3.12 / pytest / `pyahocorasick==2.1.0`（Phase 2 着手ゲート PASS。`Automaton.iter(s)`=`(end_index, value)`・部分文字列も拾うため識別子境界フィルタ必須）。tree-sitter/chardet 既存のまま。`docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`（v7・**§9 は `07e81bb` で明確化済**・spec が常に優先）、`.claude/skills/writing-tests.md`、`.claude/skills/coding-conventions.md` に従う（docstring/コメント・テスト名は日本語、古典学派+TDD、外部I/O境界＝ファイルのみ本物）。

**型・シグネチャ契約（全タスク共通・不変。Self-Review 3 で串刺し）:**

- `chase.ChaseSymbols`（frozen）: `.constants/.vars/.getters/.setters: tuple[str, ...]`
- `chase.mask_literals(language: str, line: str) -> str`（文字列/コメントを同幅空白へ。行長・桁不変）
- `chase.extract_chase_symbols(language: str, dialect: str, line: str) -> ChaseSymbols`（内部で `mask_literals` 適用）
- `stoplist.SymbolPolicy(min_specificity: int, user_stoplist: frozenset[str])`（cap 持たず）
- `stoplist.load_stoplist(path: Path | None) -> frozenset[str]`／`stoplist.LANG_KEYWORDS: dict[str, frozenset[str]]`
- `stoplist.admit(symbols, language, policy) -> AdmissionResult(accepted: list[str], rejected: list[tuple[str,str]])`、reason ∈ `{keyword,too_short,user_stoplist}`
- `stoplist.partition(cs, language, policy) -> Partition(chase: list[str], terminal: list[str], rejected: list[tuple[str,str]])`
- `automaton.build(symbols) -> ahocorasick.Automaton | None`／`automaton.scan_line(au, line) -> list[str]`（境界一致・昇順ユニーク）
- `walk.walk_files(root, *, include, exclude, follow_symlinks, max_file_bytes, diag) -> Iterator[tuple[str, Path]]`／`walk.DEFAULT_EXCLUDE: tuple[str,...]`
- `provenance.Occurrence`（frozen, order=True）: `symbol: str, relpath: str, lineno: int`
- `provenance.ProvenanceGraph`: `add_seed(occ)` / `is_seed_location(relpath, lineno) -> bool` / `add_edge(parent, child)` / `chains_to(target, *, max_depth: int, max_paths: int, diag) -> list[str]`（hop 表記 `symbol@relpath:lineno`・` -> ` 連結）
- `classify.classify_hit(language, dialect, file_text, lineno, content) -> tuple[str,str]`
- `fixedpoint.EngineOptions`（dataclass）: `max_depth:int, min_specificity:int, stoplist_path:Path|None, lang_map:dict[str,str], include:list[str], exclude:list[str], jobs:int, follow_symlinks:bool, max_file_bytes:int, max_symbols:int, max_paths:int`
- `fixedpoint.run_fixedpoint(seed_hits, source_root, opts, diag) -> list[Hit]`（indirect のみ）
- **来歴エッジ確定規則（v3 中核）**: `intro: dict[str, list[Occurrence]]` を `_ingest(parent_occ, line, …)` で「その行から抽出された各シンボル → parent_occ」と記録。シンボル `s` がツリー上 `Occurrence(s,rel,ln)` で発見されたら **`intro[s]` の各 parent_occ → 当該 child へ 1 本ずつ**エッジを張る（spec §8.2「(発見元シンボル,発見シンボル,file,lineno)」を実抽出元で精密化）。`_parents_of` は存在しない。

**spec 解釈の明示（spec 本体改訂と整合・次レビューで再検証可能）:**

- **`max_depth`＝chain のホップ数（` -> ` の本数）の上限**。`--max-depth 0`＝ホップ0＝direct のみ。engine `_ingest` の `hop>max_depth` 抑止・`provenance.chains_to` のパス長・CLI を単一定義で串刺し（spec §8.1 手順6 / §9「`--max-depth` 超過パスも打ち切り」）。**`hop>max_depth` で打ち切った事実は fixedpoint が `prov_max_depth` を diagnostics に記録**（spec §8.1 手順6「max-depth 到達は diagnostics 明示」。chains_to も経路長打ち切り時に記録）。
- **単純パスの「同一シンボル」**: spec §9 が `07e81bb` で「不動点に投入された追跡識別子（chase/terminal）を指し、起点 keyword（調査対象の文言・追跡識別子でない）は循環判定対象外」と明確化済。本計画はこれに従属＝`provenance._dfs` は起点 keyword の symbol を `visited_sym` に入れず、`CODE@def -> CODE@use` を許容（PRD 主目的）。定数連鎖 A→B→A は最初の再訪で `prov_cycle_cut`。
- **getter/setter（spec §8.3/§8.4）**: chase 集合へ投入せず横展開（ヒット行からの再抽出）しないが、**spec §8.1 手順1「seed/既存ヒットから追跡シンボルを抽出（…getter/setter名…)」に従い、constant/var 追跡で到達した行から抽出した getter/setter も含め automaton に全反復投入し、全出現を `indirect:getter|setter`・`confidence=low` で全件報告**（spec §8.4「同名メソッド全件 confidence=low」）。「既存ヒット」は constant/var 経由で確定した行を含む（§8.1 手順1）。横展開（再帰追跡）抑止と報告（全件）を混同しない。
- **マスク非対称（抽出=マスク／automaton 走査=raw）の根拠**: 追跡シンボルの**抽出**は `mask_literals` 後（文字列内 `"x=1"` をシンボル化しない＝spec §8 偽陽性ノイズ抑止）。一方、既存追跡シンボルの**出現検出**（automaton scan）は raw 行で行う。Shell/SQL の変数利用は `"$CODE"`/`'...&v...'` 等**文字列内に正当出現**し（spec §7 は Shell/SQL の文字列内変数参照を分類対象とする）、走査をマスクすると実利用を取りこぼすため。raw 走査は Shell/SQL の文字列内正当変数参照（spec §7 分類対象）を取りこぼさないための設計判断。Java/C の文字列/コメント内に**静的に書かれた**シンボル字句がヒット化するのは字句ツールの既知近似であり、confidence/分類は spec §7 準拠で human 確認前提（spec §8 の low の趣旨。§8.4「実行時に動的生成される名前」とは別カテゴリなので §8.4 援用はしない）。本非対称は意図的設計として明記する。

---

## Task 0: 着手ゲート（Phase 1.5 緑＋pyahocorasick G1・コードなし）

spec §15 フェーズ2 着手前提: (1) Phase 1.5 全テスト緑、(2) `pyahocorasick` G1 PASS。

- [ ] **Step 1: ベースライン全緑**

Run: `cd /workspaces/grep_helpers2 && python -m pytest -q`
Expected: `78 passed`（0 failed / 0 error）。

- [ ] **Step 2: pyahocorasick G1 PASS 記録の存在**

Run: `grep -nF 'G1 相当判定: **PASS**' docs/superpowers/plans/phase0-gate-result.md`
Expected: 1 行ヒット。ヒットしなければ着手不可（spec §4.2）。

- [ ] **Step 3: pyahocorasick import**

Run: `python -c "import ahocorasick, importlib.metadata as m; print(m.version('pyahocorasick'))"`
Expected: `2.1.0`。失敗時 `python -m pip install --no-index --find-links wheelhouse "pyahocorasick==2.1.0"` 後再確認。

- [ ] **Step 4: ゲート記録しコミット**

`docs/superpowers/plans/phase0-gate-result.md` 末尾に「## Phase 2a 着手ゲート記録」（UTC 日付・`78 passed`・pyahocorasick G1 PASS 参照・判定 PASS）追記。

```bash
git add docs/superpowers/plans/phase0-gate-result.md
git commit -m "chore: Phase 2a 着手ゲート記録（78 passed / pyahocorasick G1 PASS）"
```

注: `requirements.lock` は Phase 3（ユーザ決定）。`--memory-limit`/オートマトン分割/`ripgrep`/経路爆発 degrade は Phase 2b。本計画着手をブロックしない。

---

## Task 1: 文字列/コメントマスキング付き分類抽出 `chase.extract_chase_symbols`

**Files:** Modify `src/grep_analyzer/chase.py` / Test `tests/unit/test_chase.py`

spec §8「偽陽性ノイズは許容しない」。抽出前に文字列リテラル・コメントを同幅空白へマスク（行長・桁不変）。spec §9 ref_kind×言語表に従い `constant/var/getter/setter` を決定的抽出。`extract_var_symbols` 不変（既存7テスト維持）、var は内部再利用。Java 定数は static∧final 必須・generic/配列許容。**Pro\*C ホスト変数 `:var` は追跡投入しない**（spec §8.1 手順1「バインド/置換変数は外部・ホスト境界のため追跡投入しない＝Pro\*C ホスト変数と同様」。手順5 の「`:` を剥がした原識別子」は停止性論証中の*字句形*規定であり投入是非を述べていない）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_chase.py` 末尾に追記:
```python
from grep_analyzer.chase import ChaseSymbols, extract_chase_symbols, mask_literals


def test_文字列とコメントをマスクし行長を保つ():
    src = 'String s = "x=1"; // y=2'
    out = mask_literals("java", src)
    assert out == 'String s =      ;       '   # "x=1"=5字→空白5, // y=2=6字→空白6
    assert len(out) == len(src) == 24
    assert len(mask_literals("c", 'a=1; /* z=9 */ b=2')) == len('a=1; /* z=9 */ b=2')


def test_文字列内の代入様字句は追跡シンボルにしない():
    cs = extract_chase_symbols("java", "", 'String s = "url=/x"; int n = 1;')
    assert "url" not in cs.vars and cs.vars == ("s", "n")


def test_Java定数はstaticかつfinalのみでgenericと配列を許容する():
    assert extract_chase_symbols(
        "java", "", "private static final Map<String, Integer> CODE_MAP = init();"
    ).constants == ("CODE_MAP",)
    assert extract_chase_symbols("java", "", "static final int[] CODES = a;").constants == ("CODES",)
    cs = extract_chase_symbols("java", "", "final int X = 1;")
    assert cs.constants == () and cs.vars == ("X",)
    assert extract_chase_symbols("java", "", "public static int Y = 1;").constants == ()


def test_Javaのgetterとsetterとvarをマスクのうえ分類抽出する():
    cs = extract_chase_symbols("java", "", "int count = svc.getName(); obj.setValue(count);")
    assert cs.vars == ("count",)
    assert cs.getters == ("getName",) and cs.setters == ("setValue",)


def test_C定義とconst定数を抽出しProCホスト変数は追跡投入しない():
    assert extract_chase_symbols("c", "", "#define MAX_LEN 10").constants == ("MAX_LEN",)
    assert extract_chase_symbols("c", "", "const int FOO = 1;").constants == ("FOO",)
    assert extract_chase_symbols("c", "", "int n = 3;").vars == ("n",)
    # spec §8.1 手順1（8c21227 で本体明確化）: Pro*C ホスト変数 :host は
    # 外部・ホスト境界＝追跡投入しない。手順5 は停止性の字句形のみで投入是非でない。
    cs = extract_chase_symbols("proc", "", "EXEC SQL SELECT c INTO :host FROM t;")
    assert "host" not in cs.vars and cs.vars == () and cs.constants == ()


def test_ref_kind言語表の禁止セルは空を返す():
    # spec §9 ref_kind×言語表の `—` セルを負の契約で固定（将来改修の回帰防御）。
    pc = extract_chase_symbols("proc", "", "int n = 3; #define M 1")
    assert pc.getters == () and pc.setters == ()                 # C/Pro*C: getter/setter 無
    sq = extract_chase_symbols("sql", "", "v := 1;")
    assert sq.constants == () and sq.getters == () and sq.setters == ()  # SQL: const/getter/setter 無
    cs = extract_chase_symbols("shell", "cshell", "set CODE = 1")
    assert cs.constants == () and cs.getters == () and cs.setters == ()  # cshell: const 無
    bo = extract_chase_symbols("shell", "bourne", 'NAME="x"')
    assert bo.constants == () and bo.getters == () and bo.setters == ()  # bourne 非readonly: const 無


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
        "shell", "bourne", line)
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_chase.py -q`
Expected: FAIL（`ImportError: cannot import name 'ChaseSymbols'`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/chase.py` 末尾に追記（既存 `extract_var_symbols` 不変）:
```python
from dataclasses import dataclass

_MASK_SPECS = {
    "java": [r'"(?:\\.|[^"\\])*"', r"'(?:\\.|[^'\\])*'", r"//[^\n]*", r"/\*.*?\*/"],
    "c": [r'"(?:\\.|[^"\\])*"', r"'(?:\\.|[^'\\])*'", r"//[^\n]*", r"/\*.*?\*/"],
    "proc": [r'"(?:\\.|[^"\\])*"', r"'(?:\\.|[^'\\])*'", r"//[^\n]*", r"/\*.*?\*/"],
    "sql": [r"'(?:''|[^'])*'", r"--[^\n]*", r"/\*.*?\*/"],
    "shell": [r'"(?:\\.|[^"\\])*"', r"'[^']*'", r"#[^\n]*"],
}
_MASK_RE = {lang: re.compile("|".join(p), re.DOTALL) for lang, p in _MASK_SPECS.items()}

_JAVA_GETSET_RE = re.compile(r"\b((?:get|set)[A-Z]\w*)\s*\(")
_JAVA_CONST_RE = re.compile(
    r"\b((?:public|protected|private|static|final)(?:\s+(?:public|protected|private|static|final))*)"
    r"\s+[\w.$]+(?:\s*<[^=;{}]*?>)?(?:\s*\[\s*\])*\s+([A-Za-z_]\w*)\s*=")
_JAVA_VAR_RE = re.compile(r"(?<![=!<>+\-*/%&|^])\b([A-Za-z_]\w*)\s*=(?!=)")
_C_DEFINE_RE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)")
_C_CONST_RE = re.compile(r"\bconst\b[\w\s*]*?\b([A-Za-z_]\w*)\s*=")
_C_VAR_RE = re.compile(r"(?<![=!<>+\-*/%&|^])\b([A-Za-z_]\w*)\s*=(?!=)")
_BOURNE_READONLY_RE = re.compile(r"^\s*readonly\s+([A-Za-z_]\w*)=")


def mask_literals(language: str, line: str) -> str:
    """文字列リテラル・コメントを同幅の空白へ置換（行長・桁・行番号を保存）。

    偽陽性ノイズ抑止（spec §8）。マッチ全体を同字数スペースに潰すので後段の
    正規表現抽出に影響しない。automaton 走査は raw 行（spec 解釈の明示・非対称根拠）。
    """
    re_ = _MASK_RE.get(language)
    return line if re_ is None else re_.sub(lambda m: " " * len(m.group(0)), line)


@dataclass(frozen=True)
class ChaseSymbols:
    """1行から抽出した追跡候補（spec §8.1/§9）。getters/setters は §8.3 で

    横展開しない報告専用候補（fixedpoint が terminal として全件 low 報告）。
    """

    constants: tuple[str, ...] = ()
    vars: tuple[str, ...] = ()
    getters: tuple[str, ...] = ()
    setters: tuple[str, ...] = ()


def extract_chase_symbols(language: str, dialect: str, line: str) -> ChaseSymbols:
    """1行をマスク後に spec §9 ref_kind×言語表で分類抽出する（決定的・出現順）。

    var は extract_var_symbols 再利用。getter/setter は Java 字句のみ。Pro*C
    ホスト変数 :var は追跡投入しない（spec §8.1 手順1 外部・ホスト境界）。
    """
    m = mask_literals(language, line)
    if language == "java":
        consts = tuple(g.group(2) for g in _JAVA_CONST_RE.finditer(m)
                       if "static" in g.group(1).split() and "final" in g.group(1).split())
        getters = tuple(x.group(1) for x in _JAVA_GETSET_RE.finditer(m) if x.group(1)[0] == "g")
        setters = tuple(x.group(1) for x in _JAVA_GETSET_RE.finditer(m) if x.group(1)[0] == "s")
        cset = set(consts)
        vars_ = tuple(v for v in (x.group(1) for x in _JAVA_VAR_RE.finditer(m)) if v not in cset)
        return ChaseSymbols(consts, vars_, getters, setters)
    if language in ("c", "proc"):
        consts = tuple(x.group(1) for x in _C_DEFINE_RE.finditer(m)) + tuple(
            x.group(1) for x in _C_CONST_RE.finditer(m))
        cset = set(consts)
        vars_ = tuple(v for v in (x.group(1) for x in _C_VAR_RE.finditer(m))
                      if v not in cset and v != "const")
        return ChaseSymbols(consts, vars_, (), ())  # Pro*C :host は非投入（spec §8.1手順1）
    if language == "shell" and dialect != "cshell":
        rm = _BOURNE_READONLY_RE.match(m)
        if rm is not None:
            return ChaseSymbols((rm.group(1),), (), (), ())
    return ChaseSymbols((), tuple(extract_var_symbols(language, dialect, m)), (), ())
```

> **注:** マスク期待値は機械的に算出（`"x=1"`=5字→空白5、`// y=2`=6字→空白6、合計 24 字保存）。実装で必ず再確認（Task1 Step4 が `out == 'String s =      ;       '` を assert）。

- [ ] **Step 4: テストが通る（当該＋全体回帰ゼロ）**

Run: `python -m pytest tests/unit/test_chase.py -q` → PASS（既存7＋新規8）
Run: `python -m pytest -q` → 全 PASS・0 failed/0 error。

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/chase.py tests/unit/test_chase.py
git commit -m "feat(chase): 文字列マスク付き分類抽出（spec §8/§9・ProC手順1非投入）"
```

---

## Task 2: 静的シンボル採否 `stoplist.admit`（cap なし）

**Files:** Create `src/grep_analyzer/stoplist.py` / Test `tests/unit/test_stoplist.py`

spec §8.3 静的ストップリスト（① 言語キーワード ② 最小長 ③ ユーザ `--stoplist`）。集合上限切り捨ては大域・累積（spec §8.3）で fixedpoint 側。`admit` は per-symbol 静的篩のみ。

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
    assert r.accepted == ["FOO"] and ("BAR", "user_stoplist") in r.rejected


def test_順序保存で採否しcapはここで行わない():
    r = admit(["zzz", "ab", "yy"], "c", _pol(min_spec=1))
    assert r.accepted == ["zzz", "ab", "yy"]


def test_ストップリストファイルは空行とコメントを無視する(tmp_path):
    f = tmp_path / "stop.txt"
    f.write_text("# c\nFOO\n\n  BAR  \n", "utf-8")
    assert load_stoplist(f) == frozenset({"FOO", "BAR"})
    assert load_stoplist(None) == frozenset()
```

- [ ] **Step 2: 失敗を確認** — Run: `python -m pytest tests/unit/test_stoplist.py -q` → FAIL（ModuleNotFound）

- [ ] **Step 3: 実装** — `src/grep_analyzer/stoplist.py` を新規作成:
```python
"""静的シンボル採否ポリシー（spec §8.3）。汎用名の横展開爆発を篩で防ぐ。

v1 は静的ソースのみ。動的トップN は spec §14 外。集合サイズ上限の決定的
切り捨ては大域・累積のため fixedpoint 側（spec §8.3「(発見ホップ,長さ,辞書順)」）。
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
    "java": _JAVA_KW, "c": _C_KW, "proc": _C_KW, "sql": _SQL_KW, "shell": _SHELL_KW}


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
    """シンボル列を静的ポリシーで決定的に採否（spec §8.3・cap 非適用）。"""
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

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_stoplist.py -q` → PASS（5本）／`python -m pytest -q` → 全 PASS。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/stoplist.py tests/unit/test_stoplist.py
git commit -m "feat(stoplist): 静的シンボル採否（spec §8.3・大域capは分離）"
```

---

## Task 3: getter/setter 非投入の分割 `stoplist.partition`

**Files:** Modify `src/grep_analyzer/stoplist.py` / Test `tests/unit/test_stoplist.py`

spec §8.3 生命線: getter/setter は chase 集合へ投入しない。terminal は fixedpoint が全反復走査し全件 low 報告するが横展開しない。

- [ ] **Step 1: 失敗するテストを書く** — `tests/unit/test_stoplist.py` 末尾に追記:
```python
from grep_analyzer.chase import ChaseSymbols
from grep_analyzer.stoplist import partition


def test_getterとsetterは横展開せずterminalへ回す():
    cs = ChaseSymbols(constants=("STATUS_OK",), vars=("count",), getters=("getName",), setters=("setX",))
    p = partition(cs, "java", _pol(min_spec=2))
    assert p.chase == ["STATUS_OK", "count"]
    assert p.terminal == ["getName", "setX"] and p.rejected == []


def test_terminalにもキーワード最小長は効く():
    cs = ChaseSymbols(getters=("getX",), setters=("set",))
    p = partition(cs, "java", _pol(min_spec=4))
    assert p.terminal == ["getX"] and ("set", "too_short") in p.rejected
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_stoplist.py -q` → FAIL（ImportError partition）

- [ ] **Step 3: 実装** — `src/grep_analyzer/stoplist.py` 末尾に追記:
```python
from grep_analyzer.chase import ChaseSymbols


@dataclass(frozen=True)
class Partition:
    """ChaseSymbols の決定的分割（spec §8.3）。

    chase=横展開対象(constant/var採用)、terminal=報告専用(getter/setter採用・
    横展開しない)、rejected=静的棄却(双方)。cap は非適用(大域=fixedpoint)。
    """

    chase: list[str]
    terminal: list[str]
    rejected: list[tuple[str, str]]


def partition(cs: ChaseSymbols, language: str, policy: SymbolPolicy) -> Partition:
    """ChaseSymbols を「横展開する chase／報告専用 terminal／棄却」に決定的分割。

    spec §8.3 生命線: getter/setter は chase に入れない。keyword/too_short/
    user_stoplist は双方に適用（cap は大域＝fixedpoint）。
    """
    chase_r = admit(list(cs.constants) + list(cs.vars), language, policy)
    term_r = admit(list(cs.getters) + list(cs.setters), language, policy)
    return Partition(chase_r.accepted, term_r.accepted, chase_r.rejected + term_r.rejected)
```

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_stoplist.py -q` → PASS（7本）／`python -m pytest -q` → 全 PASS。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/stoplist.py tests/unit/test_stoplist.py
git commit -m "feat(stoplist): getter/setter 非投入の分割 partition（spec §8.3 生命線）"
```

---

## Task 4: Aho-Corasick ラッパ `automaton.py`（識別子境界）

**Files:** Create `src/grep_analyzer/automaton.py` / Test `tests/unit/test_automaton.py`

spec §8.2。部分文字列を識別子境界で除外。空・空文字シンボル防御。決定的（昇順ユニーク）。

- [ ] **Step 1: 失敗するテストを書く** — `tests/unit/test_automaton.py` を新規作成:
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


def test_空集合と空文字シンボルはNoneあるいは除去():
    assert build([]) is None and build(["", ""]) is None
    assert scan_line(None, "anything") == []
    assert scan_line(build(["", "CODE"]), "CODE") == ["CODE"]


def test_先頭末尾と記号隣接の境界():
    au = build(["CODE"])
    assert scan_line(au, "CODE") == ["CODE"]
    assert scan_line(au, "$CODE)") == ["CODE"]
    assert scan_line(au, "xCODE") == [] and scan_line(au, "CODEx") == []
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_automaton.py -q` → FAIL（ModuleNotFound）

- [ ] **Step 3: 実装** — `src/grep_analyzer/automaton.py` を新規作成:
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
    """1 行から語境界一致シンボルを昇順ユニークで返す（決定的）。"""
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

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_automaton.py -q` → PASS（4本）／`python -m pytest -q` → 全 PASS。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/automaton.py tests/unit/test_automaton.py
git commit -m "feat(automaton): pyahocorasick ラッパ＋識別子境界（spec §8.2）"
```

---

## Task 5: 決定的ツリー走査 `walk.py`

**Files:** Create `src/grep_analyzer/walk.py` / Test `tests/unit/test_walk.py`

spec §8.2: サイズ/バイナリ skip、生成コード既定除外（v1 言語スコープ spec §2.3 整合）、symlink 既定で辿らず realpath 重複排除、relpath 昇順決定的。glob は `/` セグメント自前マッチャ。

- [ ] **Step 1: 失敗するテストを書く** — `tests/unit/test_walk.py` を新規作成:
```python
"""決定的ツリー走査の仕様（spec §8.2）。外部I/O境界＝実FS本物。"""

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
    assert _walk(tmp_path)[0] == ["a.c", "b.c", "sub/c.c"]


def test_生成コードは既定除外しトップでも深くても効き診断記録(tmp_path):
    for rel in ("target/Gen.java", "a/b/build/X.c", "src/Keep.java"):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", "utf-8")
    rels, diag = _walk(tmp_path)
    assert rels == ["src/Keep.java"] and "walk_excluded" in diag.render()


def test_バイナリと巨大ファイルはskipし診断記録(tmp_path):
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01CODE")
    (tmp_path / "big.c").write_text("a" * 50, "utf-8")
    (tmp_path / "ok.c").write_text("CODE", "utf-8")
    diag = Diagnostics()
    rels = [r for r, _ in walk_files(tmp_path, include=[], exclude=list(DEFAULT_EXCLUDE),
            follow_symlinks=False, max_file_bytes=10, diag=diag)]
    assert rels == ["ok.c"]
    d = diag.render()
    assert "walk_skipped_binary" in d and "walk_skipped_large" in d


def test_includeグロブ指定時は一致のみ(tmp_path):
    (tmp_path / "a.java").write_text("x", "utf-8")
    (tmp_path / "b.txt").write_text("y", "utf-8")
    assert _walk(tmp_path, include=["*.java"])[0] == ["a.java"]


def test_symlinkは既定で辿らず実体重複は辞書順代表のみ(tmp_path):
    (tmp_path / "real.c").write_text("CODE", "utf-8")
    os.symlink(tmp_path / "real.c", tmp_path / "link.c")
    rels, diag = _walk(tmp_path)
    assert rels == ["real.c"] and "symlink_skipped" in diag.render()
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_walk.py -q` → FAIL（ModuleNotFound）

- [ ] **Step 3: 実装** — `src/grep_analyzer/walk.py` を新規作成:
```python
"""決定的ツリー走査（spec §8.2）。relpath 昇順・glob・サイズ/バイナリ skip・

生成コード既定除外・symlink は既定で辿らず realpath 重複排除。走査順非依存決定的。
"""

import fnmatch
import os
from collections.abc import Iterator
from pathlib import Path

from grep_analyzer.diagnostics import Diagnostics

# v1 言語スコープ(spec §2.3: Java/C/Pro*C/SQL/Shell)整合の保守的既定。
# Python/JS 生成物は v1 言語外のため含めない。spec §8.2 は具体非列挙＝実装委任。
DEFAULT_EXCLUDE: tuple[str, ...] = (
    "**/target/**", "**/build/**", "**/generated/**", "**/.git/**")


def _match_one(rel: str, pat: str) -> bool:
    rseg = rel.split("/")
    pseg = pat.split("/")

    def m(ri: int, pi: int) -> bool:
        if pi == len(pseg):
            return ri == len(rseg)
        if pseg[pi] == "**":
            return any(m(k, pi + 1) for k in range(ri, len(rseg) + 1))
        if ri == len(rseg):
            return False
        return fnmatch.fnmatch(rseg[ri], pseg[pi]) and m(ri + 1, pi + 1)

    return m(0, 0)


def _match_any(rel: str, patterns: list[str]) -> bool:
    base = rel.rsplit("/", 1)[-1]
    for p in patterns:
        if _match_one(rel, p) or ("/" not in p and fnmatch.fnmatch(base, p)):
            return True
    return False


def _is_binary(path: Path) -> bool:
    with open(path, "rb") as f:
        return b"\x00" in f.read(8192)


def walk_files(
    root: Path, *, include: list[str], exclude: list[str],
    follow_symlinks: bool, max_file_bytes: int, diag: Diagnostics,
) -> Iterator[tuple[str, Path]]:
    """root 配下の通常ファイルを relpath 昇順で yield（spec §8.2）。"""
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
        seen_real[real] = rel
        yield rel, abspath
```

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_walk.py -q` → PASS（5本）／`python -m pytest -q` → 全 PASS。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/walk.py tests/unit/test_walk.py
git commit -m "feat(walk): 決定的走査＋生成コード除外＋symlink重複排除（spec §8.2）"
```

---

## Task 6: 来歴グラフと chain 正規形 `provenance.py`

**Files:** Create `src/grep_analyzer/provenance.py` / Test `tests/unit/test_provenance.py`

spec §9（`07e81bb` 明確化済）chain 正規形・単純パス（同一エッジ・**同一追跡シンボル**を二度通らない／起点 keyword は対象外）。循環は `prov_cycle_cut`、`max_depth`（ホップ数）超過は `prov_max_depth`、経路数 `max_paths` 超過は決定的辞書順先頭採用＋`prov_path_capped`。同一ヒットへ複数単純パスは経路別 chain（重複許容＝spec §9）。

- [ ] **Step 1: 失敗するテストを書く** — `tests/unit/test_provenance.py` を新規作成:
```python
"""来歴グラフと chain 正規形の仕様（spec §9・07e81bb 明確化準拠）。"""

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
    assert _g(s, [(s, m)]).chains_to(m, max_depth=10, max_paths=100, diag=Diagnostics()) == [
        "KEY@a.c:1 -> CODE@b.c:5"]


def test_同名keywordと追跡識別子は単純パスとして許容する():
    s, u = Occurrence("CODE", "r.sh", 1), Occurrence("CODE", "r.sh", 2)
    assert _g(s, [(s, u)]).chains_to(u, max_depth=10, max_paths=100, diag=Diagnostics()) == [
        "CODE@r.sh:1 -> CODE@r.sh:2"]


def test_複数単純パスは経路ごとに別chainを決定的順で返す():
    s = Occurrence("KEY", "a.c", 1)
    p, q, h = Occurrence("P", "p.c", 2), Occurrence("Q", "q.c", 3), Occurrence("H", "h.c", 9)
    assert _g(s, [(s, p), (s, q), (p, h), (q, h)]).chains_to(
        h, max_depth=10, max_paths=100, diag=Diagnostics()) == [
        "KEY@a.c:1 -> P@p.c:2 -> H@h.c:9", "KEY@a.c:1 -> Q@q.c:3 -> H@h.c:9"]


def test_追跡識別子の循環は再訪エッジで打ち切り診断記録する():
    s = Occurrence("KEY", "a.c", 1)
    x, y = Occurrence("X", "x.c", 2), Occurrence("Y", "y.c", 3)
    x2, h = Occurrence("X", "x.c", 9), Occurrence("H", "h.c", 4)
    diag = Diagnostics()
    chains = _g(s, [(s, x), (x, y), (y, x2), (y, h)]).chains_to(
        h, max_depth=10, max_paths=100, diag=diag)
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
    s, h = Occurrence("KEY", "a.c", 1), Occurrence("H", "h.c", 9)
    mids = [Occurrence(f"M{i}", f"m{i}.c", i) for i in range(5)]
    g = ProvenanceGraph()
    g.add_seed(s)
    for mid in mids:
        g.add_edge(s, mid)
        g.add_edge(mid, h)
    diag = Diagnostics()
    chains = g.chains_to(h, max_depth=10, max_paths=2, diag=diag)
    assert chains == ["KEY@a.c:1 -> M0@m0.c:0 -> H@h.c:9", "KEY@a.c:1 -> M1@m1.c:1 -> H@h.c:9"]
    assert "prov_path_capped" in diag.render()


def test_seed物理行は間接から除外判定できる():
    g = ProvenanceGraph()
    g.add_seed(Occurrence("X", "o.sql", 2))
    assert g.is_seed_location("o.sql", 2) is True
    assert g.is_seed_location("o.sql", 1) is False
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_provenance.py -q` → FAIL（ModuleNotFound）

- [ ] **Step 3: 実装** — `src/grep_analyzer/provenance.py` を新規作成:
```python
"""来歴グラフと chain 正規形（spec §9・07e81bb 明確化準拠）。単純パスのみ列挙。"""

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
        """起点（direct 相当）を登録。物理行も seed として記録。"""
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

        単純パス＝同一 Occurrence 非反復、起点以降の追跡識別子(symbol)非反復
        （spec §9・07e81bb 明確化）。max_depth はホップ数(` -> `本数)。
        循環/深さ/経路数の打ち切り＝prov_cycle_cut/prov_max_depth/prov_path_capped。
        """
        results: list[str] = []
        for seed in sorted(self._seeds):
            self._dfs(seed, target, [seed], {seed}, set(), max_depth, diag, results)
        results = sorted(set(results))
        if len(results) > max_paths:
            diag.add("prov_path_capped", f"{_hop(target)}\t{len(results)}>{max_paths}")
            results = results[:max_paths]
        return results

    def _dfs(self, node, target, path, vocc, vsym, max_depth, diag, results) -> None:
        if node == target:
            results.append(" -> ".join(_hop(o) for o in path))
            return
        if len(path) - 1 >= max_depth:
            diag.add("prov_max_depth", _hop(path[0]) + " ... " + _hop(node))
            return
        for nxt in self._adj.get(node, []):
            if nxt in vocc or nxt.symbol in vsym:
                diag.add("prov_cycle_cut", _hop(node) + " -> " + _hop(nxt))
                continue
            self._dfs(nxt, target, path + [nxt], vocc | {nxt},
                      vsym | {nxt.symbol}, max_depth, diag, results)
```

> **境界整合（Self-Review 3 串刺し）:** seed の symbol は `vsym` 初期値（空集合）に入れない＝起点 keyword は循環判定対象外（spec §9 改訂準拠）。`max_depth=1` で `KEY→A→B` は path=[KEY,A] の時 `len-1=1>=1` 真で B 前に打ち切り＝`[]`＋`prov_max_depth`。`max_depth=2` は採用。`max_depth=0` は seed 直後 `len([KEY])-1=0>=0` 真＝即打ち切り（間接ゼロ）。循環テストは target=H が `Y→X2` 再訪エッジの先にあり `X` が `vsym` 既出で `prov_cycle_cut` 発火。`test_同名keyword…` は seed symbol 非投入で `CODE@r.sh:1 -> CODE@r.sh:2` 許容。

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_provenance.py -q` → PASS（7本）／`python -m pytest -q` → 全 PASS。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/provenance.py tests/unit/test_provenance.py
git commit -m "feat(provenance): シンボル来歴グラフ＋単純パスchain（spec §9・07e81bb準拠）"
```

---

## Task 7: 共有行分類 `classify.py`

**Files:** Create `src/grep_analyzer/classify.py` / Test `tests/unit/test_classify.py`

`pipeline._classify` と同じ分類を fixedpoint からも使う。循環なし（`classify` は `classifiers/*` のみ依存）。

- [ ] **Step 1: 失敗するテストを書く** — `tests/unit/test_classify.py` を新規作成:
```python
"""共有行分類の仕様（pipeline と fixedpoint が共通利用）。"""

from grep_analyzer.classify import classify_hit


def test_ts言語はtree_sitterでhigh分類():
    # if は自分の行・正しいメソッド内（既存 test_ts_classifier/test_pipeline と同形）。
    # 不正 Java をクラス本体直下に置くと tree-sitter が ERROR ノード化し比較を取れない。
    src = "class A {\n void m(int x){\n  if (x == 1) {}\n }\n}\n"
    assert classify_hit("java", "", src, 3, "  if (x == 1) {}") == ("比較", "high")


def test_sqlとshellはmedium分類で未知はbourneフォールバック():
    assert classify_hit("sql", "", "", 1, "v := 1;") == ("代入", "medium")
    assert classify_hit("shell", "cshell", "", 1, "set X = 1") == ("代入", "medium")
    assert classify_hit("unknown", "", "", 1, "X=1") == ("代入", "medium")
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_classify.py -q` → FAIL（ModuleNotFound）

- [ ] **Step 3: 実装** — `src/grep_analyzer/classify.py` を新規作成:
```python
"""言語別行分類の共有実装（spec §7）。pipeline と fixedpoint が共通利用する。"""

from grep_analyzer.classifiers.base import ClassifyResult
from grep_analyzer.classifiers.regex_classifier import classify_shell, classify_sql
from grep_analyzer.classifiers.ts_classifier import classify_ts


def classify_hit(
    language: str, dialect: str, file_text: str, lineno: int, content: str
) -> ClassifyResult:
    """1 ヒットを言語別に分類して (category, confidence) を返す（spec §7）。

    java/c/proc は tree-sitter(high)、sql/shell は正規表現(medium)、未知は
    bourne shell フォールバック（pipeline 既存挙動と同一）。
    """
    if language in ("java", "c", "proc"):
        return classify_ts(language, file_text, lineno)
    if language == "sql":
        return classify_sql(content)
    if language == "shell":
        return classify_shell(content, dialect)
    return classify_shell(content, "bourne")
```

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_classify.py -q` → PASS（2本）／`python -m pytest -q` → 全 PASS（pipeline 未変更）。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/classify.py tests/unit/test_classify.py
git commit -m "feat(classify): pipeline/fixedpoint 共有の行分類（循環import回避）"
```

---

## Task 8: 不動点エンジン `fixedpoint.py`（intro ベース精密エッジ・一度だけ実装）

**Files:** Create `src/grep_analyzer/fixedpoint.py` / Test `tests/unit/test_fixedpoint.py`

spec §8.1 反復＋§8.3 採否＋§8.2 来歴集約を一度だけ実装。確定事項:

- **エッジは `intro` ベース**: `_ingest(parent_occ, line, hop)` で「その行から抽出した各シンボル → parent_occ」を `intro` に記録。シンボル `s` がツリー上 `child=Occurrence(s,rel,ln)` で発見されたら `intro[s]` の各 parent_occ → child へ **1 本ずつ**エッジ（spec §8.2 を実抽出元で精密化。`_parents_of` は無い＝v1/v2 偽 chain の根治）。
- seed 方言/言語は seed ファイル実読 `detect_language`/`detect_shell_dialect`（spec §5.1 決定的）。
- terminal（getter/setter）は全反復走査・全件 low 報告・**`_ingest` しない**（横展開抑止＝spec §8.3／報告全件＝spec §8.4・§8.1手順1）。
- 大域 cap: 反復先頭で採用集合サイズ超過なら `(発見ホップ,長さ,辞書順)` で恒久除外集合 `capped` へ（`chase_done` から discard しない＝spec §8.1手順5 単調増加維持）。`symbol_rejected\tcapped` 記録。
- `_ingest` で `hop>max_depth` 打ち切り時は `prov_max_depth` を fixedpoint が記録（dedup・spec §8.1手順6）。
- 走査は `_scan_file` 純関数（1 デコードで text/言語/方言/ヒット返却）。`jobs>1` は `multiprocessing.Pool`。集約は `rel` 昇順決定的。chain 確定は全エッジ集約後の単一フェーズ（走査/完了順非依存＝spec §9）。

- [ ] **Step 1: 失敗するテストを書く** — `tests/unit/test_fixedpoint.py` を新規作成:
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
    src = _mk(tmp_path, {"C.java": 'class C { static final String STATUS_OK = "S"; }\n',
                         "U.java": "class U { String x = STATUS_OK; }\n"})
    seed = _seed("STATUS_OK", "java", "C.java", 1, 'static final String STATUS_OK = "S";')
    hits = run_fixedpoint([seed], src, _opts(max_depth=1), Diagnostics())
    u = [h for h in hits if h.file == "U.java"]
    assert u and u[0].ref_kind == "indirect:constant" and u[0].via_symbol == "STATUS_OK"
    assert u[0].chain == "STATUS_OK@C.java:1 -> STATUS_OK@U.java:1"
    assert all(h.file != "C.java" for h in hits)  # seed 物理行は間接再出力しない


def test_多ホップ定数連鎖を不動点まで追い偽直結を生まない(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ static final int K1 = 1; }\n",
                         "B.java": "class B{ static final int K2 = K1; }\n",
                         "C.java": "class C{ int z2 = K2; }\n"})
    seed = _seed("K1", "java", "A.java", 1, "static final int K1 = 1;")
    hits = run_fixedpoint([seed], src, _opts(), Diagnostics())
    chains = {(h.file, h.via_symbol): h.chain for h in hits}
    assert chains[("B.java", "K1")] == "K1@A.java:1 -> K1@B.java:1"
    assert chains[("C.java", "K2")] == "K1@A.java:1 -> K1@B.java:1 -> K2@C.java:1"
    # 偽直結 K1@A.java:1 -> K2@C.java:1 は intro ベースで生成されない
    assert all(h.chain != "K1@A.java:1 -> K2@C.java:1" for h in hits)


def test_複数seedで無関係seedからの偽chainを生まない(tmp_path):
    # oracle_direct 相当: seed 2件、片方のみ v_code を導入
    src = _mk(tmp_path, {"o.sql": "v_code VARCHAR2(10);\nv_code := 'X';\n"
                                   "SELECT DECODE(st,1,'OK','NG') FROM dual;\n"})
    seeds = [_seed("X", "sql", "o.sql", 2, "v_code := 'X';"),
             _seed("X", "sql", "o.sql", 3, "SELECT DECODE(st,1,'OK','NG') FROM dual;")]
    hits = run_fixedpoint(seeds, src, _opts(), Diagnostics())
    h1 = [h for h in hits if h.file == "o.sql" and h.lineno == 1]
    assert len(h1) == 1 and h1[0].chain == "X@o.sql:2 -> v_code@o.sql:1"
    assert all("o.sql:3 -> v_code" not in h.chain for h in hits)


def test_相互参照でも有限母集合で飽和し停止する(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ static final int PP = QQ; }\n",
                         "B.java": "class B{ static final int QQ = PP; }\n"})
    seed = _seed("PP", "java", "A.java", 1, "static final int PP = QQ;")
    hits = run_fixedpoint([seed], src, _opts(max_depth=10), Diagnostics())
    assert hits and all(h.ref_kind.startswith("indirect:") for h in hits)


def test_getterは横展開せず全反復全件lowで報告し抑止記録(tmp_path):
    src = _mk(tmp_path, {
        "S.java": "class S { int count = a.getName(); }\n",
        "U.java": "class U { int v2 = count; String t2 = b.getStatus(); }\n",
        "T.java": "class T { String n = c.getName();\n String s = d.getStatus(); }\n"})
    seed = _seed("count", "java", "S.java", 1, "int count = a.getName();")
    diag = Diagnostics()
    hits = run_fixedpoint([seed], src, _opts(), diag)
    g = [h for h in hits if h.via_symbol in ("getName", "getStatus")]
    assert g and all(h.ref_kind == "indirect:getter" and h.confidence == "low" for h in g)
    assert any(h.via_symbol == "getStatus" and h.file == "T.java" for h in hits)
    d = diag.render()
    assert "getter_setter_no_expand\tgetName" in d and "getter_setter_no_expand\tgetStatus" in d


def test_jobs1とjobsNでindirectキーが完全一致し非空(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ static final int KK = 1; }\n",
                         **{f"{n}.java": f"class {n}{{ int v3 = KK; }}\n" for n in "BCDE"}})
    seed = _seed("KK", "java", "A.java", 1, "static final int KK = 1;")
    key = lambda h: (h.file, h.lineno, h.ref_kind, h.via_symbol, h.chain)
    h1 = run_fixedpoint([seed], src, _opts(jobs=1), Diagnostics())
    hN = run_fixedpoint([seed], src, _opts(jobs=4), Diagnostics())
    assert h1 and sorted(map(key, h1)) == sorted(map(key, hN))


def test_大域集合上限超過は決定的に切り捨て診断記録する(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ int aa=bb; int bb=cc; int cc=dd; int dd=1; }\n",
                         "B.java": "class B{ int zz = aa; }\n"})
    seed = _seed("aa", "java", "A.java", 1, "int aa=bb;")
    diag = Diagnostics()
    run_fixedpoint([seed], src, _opts(min_specificity=1, max_symbols=2), diag)
    assert "symbol_rejected\tcapped" in diag.render()


def test_max_depth0は間接を出さずprov_max_depthを記録(tmp_path):
    src = _mk(tmp_path, {"C.java": 'class C { static final String KK = "S"; }\n',
                         "U.java": "class U { String x = KK; }\n"})
    seed = _seed("KK", "java", "C.java", 1, 'static final String KK = "S";')
    diag = Diagnostics()
    assert run_fixedpoint([seed], src, _opts(max_depth=0), diag) == []
    assert "prov_max_depth" in diag.render()
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_fixedpoint.py -q` → FAIL（ModuleNotFound）

- [ ] **Step 3: 実装** — `src/grep_analyzer/fixedpoint.py` を新規作成:
```python
"""不動点・ターゲットスキャン・エンジン（spec §8.1/§8.2/§8.3）。

direct ヒットを seed に constant/var を多ホップ追跡し indirect ヒットと chain を
出す。getter/setter は §8.3 で横展開しないが全反復走査・全件 low 報告(§8.4)。
来歴エッジは intro(実抽出元 Occurrence)ベース＝spec §8.2 を精密化(偽 chain 根治)。
出力は走査順・並列完了順に非依存で決定的(spec §9)。

停止性(spec §8.1 手順5): 追跡シンボルは原ソース字句のみ。母集合有限・採用集合
単調増加(chase_done から削らない＝cap は capped で scan 除外のみ)。よって高々
|母集合| ステップで飽和。--max-depth/max_symbols/max_paths は安全弁。
"""

import multiprocessing
from dataclasses import dataclass
from pathlib import Path

from grep_analyzer import automaton, walk
from grep_analyzer.chase import extract_chase_symbols
from grep_analyzer.classify import classify_hit
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.dispatch import detect_language, detect_shell_dialect
from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes
from grep_analyzer.model import Hit
from grep_analyzer.provenance import Occurrence, ProvenanceGraph
from grep_analyzer.stoplist import SymbolPolicy, load_stoplist, partition


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
    """1 ファイルを走査しヒット素片を返す純関数（並列ワーカ・picklable のみ）。

    automaton 走査は raw 行（spec 解釈の明示・マスク非対称根拠）。
    """
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

    intro: dict[str, list[Occurrence]] = {}   # symbol -> 実抽出元 Occurrence 群
    sym_kind: dict[str, str] = {}
    sym_hop: dict[str, int] = {}
    edges: list[tuple[Occurrence, Occurrence]] = []
    chase_active: set[str] = set()
    chase_done: set[str] = set()
    term_active: set[str] = set()
    term_done: set[str] = set()
    capped: set[str] = set()
    no_expand_logged: set[str] = set()
    replaced_logged: set[str] = set()
    maxdepth_logged: set[Occurrence] = set()

    def _ingest(parent: Occurrence, language: str, dialect: str, line: str,
                hop: int, is_seed: bool = False):
        if hop > opts.max_depth:
            if parent not in maxdepth_logged:
                diag.add("prov_max_depth", f"{parent.symbol}@{parent.relpath}:"
                         f"{parent.lineno} (hop {hop} > --max-depth {opts.max_depth})")
                maxdepth_logged.add(parent)
            return
        cs = extract_chase_symbols(language, dialect, line)
        kinds = _kinds_of(language, dialect, line)
        part = partition(cs, language, policy)
        for sym, reason in sorted(part.rejected):
            diag.add("symbol_rejected", f"{reason}\t{sym}")
        for sym in part.chase:
            if sym in capped:
                continue
            # 非 seed の自己定義行が自分自身を再抽出しても発見元ではない
            # （spec §8.2「発見元≠発見」）。seed は keyword 原点なので例外。
            if not is_seed and sym == parent.symbol:
                continue
            sym_kind.setdefault(sym, kinds.get(sym, "var"))
            sym_hop.setdefault(sym, hop)
            lst = intro.setdefault(sym, [])
            if parent not in lst:
                lst.append(parent)
            if sym not in chase_done:
                chase_active.add(sym)
        for sym in part.terminal:
            if sym in capped:
                continue
            if not is_seed and sym == parent.symbol:
                continue
            sym_kind.setdefault(sym, kinds.get(sym, "getter"))
            sym_hop.setdefault(sym, hop)
            lst = intro.setdefault(sym, [])
            if parent not in lst:
                lst.append(parent)
            if sym not in term_done:
                term_active.add(sym)

    # hop0→hop1: seed ファイル実読で spec §5.1 決定的に言語/方言確定
    for s in seed_hits:
        occ = Occurrence(s.keyword, s.file, s.lineno)
        graph.add_seed(occ)
        sp = source_root / s.file
        if sp.is_file():
            _, _, _, lang, dia = _file_meta(s.file, sp.read_bytes(), opts.lang_map)
        else:
            lang, dia = s.language, "bourne"
        _ingest(occ, lang, dia, s.snippet, hop=1, is_seed=True)

    files: list[tuple[str, bytes]] = [
        (rel, abspath.read_bytes())
        for rel, abspath in walk.walk_files(
            source_root, include=opts.include, exclude=opts.exclude,
            follow_symlinks=opts.follow_symlinks,
            max_file_bytes=opts.max_file_bytes, diag=diag)]

    def _apply_global_cap():
        live = sorted(chase_active | chase_done | term_active | term_done,
                      key=lambda s: (sym_hop.get(s, 0), len(s), s))
        if len(live) <= opts.max_symbols:
            return
        for s in live[opts.max_symbols:]:
            if s not in capped:
                diag.add("symbol_rejected", f"capped\t{s}")
                capped.add(s)
            chase_active.discard(s)
            term_active.discard(s)  # chase_done は単調維持・scan は capped で除外

    enc_of: dict[str, tuple[str, bool]] = {}
    hop = 1
    while chase_active or term_active:
        _apply_global_cap()
        scan_chase = {s for s in chase_active if s not in capped}
        scan_term = {s for s in term_active if s not in capped}
        scan_syms = sorted(scan_chase | scan_term)
        chase_done |= chase_active
        chase_active = set()
        term_done |= term_active
        term_active = set()
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
            for sym, i, line in found:
                if sym not in scan_chase and sym not in scan_term:
                    continue
                child = Occurrence(sym, rel, i)
                for parent in intro.get(sym, []):
                    if parent != child:
                        edges.append((parent, child))
                if sym in scan_term:
                    if sym not in no_expand_logged:
                        diag.add("getter_setter_no_expand", sym)
                        no_expand_logged.add(sym)
                    continue  # 横展開しない（spec §8.3 生命線）
                _ingest(child, language, dialect, line, hop + 1)
        hop += 1

    for p, c in edges:
        graph.add_edge(p, c)

    indirect: list[Hit] = []
    seen: set[Occurrence] = set()
    line_cache: dict[str, list[str]] = {}
    meta_of: dict[str, tuple[str, str, str]] = {}
    raw_of = dict(files)
    for _, c in sorted(set(edges)):
        if c in seen or c.symbol not in (chase_done | term_done):
            continue
        if graph.is_seed_location(c.relpath, c.lineno):
            continue  # direct 既出
        seen.add(c)
        if c.relpath not in line_cache:
            raw = raw_of.get(c.relpath, b"")
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
        for chain in graph.chains_to(c, max_depth=opts.max_depth,
                                     max_paths=opts.max_paths, diag=diag):
            indirect.append(Hit(
                keyword=keyword, language=language, file=c.relpath, lineno=c.lineno,
                ref_kind=_REF_KIND[kind], category=cat, category_sub="",
                usage_summary=f"{cat} ({language})", via_symbol=c.symbol,
                chain=chain, snippet=line,
                encoding=enc + (" 要確認" if replaced else ""), confidence=conf))
    return indirect
```

> **実装注（次レビュー重点・3巡目反映）:** エッジは `intro[s]`（s を実際に抽出した parent_occ 群）→ 発見 child のみ。seed 行が s を抽出した場合のみ当該 seed occ が親（全 seed 無条件親化＝v1/v2 偽 chain を根治）。hop≥2 は s を抽出した child occ が親。**`_ingest` の `is_seed`**: 非 seed 親の自己定義行が自分自身（`sym == parent.symbol`）を再抽出しても発見元にしない（spec §8.2「発見元≠発見」。3巡目 R1-High2 の intro 自己汚染を根治。seed は keyword 原点なので例外＝`is_seed=True` で自身を intro に登録し tree 出現を seed に連結）。`provenance` の追跡シンボル単純パス（spec §9・07e81bb）が定数循環 A→B→A を `prov_cycle_cut` で打ち切り＝有限・決定的。`seen` は Occurrence 単位（異なる単純パスは `chains_to` が経路別 chain＝spec §9 重複許容）。`is_seed_location` で seed 物理行を間接除外（keyword≠シンボル名でも seed 行を再出力しない）。`_file_meta` 単一デコード＋`line_cache`/`meta_of`/`raw_of` キャッシュで再 I/O ゼロ。`hop>max_depth` 打ち切りは `prov_max_depth` 記録（dedup・spec §8.1手順6＝`8c21227`/`07e81bb` と同様 spec 本体準拠）＝Task10 が `--max-depth` で必ず観測可能。`chains_to` 側も経路長超過で `prov_max_depth` を記録しうるが両者とも決定的順序で発火し2回実行一致は不変（詳細件数の縮約は spec §10.3＝Phase 3）。**cap 単調性**: `sym_hop` は `setdefault` で初出 hop に固定＝`_apply_global_cap` の `(sym_hop,len,sym)` ソート順は sym 確定後不変＝一度 capped は恒久・未 capped の遅延 capped 化はあっても再活性化しない（spec §8.1手順5 単調・停止性不変）。**getter テストの U.java の `count`/`v2`/`t2` は constant/var として正規に横展開され `indirect:var` 行も出る**（getter 非展開と var 展開は独立。`test_getterは…` は getter のみ assert）。terminal(getter/setter) は `continue` で _ingest しない＝出ていく辺を持たない chain 末端ノードなので、`provenance._dfs` の `vsym` に入っても同名 getter 全件報告（spec §8.4）は損なわれない（同名 getter は別 target として各々 `chains_to` され、単一経路内に二度現れない）。

- [ ] **Step 4: テストが通る（当該＋全体回帰ゼロ）**

Run: `python -m pytest tests/unit/test_fixedpoint.py -q`
Expected: PASS（8本）。`test_相互参照…` がタイムアウトせず PASS（停止性実測）。`test_多ホップ…偽直結を生まない`／`test_複数seedで無関係seedからの偽chain…` が PASS（intro エッジの正しさ）。

Run: `python -m pytest -q` → 全 PASS・0 failed/0 error。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/fixedpoint.py tests/unit/test_fixedpoint.py
git commit -m "feat(fixedpoint): introベース精密エッジ＋多ホップ不動点＋getter全件＋jobs決定的＋大域cap（spec §8.1/§8.2/§8.3）"
```

---

## Task 9: パイプライン配線と CLI（`--lang-map` 対称・pipeline.py 全文）

**Files:** Modify `src/grep_analyzer/pipeline.py`（全文置換）/ Modify `src/grep_analyzer/cli.py` / Test `tests/integration/test_pipeline_fixedpoint.py`

direct 生成後に `run_fixedpoint` を呼び indirect 併合、`write_tsv`（既存 `model.sort_key`）で安定化。`classify.classify_hit` 委譲。`lang_map` を direct/indirect 同一で配線（spec §5.1/§10.4）。既存 `run` 呼び出し元はキーワード引数のため `opts=None` 既定で後方互換。

- [ ] **Step 1: 失敗するテストを書く** — `tests/integration/test_pipeline_fixedpoint.py` を新規作成:
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
    src, inp = _setup(tmp_path,
        {"C.java": 'class C { static final String STATUS_OK = "S"; }\n',
         "U.java": "class U { String x = STATUS_OK; }\n"},
        'C.java:1:static final String STATUS_OK = "S";\n', "STATUS_OK")
    o1, o2 = tmp_path / "o1", tmp_path / "o2"
    assert main(["--input", str(inp), "--output", str(o1), "--source-root", str(src)]) == 0
    main(["--input", str(inp), "--output", str(o2), "--source-root", str(src)])
    a = (o1 / "STATUS_OK.tsv").read_text("utf-8-sig")
    cols = a.splitlines()[0].split("\t")
    rows = [dict(zip(cols, ln.split("\t"))) for ln in a.splitlines()[1:]]
    kinds = {r["file"]: r["ref_kind"] for r in rows}
    assert kinds["C.java"] == "direct" and kinds["U.java"] == "indirect:constant"
    assert a == (o2 / "STATUS_OK.tsv").read_text("utf-8-sig")


def test_max_depth0は間接追跡せずdirectのみ(tmp_path: Path):
    src, inp = _setup(tmp_path,
        {"C.java": 'class C { static final String STATUS_OK = "S"; }\n',
         "U.java": "class U { String x = STATUS_OK; }\n"},
        'C.java:1:static final String STATUS_OK = "S";\n', "STATUS_OK")
    o = tmp_path / "o"
    main(["--input", str(inp), "--output", str(o), "--source-root", str(src), "--max-depth", "0"])
    rows = (o / "STATUS_OK.tsv").read_text("utf-8-sig").splitlines()[1:]
    assert rows and all("\tdirect\t" in r for r in rows)


def test_lang_mapはdirectとindirectで対称に効く(tmp_path: Path):
    src, inp = _setup(tmp_path,
        {"C.inc": 'class C { static final String STATUS_OK = "S"; }\n',
         "U.inc": "class U { String x = STATUS_OK; }\n"},
        'C.inc:1:static final String STATUS_OK = "S";\n', "STATUS_OK")
    o = tmp_path / "o"
    main(["--input", str(inp), "--output", str(o), "--source-root", str(src),
          "--lang-map", ".inc=java"])
    a = (o / "STATUS_OK.tsv").read_text("utf-8-sig")
    cols = a.splitlines()[0].split("\t")
    rows = [dict(zip(cols, ln.split("\t"))) for ln in a.splitlines()[1:]]
    assert all(r["language"] == "java" for r in rows)
    assert any(r["ref_kind"] == "indirect:constant" for r in rows)
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/integration/test_pipeline_fixedpoint.py -q` → FAIL（未知引数 or 間接行なし）

- [ ] **Step 3: 実装** — `src/grep_analyzer/pipeline.py` を**全文置換**（既存 Phase 1.5 ロジックを保持しつつ classify 委譲・lang_map・不動点併合を統合。`...` プレースホルダなし）:
```python
"""direct＋不動点 indirect 併合パイプライン（spec §15 フェーズ2 Phase 2a）。"""

from pathlib import Path

from grep_analyzer.classify import classify_hit
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.dispatch import (
    detect_language,
    detect_shell_dialect,
    extension_resolves_language,
    shebang_dialect,
)
from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes
from grep_analyzer.fixedpoint import EngineOptions, run_fixedpoint
from grep_analyzer.ingest import parse_grep_line
from grep_analyzer.model import Hit
from grep_analyzer.tsv import write_tsv
from grep_analyzer.walk import DEFAULT_EXCLUDE


def _default_opts() -> EngineOptions:
    return EngineOptions(
        max_depth=10, min_specificity=2, stoplist_path=None, lang_map={},
        include=[], exclude=list(DEFAULT_EXCLUDE), jobs=1, follow_symlinks=False,
        max_file_bytes=5_000_000, max_symbols=100_000, max_paths=1000)


def run(
    input_dir: Path, output_dir: Path, source_root: Path,
    opts: EngineOptions | None = None,
) -> int:
    """input/*.grep を処理し、direct＋不動点 indirect を併合した TSV を出力する。"""
    diag = Diagnostics()
    output_dir.mkdir(parents=True, exist_ok=True)
    if opts is None:
        opts = _default_opts()
    lang_map = opts.lang_map

    for grep_file in sorted(Path(input_dir).glob("*.grep")):
        keyword = grep_file.stem
        text, _, _ = decode_bytes(grep_file.read_bytes(), DEFAULT_FALLBACK)
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
            sample = file_text[:4096]
            language = detect_language(rel, sample, lang_map)
            dialect = detect_shell_dialect(rel, sample) if language == "shell" else "bourne"
            if (
                not extension_resolves_language(rel, lang_map)
                and language != "shell"
                and shebang_dialect(sample) == "other"
            ):
                diag.add("unsupported_shebang", str(rel))
            category, confidence = classify_hit(language, dialect, file_text, lineno, content)
            hits.append(Hit(
                keyword=keyword, language=language, file=rel, lineno=lineno,
                ref_kind="direct", category=category, category_sub="",
                usage_summary=f"{category} ({language})", via_symbol="",
                chain=f"{keyword}@{rel}:{lineno}", snippet=content,
                encoding=enc + (" 要確認" if replaced else ""), confidence=confidence,
            ))

        indirect = run_fixedpoint(hits, Path(source_root), opts, diag)
        write_tsv(output_dir / f"{keyword}.tsv", hits + indirect, "utf-8-sig")

    (output_dir / "diagnostics.txt").write_text(diag.render(), encoding="utf-8")
    return 0
```
> 注: 上記は Phase 1.5 `pipeline.py` の grep 行ループ本体を**逐語保持**し、差分は (a) `classify` 委譲・`_classify` 削除、(b) `detect_language`/`extension_resolves_language` 第3引数を `lang_map`、(c) ループ後 `run_fixedpoint`＋`write_tsv(hits+indirect)`、(d) `EngineOptions` 既定。`write_tsv` は既存 `model.sort_key` 全順序安定ソートで direct/indirect 混在も決定的（spec §9）。

`src/grep_analyzer/cli.py` を編集（Phase 2a オプション・`--lang-map`）:
```python
import argparse
from pathlib import Path

from grep_analyzer.fixedpoint import EngineOptions
from grep_analyzer.pipeline import run
from grep_analyzer.walk import DEFAULT_EXCLUDE


def _parse_lang_map(spec: str | None) -> dict[str, str]:
    """`.ext=lang,.e2=l2` を {".ext":"lang"} に。空は {}（spec §10.4/§5.1手順1）。"""
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

- [ ] **Step 4: テストが通る（当該＋全体回帰）**

Run: `python -m pytest tests/integration/test_pipeline_fixedpoint.py -q` → PASS（3本）

Run: `python -m pytest -q`
Expected: **`tests/golden` の `shell_direct` と `oracle_direct` のみ FAIL**（想定どおり）。`test_pipeline.py`/`test_pipeline_dialect.py`/他8 golden/smoke は **PASS**。**ここで commit しない**（Task 11 で golden 確定後に全緑へ戻す）。FAIL が 2 件以外なら**停止し構造を疑う**（writing-tests）。

> **既存 golden 影響の確定（v3・seed行除外＋intro エッジで再検証済）:**
> - **shell_direct（変化）**: `run.sh:1 CODE="X"`→var `CODE`。`run.sh:2 echo "$CODE"` の `$CODE`（非seed行）＝`indirect:var` 1 行増（chain `CODE@run.sh:1 -> CODE@run.sh:2`）。
> - **oracle_direct（変化）**: seed 2件（o.sql:2/3）。`v_code` は **o.sql:2 のみ**が intro（`v_code := 'X';`）。o.sql:3（`SELECT DECODE…`）は v_code を抽出しないため親にならない＝偽行を生まない。`o.sql:1 v_code VARCHAR2(10);`（非seed行）＝`indirect:var` **1 行**増（chain `X@o.sql:2 -> v_code@o.sql:1`）。
> - **不変（8件）**: java_direct（STATUS_OK 出現は seed 行 2/4 のみ＝is_seed_location 除外）、c_direct（CODE は seed 行のみ）、proc_direct（`p` は too_short）、sql_direct（chase 空）、**csh_direct（seed が run.csh:1+2 の両方＝`$CODE` 出現行 run.csh:2 が seed 物理行で is_seed_location 除外。shell_direct は seed が run.sh:1 のみ＝run.sh:2 が非 seed で 1 行増、の差。両者の差分理由を明示）**、csh_noext_shebang/sh_noext_shebang（CODE 出現は seed 行のみ）、encoding_utf8（`コード` は ASCII 開始でなく抽出されない＝v1 既知の ASCII 識別子限界）。

- [ ] **Step 5: コミット（golden 含まず・Task11 と連続実施）**
```bash
git add src/grep_analyzer/pipeline.py src/grep_analyzer/cli.py tests/integration/test_pipeline_fixedpoint.py
git commit -m "feat(pipeline): direct＋不動点併合配線＋--lang-map対称＋CLI（spec §8/§10.4）"
```
> 注: この時点で pytest は 2 golden が赤。**Task 9→10→11 を中断なく進め Task 11 完了時に全緑へ戻す**。Task 9 単独で完了主張・レビュー差し戻しをしないこと（verification-before-completion はフェーズ完了＝Task 12 で確認）。

---

## Task 10: §8.4 診断の正本（全件性・決定性の契約）

**Files:** Test `tests/integration/test_diagnostics_phase2.py`

spec §8.4「唯一の正本」。横展開抑止／集合上限切り捨て（全件）／生成コード除外／max-depth 到達／getter 全件報告／**diagnostics の決定性（2 回実行で同一）**を契約化。`prov_max_depth` は fixedpoint が `hop>max_depth` で記録するため `--max-depth` 指定で必ず観測可能（v2 の構造的不能を解消）。

- [ ] **Step 1: 失敗するテストを書く** — `tests/integration/test_diagnostics_phase2.py` を新規作成:
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
    main(["--input", str(inp), "--output", str(out), "--source-root", str(src)] + (extra or []))
    return (out / "diagnostics.txt").read_text("utf-8")


def test_複数getterが全件抑止記録される(tmp_path: Path):
    d = _run(tmp_path,
             {"S.java": "class S{ int vv = a.getName(); String ww = b.getCode(); }\n",
              "T.java": "class T{ String n = c.getName(); String m = d.getCode(); }\n"},
             "S.java:1:int vv = a.getName();\n", "vv")
    assert "getter_setter_no_expand\tgetName" in d and "getter_setter_no_expand\tgetCode" in d


def test_集合上限切り捨てが記録される(tmp_path: Path):
    d = _run(tmp_path,
             {"A.java": "class A{ int aa=bb; int bb=cc; int cc=1; }\n",
              "B.java": "class B{ int zz=aa; }\n"},
             "A.java:1:int aa=bb;\n", "aa",
             extra=["--max-symbols", "1", "--min-specificity", "1"])
    assert "symbol_rejected\tcapped" in d


def test_生成コード除外とmax_depth到達が記録される(tmp_path: Path):
    d = _run(tmp_path,
             {"build/Gen.java": "class Gen{ String x = STATUS_OK; }\n",
              "K.java": 'class K{ static final String STATUS_OK="S"; }\n',
              "L.java": "class L{ String yy = STATUS_OK; String zz = yy; }\n"},
             'K.java:1:static final String STATUS_OK="S";\n', "STATUS_OK",
             extra=["--max-depth", "1"])
    assert "walk_excluded\tbuild/Gen.java" in d
    assert "prov_max_depth" in d   # hop2 ingest が --max-depth 1 で打ち切り→fixedpoint 記録


def test_diagnosticsは2回実行で完全一致の決定的(tmp_path: Path):
    files = {"A.java": "class A{ static final int KK=1; }\n",
             **{f"{n}.java": f"class {n}{{ int vv=KK; }}\n" for n in "BCDEF"}}
    d1 = _run(tmp_path, files, "A.java:1:static final int KK=1;\n", "KK", outname="r1")
    d2 = _run(tmp_path, files, "A.java:1:static final int KK=1;\n", "KK", outname="r2")
    assert d1 == d2
```

- [ ] **Step 2: 失敗を確認 → 必要なら最小修正**

Run: `python -m pytest tests/integration/test_diagnostics_phase2.py -q`
Expected: 基本 PASS（各診断は Task 8 で決定的集約・`sorted` 呼び出し済。`prov_max_depth` は `_ingest` の hop>max_depth 記録で `--max-depth 1` でも発火）。FAIL する契約があれば該当 `diag.add` を決定的順序で最小追加（テストは緩めない）。

- [ ] **Step 3: 全体回帰（golden 除く）** — `python -m pytest -q --ignore=tests/golden` → 全 PASS。

- [ ] **Step 4: コミット**
```bash
git add tests/integration/test_diagnostics_phase2.py src/grep_analyzer/
git commit -m "test(diagnostics): §8.4 正本の全件性・決定性契約を固定（spec §8.4）"
```

---

## Task 11: golden（既存2件の意図 regen＋多ホップ代表）

**Files:** Modify `tests/golden/cases/shell_direct/expected/CODE.tsv`・`.../oracle_direct/expected/X.tsv` / Create `indirect_constant`・`indirect_var_shell`・`chain_multipath`・`getter_no_expand` 各ケース

spec §11 必須回帰: 汎用 getter 横展開抑止／chain 複数経路の決定性（真ダイヤモンド・別行）／indirect:constant・var 網羅。`category_sub` 空固定。symlink 重複排除は unit `test_walk.py` 担保（conftest で symlink 生成は過剰結合＝層の縄張り。golden は決定性最終形＝spec §11 文言と整合）。`tests/golden/conftest.py` 無改変（`cases/*/` 自動 parametrize）。**全期待 TSV は実エンジン生成→git diff 目視レビュー後に確定**（writing-tests Golden「反射的 regen は alarm を殺す」）。

- [ ] **Step 1: 既存 2 件の変化を目視 regen**

Run: `python -m pytest tests/golden -q`
Expected: `shell_direct`/`oracle_direct` のみ FAIL（Task 9 想定どおり）。他8 PASS。**2 件以外が FAIL なら停止し構造を疑う**。

```bash
for c in shell_direct oracle_direct; do
  python -m grep_analyzer --input tests/golden/cases/$c/input \
    --output tests/golden/cases/$c/expected --source-root tests/golden/cases/$c/src
done
rm -f tests/golden/cases/*/expected/diagnostics.txt
git diff tests/golden/cases/shell_direct tests/golden/cases/oracle_direct
```
**目視確認**:
- `shell_direct/expected/CODE.tsv`: 既存 direct(run.sh:1) 不変＋新規 `run.sh\t2\tindirect:var\t…\tCODE\tCODE@run.sh:1 -> CODE@run.sh:2\techo "$CODE"\t…`（1 行のみ）。
- `oracle_direct/expected/X.tsv`: 既存 direct 2 行(o.sql:2/3) 不変＋新規 `o.sql\t1\tindirect:var\t…\tv_code\tX@o.sql:2 -> v_code@o.sql:1\tv_code VARCHAR2(10);\t…`（**1 行のみ**＝intro エッジで偽 `X@o.sql:3 -> v_code` は出ない）。
- 他8 golden は `git diff` に出ない。出たら停止し構造を疑う。

- [ ] **Step 2: 多ホップ代表ケースの src/input を作る（識別子は全て ≥2 文字＝既定 min_specificity=2）**

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

`chain_multipath`（真ダイヤモンド＝同一ヒット `HUB@D.java:1` へ 2 単純パス）:
`chain_multipath/src/A.java`: `class A { static final int KSEED = 9; }`
`chain_multipath/src/B.java`: `class B { static final int HUB = KSEED; }`
`chain_multipath/src/C.java`: `class C { static final int HUB = KSEED; }`
`chain_multipath/src/D.java`: `class D { void run(){ check(HUB); } }`
`chain_multipath/input/KSEED.grep`: `A.java:1:static final int KSEED = 9;`
（D は `check(HUB)`＝代入でない HUB 利用にし `use` var 抽出を排す＝3巡目 R1/R3-H1 の `use@D` ノイズ行を消し golden を「HUB@D 2経路」固定に純化。KSEED→(B/C 行で HUB 抽出)→HUB の 2 経路で `HUB@D.java:1` へ到達＝**2 chain 行が spec §11 chain 複数経路決定性の固定点**。B.java:1/C.java:1 は同一物理行に KSEED と HUB の両トークンが在り、KSEED 出現（KSEED 経由 indirect:constant 1 行）＋HUB 出現（2 経路 2 行）＝各 3 行出るのも決定的に正しい＝Step3 で全行を目視確定）

`getter_no_expand/src/S.java`: `class S { int vv = a.getName(); }`
`getter_no_expand/src/T.java`:
```java
class T { String n = b.getName();
 String m = c.getName(); }
```
`getter_no_expand/input/vv.grep`: `S.java:1:int vv = a.getName();`

- [ ] **Step 3: 期待 TSV を生成（必ず全行を目視レビュー）**

```bash
for c in indirect_constant indirect_var_shell chain_multipath getter_no_expand; do
  python -m grep_analyzer --input tests/golden/cases/$c/input \
    --output tests/golden/cases/$c/expected --source-root tests/golden/cases/$c/src
done
rm -f tests/golden/cases/*/expected/diagnostics.txt
git diff --stat tests/golden/cases/
```
**目視確認（全行を確認。想定外行が出たら停止し構造を疑う）**:
- `indirect_constant`: direct `C.java:1`＋`U.java:1 indirect:constant via STATUS_OK chain "STATUS_OK@C.java:1 -> STATUS_OK@U.java:1"`、`category_sub` 空。
- `indirect_var_shell`: direct `run.sh:1`＋`run.sh:2 indirect:var`＋`other.sh:1 indirect:var`（`$CODE`）。
- `chain_multipath`: **ヘッダ除き厳密に 9 行**（決定的・2回実行一致。9 行以外なら停止し構造を疑う）。内訳:
  - `A.java:1` direct（keyword=KSEED の seed 行）×1
  - `B.java:1`: via=KSEED の indirect:constant ×1（chain `KSEED@A.java:1 -> KSEED@B.java:1`）＋ via=HUB の indirect:constant ×2（chain `KSEED@A.java:1 -> KSEED@B.java:1 -> HUB@B.java:1` と `… -> KSEED@C.java:1 -> HUB@B.java:1`）＝計3行
  - `C.java:1`: 同様に via=KSEED ×1＋via=HUB ×2＝計3行
  - `D.java:1`: via=HUB の indirect:constant **×2**（`KSEED@A.java:1 -> KSEED@B.java:1 -> HUB@D.java:1` と `KSEED@A.java:1 -> KSEED@C.java:1 -> HUB@D.java:1`・決定的順）＝**spec §11「chain 複数経路の決定性」の固定点**
  - `use` 由来行は出ない（D は `check(HUB)` で代入なし）。`HUB@{B,C}:1->HUB@*` 偽エッジは `_ingest` の `is_seed` 自己抽出抑止＋`provenance` 追跡シンボル単純パスで生成・残存しない。
- `getter_no_expand`: direct `S.java:1`（keyword=`vv` len2≥2＝`vv` は chase 投入されるが S.java 以外に出現せず S.java:1 は seed 物理行で除外＝間接ゼロ）。`T.java:1`/`T.java:2` に `getName` が `indirect:getter`・`confidence=low`（chain `vv@S.java:1 -> getName@T.java:1`/`…:2`）、`getName` から先のシンボルは出ない（横展開なし）。category は tree-sitter の対象行依存で決定的（生成値で固定＝目視のみ）。
- 既存8不変・Step1 の2件は意図変化のみ。

- [ ] **Step 4: golden 全緑＋全体回帰ゼロ**

Run: `python -m pytest tests/golden -q` → 全 PASS（既存10〔2件意図 regen 済〕＋新規4＝14 ケース）。
Run: `python -m pytest -q` → 全 PASS・**0 failed/0 error**（Task 9 の赤が解消）。

- [ ] **Step 5: コミット（golden 規約）**
```bash
git add tests/golden/cases/
git commit -m "chore(golden): Phase2 間接の既存2件意図regen＋多ホップ代表4ケース（spec §11）"
```

---

## Task 12: Phase 2a 全テスト緑化と完了確認

**Files:** Modify `docs/superpowers/plans/phase0-gate-result.md`

- [ ] **Step 1: 全テスト実行** — `cd /workspaces/grep_helpers2 && python -m pytest -q` → 全 PASS（78＋Phase 2a 追加分。0 failed/0 error）。失敗あれば該当 Task に戻る（完了主張しない）。

- [ ] **Step 2: spec §8/§9/§15・ref_kind×言語表 充足チェックリスト照合**

- §8.1 反復・停止性 → Task8（`test_相互参照…飽和し停止`）
- §8.1 手順1 Pro\*C ホスト変数 非投入 → Task1（`test_C定義…ProCホスト変数は追跡投入しない`）
- §8.3 採否・getter/setter 非投入・**大域**決定的切り捨て → Task2/3/8（`test_大域集合上限…`）
- §8.2 来歴集約（intro 精密エッジ）・jobs 並列決定性 → Task8（`test_多ホップ…偽直結を生まない`/`test_複数seedで無関係seedからの偽chain…`/`test_jobs1とjobsN…`）
- §8.2 走査・symlink 重複排除・生成コード除外 → Task5
- §9 chain 正規形（07e81bb 明確化）・真の複数経路の別行決定性 → Task6/11（`chain_multipath` の `HUB@D.java:1` 2 行）
- §9 ref_kind×言語表 全6言語×4 kind の許容/禁止セル → Task1 負の契約（SQL/cshell/C は getters/setters 空、proc は getter/setter 空かつホスト変数非投入）＋ golden の言語別 ref_kind 点検
- §8.4 診断正本（全件性・決定性）→ Task10
- §5.1 lang_map direct/indirect 対称 → Task9（`test_lang_mapは…対称に効く`）
- direct/indirect 併合の完全決定性 → Task9（2 回一致）＋既存8 golden 不変＋2件意図 regen

- [ ] **Step 3: 完了記録を追記しコミット**

`phase0-gate-result.md` 末尾に「## Phase 2a 完了記録」（完了日 UTC、コミット範囲、全テスト結果、上記対応表、spec §9 を `07e81bb` で明確化した旨、既存 golden 2 件を Phase2 間接で意図 regen した理由、Phase 2b/3 申し送り＝「境界」要約）を追記。

```bash
git add docs/superpowers/plans/phase0-gate-result.md
git commit -m "chore: Phase 2a 完了（不動点エンジン正しさ・決定性コア）"
```

---

## Phase 2a の境界（2b / Phase 3 は別計画・spec §15 根拠付き正当化）

**spec §15 整合の正当化:** spec §15 フェーズ2 は §8.1/§8.3/§8.2 を一体記載するが、§15 自身が「決定性基盤を間接追跡より先に固める」「単一実装計画は非現実的」と明記し Phase 1→1.5 も同思想で分割済。§8.2 のうち決定性に不可分な来歴集約・jobs 並列決定性は 2a、決定性確立を前提とする資源 degrade は 2b。spec 必須要件の恒久欠落ではなく後続フェーズへの分割。Phase 2a 単体は小規模で degrade 不要・テスト可能・出荷可能。**2b のストリーミング化は決定的集約フェーズ（`sorted(results, key=rel)`・全エッジ集約後 chain 計算）の契約を不変に保つ＝Phase 2a golden は走査メモリ方式非依存**（spec §9「走査順非依存」の明示的継承。将来 golden churn を予防）。論拠: ストリーミング化後も `intro`/`edges` の**最終集合**は走査順非依存（`automaton.scan_line` 昇順・`sorted(set(edges))`・`chains_to` が集合のみ依存）であり、走査メモリ方式は最終集合に影響しない。

- **Phase 2b に送る**: §8.2 資源 degrade（`--memory-limit` 超過時の来歴グラフ・ディスクスピル、優先順位＝決定的シンボル切り捨て→スピル→オートマトン分割多パス・最大走査パス上限）、任意 `ripgrep` 一次粗フィルタ（`@pytest.mark.requires_ripgrep` 隔離）、差分走査の限定効果、**chain 経路数の指数爆発に対する degrade**（Phase 2a は `max_paths` 安全弁＋小規模前提）、**全 bytes 親常駐のストリーミング化**（Phase 2a は `files` に bytes 常駐＝正しさ・決定性のみ責務）、**キーワード横断の walk 診断重複の集約**（pipeline が keyword ごとに `run_fixedpoint` を呼ぶため。spec §10.3 縮約と併せ Phase 3）。
- **Phase 3 に送る**: 60GB perf ベースライン、`--resume`、diagnostics 上限縮約（spec §10.3）、規模分割 `<keyword>.partNN.tsv`（spec §9）、`requirements.lock`（spec §4.1・ユーザ決定で Phase 3）、`--output-encoding`/`--encoding-fallback`（spec §10.1 正本だが decode は Phase 1.5 確立済 `DEFAULT_FALLBACK`・出力 encoding 変更は規模/運用＝Phase 3。`--use-ripgrep`/`--memory-limit`/`--progress` は 2b）。
- **getter terminal の報告量 vs PRD（リスク開示）**: getter/setter は spec §8.4「同名メソッド**全件** low」準拠で報告件数に上限を設けない。汎用 getter（`getName` 等）が大規模ツリーで多数 low 行を生み PRD「目視削減」と緊張しうる。Phase 2a は `--min-specificity`/`--stoplist` 運用で緩和し、報告量の degrade（頻出 getter の動的抑止）は spec §14＋Phase 2b。Phase 2a の `getter_no_expand` golden は最小ケースで爆発を再現しない（spec §8.4 準拠を固定するのみ）＝この緊張は既知・開示済。
- **diagnostics を golden 完全一致対象から除外（`rm -f`）する判断**: diagnostics に実行環境依存要素が混じると golden が脆くなるトレードオフ回避。代替として Task10 integration が §8.4 正本性（`getter_setter_no_expand`/`symbol_rejected`/`prov_*` の存在＋2回実行 byte 一致）を担保＝spec §8.4「唯一の正本」の回帰保護を golden 喪失分まで補填する設計判断（spec §8.4/§11 と整合）。
- **Phase 2a の既知境界（spec 引用付き・誤検出でなく仕様固定）**: (1) 字句正規表現抽出（tree-sitter 型解決はしない＝spec §8.3 前提どおり。精度は handcrafted の領分＝非ゲート）。(2) ASCII 識別子前提（`encoding_utf8` の非 ASCII 識別子は v1 で追跡しない＝spec §8.2 識別子境界の v1 既知境界。golden で固定）。(3) 意味的同一性（別ファイルの同名定数が別実体か）は型解決不能のため human 判断＝spec §8.4 正本に従う既知近似（v3/v4 の intro 精密エッジ＋`is_seed` 自己抽出抑止で偽直結・自己汚染は排除）。(4) マスク非対称（抽出=マスク／走査=raw）は意図的設計（冒頭「spec 解釈の明示」に §7+§8 根拠明記）。(5) Java/C 文字列・コメント内の静的シンボル言及のヒット化は字句ツール既知近似（confidence は §7 分類器準拠・human 判断。固定 golden は Phase 2a 範囲外＝handcrafted 監視）。

Phase 2a の成果物は「direct＋多ホップ indirect を偽陽性抑止（文字列マスク・getter 非展開・静的採否・大域 cap・intro 精密エッジ）しつつ `--jobs` 並列でも完全決定的に出し、chain 複数経路を真ダイヤモンド golden で固定した動くツール」であり、単体でテスト可能・出荷可能。

---

## Self-Review（v4・本計画著者によるチェック）

**1. spec coverage（§8/§9/§15 の 2a 範囲）:** §8.1 抽出/反復/停止性/Pro\*C手順1非投入 → Task1/8 ✓。§8.2 Aho-Corasick/multiprocessing決定的集約/symlink/生成コード/**intro精密エッジ** → Task4/5/8 ✓。§8.2 memory-limit/spill/分割/ripgrep/差分/ストリーミング → 2b（§15根拠付き境界）✓。§8.3 静的採否/getter非投入/**大域**切り捨て(単調維持) → Task2/3/8 ✓。§8.4 全件性・決定性・max-depth到達記録 → Task10 ✓。§9 chain正規形(07e81bb明確化)/真ダイヤモンド別行/決定性ソート → Task6/8/11 ✓。§9 ref_kind×言語禁止セル → Task1/12 ✓。§5.1 lang_map対称 → Task9 ✓。§10.4 CLI → Task9 ✓（残りは2b/3・境界に根拠明記）。

**2. Placeholder scan:** `pipeline.py` は全文掲載（`...` 廃止＝v2 M-1 解消）。全 Task に実コード・実コマンド・期待出力。「TBD/後で」なし。

**3. Type consistency（串刺し）:** 冒頭契約と全 Task 一致。`_parents_of` は存在しない（intro エッジ規則を契約に明記）。`chains_to` キーワード専用引数 `*, max_depth, max_paths, diag` を Task6/8 一致。`max_depth` 単一定義（ホップ数・0=direct）を `provenance._dfs`（`len(path)-1>=max_depth`）・`fixedpoint._ingest`（`hop>max_depth`＋`prov_max_depth`記録）・CLI で串刺し。マスク期待値は実長 24 字（Task1 C-1 解消）。フィクスチャ識別子は全て ≥2 文字（Task8/11 の空 PASS・0 行＝v2 C-2/C-3/C-5 解消）。`chase_done` 単調維持＝cap は `capped` で scan 除外（v2 H-2 解消）。Pro\*C ホスト変数非投入（v2 C-2 解消）。`prov_max_depth` を fixedpoint が記録（v2 C-6 解消）。

**4. 2巡目レビュー指摘の解消対応:** R(1/2/3)-C「`_parents_of` 偽 chain 未解消」→ **intro ベース精密エッジに再設計・`_parents_of` 廃止**＋`test_多ホップ…偽直結を生まない`/`test_複数seedで無関係seedからの偽chain…` で固定 ✓ / Pro\*C ホスト変数誤投入 → spec §8.1 手順1 精読し**非投入**に是正 ✓ / Task1 マスク期待26字 → 実24字 ✓ / Task8 1文字識別子空PASS → 多文字化＋`assert h1`/非空 assert ✓ / chain_multipath 空洞 → 真ダイヤモンド＋全行目視確定 ✓ / Task10 `prov_max_depth` 不能 → fixedpoint で `hop>max_depth` 記録 ✓ / 大域cap単調性破れ → `chase_done` 不削除・`capped` 除外 ✓ / getter「direct一致のみ」主語 → §8.1手順1「seed/既存ヒット」で根拠付け（spec解釈の明示）✓ / §9 keyword例外 → **spec本体 `07e81bb` で明確化**し計画はそれに従属 ✓ / `__import__`/`...` → 通常import・pipeline.py全文 ✓ / マスク非対称 → 根拠を spec解釈の明示に記載 ✓ / Co-Authored-By → ヘッダに方針明記 ✓ / 複数keyword診断重複 → 2b 境界に明記 ✓ / Task9「赤残しcommit」 → Task9→11連続・単独完了主張禁止を明記 ✓。

**5. 3巡目レビュー指摘の解消対応（全観点 条件付き Go・中核設計は実走で健全確認済）:** R3-C1「Task7 不正 Java で確実 RED」→ メソッド内・`if` 単独行・lineno=3 の既存同形に差替 ✓ / R1/R3-H1「chain_multipath 期待行と実出力齟齬（use@D 欠落・行数違いで誤停止）」→ `D.java` を `check(HUB)` 化し use 排除＋Step3 を実出力厳密 9 行に書換 ✓ / R1-H2「intro 自己定義行汚染（invariant 不正確・脆い）」→ `_ingest` `is_seed` で非 seed の自己再抽出を発見元にしない（spec §8.2）✓ / R2-H1「spec §8.1 手順5 文言衝突（決定性プロセス瑕疵）」→ **spec 本体 `8c21227` で明確化**（手順5＝停止性字句形・投入是非は手順1）✓ / R2-M1「§9 改訂で terminal を追跡識別子に含む用語ねじれ」→ terminal は出辺なし chain 末端で同名 getter は別 target ＝§8.4 全件不変、を実装注に明記 ✓ / R2-M2「getter 報告量 vs PRD」→ 境界にリスク開示 ✓ / R2-M3「diagnostics golden 除外の正当化不足」→ 境界に設計判断明記 ✓ / R1-M4/R2-M4「ref_kind 禁止セル負の契約不足/cap 単調性論拠」→ Task1 負の契約テスト追加・実装注に cap 単調性明記 ✓ / R2-L1/R1-Lx「マスク §8.4 誤援用・csh_direct 差分理由・prov_max_depth 二重記録」→ §7+§8 に是正・Task9 不変根拠/実装注に明記 ✓。

> 次レビュー重点候補（残存・着手と並行確認可）: ① `chain_multipath` 厳密 9 行・`oracle_direct` 1 行増（偽行ゼロ）・`shell_direct` 1 行増を実 regen で目視確定（手順は Task11 に明記済）② getter terminal の hop≥2 報告量は spec §8.4 全件準拠だが PRD 緊張は境界開示済・degrade は 2b ③ spec §8.1 手順5 の `8c21227` 改訂が他箇所と矛盾しないか（手順1/§8.4 と整合確認済）。
