# Angular inline template 式抽出 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `.component.ts` 内の `template: \`...\`` インラインテンプレート領域のヒットを、行単位の実効言語ルーティング（擬似言語 `angular_inline`）で Angular として classify/chase/snippet できるようにする。

**Architecture:** ファイルの dispatch 言語は `typescript` のまま。`effective_language(file_lang, file_text, lineno)` がテンプレ領域行を `angular_inline` に解決し、`angular_inline` は host_grammar=typescript・host_source=`extract_inline_angular`（テンプレ領域以外を空白化→track C の `extract_angular_ts` 適用）で track C angular 機構＋track A typescript parse を再利用。`effective_language` を共有エントリ（classify_hit/build_snippet/_seed/_scan）に通すことで direct/indirect 両対応（pipeline.py/_finalize.py 無改修）。

**Tech Stack:** Python 3.12, py-tree-sitter 0.23.2（tree-sitter-typescript・wheelhouse 同梱済）, pytest。

**正本spec:** `docs/superpowers/specs/2026-05-23-angular-inline-template-design.md`。

**Inv（全タスク共通）:** 既存 golden（全言語）byte 不変＝`effective_language` は非 typescript・inline template 無し typescript・テンプレ外行で恒等。各タスクのコミット前に `python -m pytest -q` がベースライン（**367 passed, 5 skipped**）以上で緑。

---

## ファイル構成

| ファイル | 差分 |
|---|---|
| `src/grep_analyzer/embed_preprocess.py` | `_INLINE_TEMPLATE`/`inline_template_spans`/`extract_inline_angular`/`effective_language` 追加。`_HOST_GRAMMAR["angular_inline"]="typescript"`、`host_source` に angular_inline 分岐 |
| `src/grep_analyzer/classifiers/ts_classifier.py` | `_CATEGORY_BY_LANG["angular_inline"]=_CATEGORY_TS` |
| `src/grep_analyzer/classifiers/__init__.py` | `_AST_CHASERS["angular_inline"]=typescript_chaser` |
| `src/grep_analyzer/stoplist.py` | `LANG_KEYWORDS["angular_inline"]=_ANGULAR_KW` |
| `src/grep_analyzer/classify.py` | `classify_hit` 冒頭で effective_language 解決＋tuple に angular_inline |
| `src/grep_analyzer/snippet/__init__.py` | `build_snippet` 冒頭で effective_language 解決 |
| `src/grep_analyzer/fixedpoint/_seed.py` | seed で effective_language 解決し eff を chase/ingest へ |
| `src/grep_analyzer/fixedpoint/_scan.py` | AST 分岐で typescript root + angular_inline root の2変数管理 |
| `tests/unit/test_embed_preprocess.py` 他 | 単体テスト追加 |
| `tests/golden/cases/angular_inline_chain/` | end-to-end golden |

---

## Task 1: extract_inline_angular / inline_template_spans / effective_language（embed_preprocess）

**Files:**
- Modify: `src/grep_analyzer/embed_preprocess.py`
- Test: `tests/unit/test_embed_preprocess.py`

- [ ] **Step 1: 失敗テストを書く**

```python
# tests/unit/test_embed_preprocess.py に追記
from grep_analyzer.embed_preprocess import (
    effective_language, extract_inline_angular, inline_template_spans)

_COMPONENT = (
    'import { Component } from "@angular/core";\n'      # 1
    "@Component({\n"                                     # 2
    '  selector: "app-x",\n'                             # 3
    "  template: `\n"                                    # 4
    "    <ul>\n"                                         # 5
    '      <li *ngFor="let row of TRACKED">\n'           # 6
    "        {{ row.code }}\n"                           # 7
    "      </li>\n"                                      # 8
    "    </ul>\n"                                        # 9
    "  `,\n"                                             # 10
    "})\n"                                               # 11
    "export class XComponent {\n"                        # 12
    "  items = TRACKED;\n"                               # 13
    "}\n")                                               # 14


def test_inline_template_spans_検出():
    spans = inline_template_spans(_COMPONENT)
    assert len(spans) == 1
    s, e = spans[0]
    assert s <= 5 and e >= 8                 # テンプレ内容行（5..9 付近）を含む


def test_inline_template_spans_templateUrlは非検出():
    src = '@Component({ templateUrl: "./x.html" })\n'
    assert inline_template_spans(src) == []


def test_inline_template_spans_stylesは非検出():
    src = "@Component({ styles: [`a{}`, `b{}`] })\n"
    assert inline_template_spans(src) == []


def test_extract_inline_angular_テンプレのみangular抽出_TSコード誤抽出なし():
    out = extract_inline_angular(_COMPONENT)
    assert out.count("\n") == _COMPONENT.count("\n")    # 行数保存
    assert "let row = TRACKED" in out                    # *ngFor 正規化（of→=）
    assert "row.code" in out                             # 補間
    assert "selector" not in out and "app-x" not in out  # TS コードは誤抽出しない
    assert "items" not in out                            # TS コードの代入も非抽出


def test_effective_language_テンプレ行はangular_inline():
    assert effective_language("typescript", _COMPONENT, 4) == "angular_inline"   # template: ` 開き行（spec §7・内容は次行＝この行は空白化され classify その他で無害）
    assert effective_language("typescript", _COMPONENT, 6) == "angular_inline"   # *ngFor 行
    assert effective_language("typescript", _COMPONENT, 7) == "angular_inline"   # {{ }} 行


def test_effective_language_コード行はtypescript():
    assert effective_language("typescript", _COMPONENT, 13) == "typescript"      # items = 行


def test_effective_language_非tsと非テンプレは恒等():
    assert effective_language("java", "x", 1) == "java"
    assert effective_language("jsp", "x", 1) == "jsp"
    plain = "export const x = 1;\n"
    assert effective_language("typescript", plain, 1) == "typescript"            # template 無し
    assert inline_template_spans(plain) == []
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_embed_preprocess.py -k "inline_template or extract_inline or effective_language" -v`
Expected: FAIL（`ImportError: cannot import name 'effective_language'`）

- [ ] **Step 3: 実装（embed_preprocess.py に追記。`extract_angular_ts`/`_blank` は既存を流用）**

```python
# src/grep_analyzer/embed_preprocess.py に追記（extract_angular_ts 定義の後）

# .component.ts の inline angular template（template: `...`）検出。
# templateUrl: は `template` の後に Url が続き `\s*:` に非マッチ。
# styles: [`...`] も `\btemplate\s*:` に非マッチ。best-effort（spec §6）。
_INLINE_TEMPLATE = re.compile(r"\btemplate\s*:\s*`(.*?)`", re.DOTALL)


def inline_template_spans(ts_source: str) -> list[tuple[int, int]]:
    """inline template 内容（group1）の行スパン [(s,e)]（0始まり・spec §3.2）。"""
    return [(ts_source.count("\n", 0, m.start(1)), ts_source.count("\n", 0, m.end(1)))
            for m in _INLINE_TEMPLATE.finditer(ts_source)]


def extract_inline_angular(ts_source: str) -> str:
    """inline template 領域のみ angular 式を残し他を空白化（行数保存・spec §3.3）。"""
    kept = list(_blank(ts_source))
    for m in _INLINE_TEMPLATE.finditer(ts_source):
        for i in range(m.start(1), m.end(1)):
            kept[i] = ts_source[i]
    return extract_angular_ts("".join(kept))


def effective_language(file_language: str, file_text: str, lineno: int) -> str:
    """ヒット行の実効言語（spec §2/§3.4）。typescript の inline template 行のみ
    angular_inline、他は file_language 恒等（高速短絡）。"""
    if file_language != "typescript":
        return file_language
    hit = lineno - 1
    for s, e in inline_template_spans(file_text):
        if s <= hit <= e:
            return "angular_inline"
    return "typescript"
```

- [ ] **Step 4: host_grammar / host_source に angular_inline を追加**

`_HOST_GRAMMAR`（既存 `{"proc": "c", "jsp": "java", "angular": "typescript"}`）に追記:
```python
_HOST_GRAMMAR = {"proc": "c", "jsp": "java", "angular": "typescript",
                 "angular_inline": "typescript"}
```
`host_source` に分岐追加（`angular` 分岐の後）:
```python
    if language == "angular_inline":
        return extract_inline_angular(source)
    return source
```

- [ ] **Step 5: パスを確認**

Run: `python -m pytest tests/unit/test_embed_preprocess.py -v`
Expected: PASS（既存＋新規）

- [ ] **Step 6: コミット**

```bash
git add src/grep_analyzer/embed_preprocess.py tests/unit/test_embed_preprocess.py
git commit -m "feat(embed): inline_template_spans/extract_inline_angular/effective_language（angular_inline 実効言語・track C angular 機構再利用）"
```

---

## Task 2: angular_inline をレジストリ登録（category / AST chaser / stoplist）

**Files:**
- Modify: `src/grep_analyzer/classifiers/ts_classifier.py`（`_CATEGORY_BY_LANG`）, `src/grep_analyzer/classifiers/__init__.py`（`_AST_CHASERS`）, `src/grep_analyzer/stoplist.py`（`LANG_KEYWORDS`）
- Test: `tests/unit/test_classify.py`, `tests/unit/test_ast_chaser.py`

- [ ] **Step 1: 失敗テストを書く**

```python
# tests/unit/test_classify.py に追記
from grep_analyzer.classifiers.ts_classifier import classify_ts


def test_angular_inline_classify_直接():
    # angular_inline を直接呼ぶ（routing は Task 3）。host_source=extract_inline_angular。
    src = '@Component({ template: `<p>{{ user.code }}</p>` })\n'
    assert classify_ts("angular_inline", src, 1)[0] == "その他"
    src2 = '@Component({ template: `<button (click)="x = 1">b</button>` })\n'
    assert classify_ts("angular_inline", src2, 1)[0] == "代入"


# tests/unit/test_ast_chaser.py に追記
from grep_analyzer.chase import extract_chase_symbols_tree


def test_angular_inline_chaser_ngFor():
    src = '@Component({ template: `<li *ngFor="let row of TRACKED">{{row.code}}</li>` })\n'
    cs = extract_chase_symbols_tree("angular_inline", src, 1)
    assert "row" in cs.vars
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_classify.py::test_angular_inline_classify_直接 tests/unit/test_ast_chaser.py::test_angular_inline_chaser_ngFor -v`
Expected: FAIL（`KeyError: 'angular_inline'`）

- [ ] **Step 3: `_CATEGORY_BY_LANG` に angular_inline 追加**

`src/grep_analyzer/classifiers/ts_classifier.py` の `_CATEGORY_BY_LANG`（既存 `"jsp": _CATEGORY_JAVAC, "angular": _CATEGORY_TS,` 行）に追記:
```python
    "jsp": _CATEGORY_JAVAC, "angular": _CATEGORY_TS, "angular_inline": _CATEGORY_TS,
```

- [ ] **Step 4: `_AST_CHASERS` に angular_inline 追加**

`src/grep_analyzer/classifiers/__init__.py` の `_AST_CHASERS`（`"angular": typescript_chaser,` の後）に1行:
```python
    "angular": typescript_chaser,
    "angular_inline": typescript_chaser,
```

- [ ] **Step 5: `LANG_KEYWORDS` に angular_inline 追加**

`src/grep_analyzer/stoplist.py` の `LANG_KEYWORDS`（`"angular": _ANGULAR_KW` の行）に追記:
```python
    "jsp": _JSP_KW, "html": frozenset(), "angular": _ANGULAR_KW,
    "angular_inline": _ANGULAR_KW}
```

- [ ] **Step 6: パスを確認**

Run: `python -m pytest tests/unit/test_classify.py tests/unit/test_ast_chaser.py -v`
Expected: PASS（既存＋新規）

- [ ] **Step 7: コミット**

```bash
git add src/grep_analyzer/classifiers/ts_classifier.py src/grep_analyzer/classifiers/__init__.py src/grep_analyzer/stoplist.py tests/unit/test_classify.py tests/unit/test_ast_chaser.py
git commit -m "feat(angular-inline): angular_inline を _CATEGORY_BY_LANG/_AST_CHASERS/LANG_KEYWORDS に登録（angular と同写像）"
```

---

## Task 3: classify_hit / build_snippet に effective_language ルーティング

**Files:**
- Modify: `src/grep_analyzer/classify.py`（`classify_hit`）, `src/grep_analyzer/snippet/__init__.py`（`build_snippet`）
- Test: `tests/unit/test_classify.py`, `tests/unit/test_snippet.py`

- [ ] **Step 1: 失敗テストを書く**

```python
# tests/unit/test_classify.py に追記
from grep_analyzer.classify import classify_hit

_C = ('@Component({\n'
      '  template: `<button (click)="x = 1">{{ user.code }}</button>`,\n'   # 2
      '})\n'
      'export class C {\n'                                                    # 4
      '  items = TRACKED;\n'                                                  # 5
      '}\n')


def test_classify_hit_inline_template行はangular扱い():
    # L2（template 行）の (click)="x=1" → 代入（angular_inline 経由）
    assert classify_hit("typescript", "", _C, 2, "")[0] == "代入"


def test_classify_hit_TSコード行はtypescript不変():
    # L5 class field items = TRACKED → public_field_definition → 宣言（typescript 経路）。
    # 誤って angular_inline に routing されると領域外で空白化され その他 になる＝判別子。
    assert classify_hit("typescript", "", _C, 5, "")[0] == "宣言"


# tests/unit/test_snippet.py に追記
from grep_analyzer.snippet import build_snippet


def test_build_snippet_inline_template行は1行():
    # const 宣言で包むと未 routing 時 ts_span が宣言全体（巨大スパン）を返すため
    # routing（angular_inline→1行）の効果を観測できる（@Component デコレータ形は
    # ts_span が None を返し元から1行＝routing 効果が出ない・spec §7 巨大スパン回避）。
    src = ('export const C = defineComponent({\n'   # 1
           '  template: `\n'                         # 2
           '    <p>{{ TRACKED }}</p>\n'             # 3 (hit)
           '  `,\n'                                  # 4
           '});\n')                                  # 5
    out = build_snippet("typescript", "", src, 3)
    assert "TRACKED" in out
    assert "defineComponent" not in out             # 宣言全体の巨大スパンにならない＝routing 効果
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_classify.py::test_classify_hit_inline_template行はangular扱い tests/unit/test_snippet.py::test_build_snippet_inline_template行は1行 -v`
Expected: FAIL（routing 未実装＝L2 が typescript で その他、snippet が巨大）

- [ ] **Step 3: `classify_hit` 冒頭で effective_language 解決＋tuple に angular_inline**

`src/grep_analyzer/classify.py` の import に追加:
```python
from grep_analyzer.embed_preprocess import effective_language
```
`classify_hit` 本体（先頭で解決し、ts-family tuple に `angular_inline` を追加）:
```python
def classify_hit(
    language: str, dialect: str, file_text: str, lineno: int, content: str
) -> ClassifyResult:
    language = effective_language(language, file_text, lineno)
    if language in ("java", "c", "proc", "python", "javascript", "typescript",
                    "tsx", "jsp", "angular", "angular_inline"):
        return classify_ts(language, file_text, lineno)
    if language == "html":
        return ("その他", "high")
    # 以降 sql/perl/groovy/shell/フォールバックの分岐は現行のまま（変更しない）
```
（注: 既存の classify_ts tuple に `angular` が含まれていなければ Task 3 で併せて追加。track C で angular は classify routing 済のはず。`angular_inline` を必ず含める。）

- [ ] **Step 4: `build_snippet` 冒頭で effective_language 解決**

`src/grep_analyzer/snippet/__init__.py` の import に追加:
```python
from grep_analyzer.embed_preprocess import effective_language, jsp_region_span
```
（既存の `jsp_region_span` import 行に併記）。`build_snippet` 本体先頭（`lines = _physical_lines(...)` の後・`span = None` の前）に1行:
```python
    language = effective_language(language, file_text, lineno)
```
`angular_inline` は ts_span 分岐タプルに**入れない**＝`span=None`→1行フォールバック（既存ロジックのまま）。

- [ ] **Step 5: パスを確認**

Run: `python -m pytest tests/unit/test_classify.py tests/unit/test_snippet.py -v`
Expected: PASS（既存＋新規）

- [ ] **Step 6: コミット**

```bash
git add src/grep_analyzer/classify.py src/grep_analyzer/snippet/__init__.py tests/unit/test_classify.py tests/unit/test_snippet.py
git commit -m "feat(angular-inline): classify_hit/build_snippet に effective_language ルーティング（direct/indirect 共有・テンプレ行は angular_inline・snippet 1行）"
```

---

## Task 4: fixedpoint chaser ルーティング（_seed / _scan）

**Files:**
- Modify: `src/grep_analyzer/fixedpoint/_seed.py`, `src/grep_analyzer/fixedpoint/_scan.py`
- Test: `tests/unit/test_fixedpoint.py`（または integration）, `tests/integration/test_v2_langs.py`

- [ ] **Step 1: 失敗テスト（integration・end-to-end でテンプレ内 chase を表明）**

```python
# tests/integration/test_v2_langs.py に追記
def test_angular_inline_template_chase(tmp_path):
    from grep_analyzer.pipeline import run, _default_opts
    src = tmp_path / "src"; src.mkdir()
    (src / "x.component.ts").write_text(
        "@Component({\n"
        '  template: `\n'
        '    <li *ngFor="let row of TRACKED">\n'      # L3 テンプレ: row 束縛
        "      {{ row.code }}\n"                       # L4 テンプレ: row 使用
        "  `,\n"
        "})\n"
        "export class X { items = init(); }\n", "utf-8")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "TRACKED.grep").write_text(
        'x.component.ts:3:    <li *ngFor="let row of TRACKED">\n', "utf-8")
    out = tmp_path / "out"
    assert run(inp, out, src, _default_opts()) == 0
    tsv = (out / "TRACKED.tsv").read_text("utf-8-sig")
    assert "\ttypescript\t" in tsv               # language 列は typescript（§2.2）
    assert "indirect:var" in tsv                 # row が chase された
    assert "row" in tsv
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/integration/test_v2_langs.py::test_angular_inline_template_chase -v`
Expected: FAIL（row が chase されない＝典型的に indirect:var 行が出ない）

- [ ] **Step 3: `_seed.py` で effective_language 解決**

`src/grep_analyzer/fixedpoint/_seed.py` の import に追加:
```python
from grep_analyzer.embed_preprocess import effective_language
```
`initialize_state` の seed ループ内 `if sp.is_file():` ブロックを次へ（`lang` を eff へ畳む）:
```python
        if sp.is_file():
            text, _, _, lang, dialect = file_meta(
                s.file, sp.read_bytes(), opts.lang_map,
                fallback_chain=list(opts.encoding_fallback))
            lang = effective_language(lang, text, s.lineno)   # テンプレ行→angular_inline
            if lang in _AST_CHASERS:
                cs = extract_chase_symbols_tree(lang, text, s.lineno)
            else:
                _ls = text.split("\n")
                seed_line = _ls[s.lineno - 1] if 0 <= s.lineno - 1 < len(_ls) else ""
                cs = extract_chase_symbols(lang, dialect, seed_line)
        else:
            lang, dialect = s.language, "bourne"
            cs = ChaseSymbols()
        ingest_one(state, occ, lang, cs, kinds_of(cs), hop=1, is_seed=True)
```

- [ ] **Step 4: `_scan.py` で2-root ルーティング**

`src/grep_analyzer/fixedpoint/_scan.py` の import に追加:
```python
from grep_analyzer.embed_preprocess import inline_template_spans
```
`_scan_file` の `if automaton_obj is not None:` ブロック（現 43-57行・末尾 return 含む）を次へ置換:
```python
    if automaton_obj is not None:
        ts_root = None
        ang_root = None
        spans = []
        if language in _AST_CHASERS:
            try:
                ts_root = parse_tree(language, text)
            except Exception:
                ts_root = None
            if language == "typescript":
                spans = inline_template_spans(text)
        for i, line in enumerate(text.split("\n"), start=1):
            symbols = list(automaton.scan_line(automaton_obj, line))
            if not symbols:
                continue
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
（`found = []` は既存どおりブロック前で初期化。`language`/`dialect` の返却は不変＝TSV language 列は dispatch 言語 typescript・§2.2。）

- [ ] **Step 5: パスを確認**

Run: `python -m pytest tests/integration/test_v2_langs.py::test_angular_inline_template_chase tests/unit/test_fixedpoint.py -v`
Expected: PASS

- [ ] **Step 6: 全体回帰（Inv）**

Run: `python -m pytest -q`
Expected: PASS（367＋新規・既存ゼロ破壊）

- [ ] **Step 7: コミット**

```bash
git add src/grep_analyzer/fixedpoint/_seed.py src/grep_analyzer/fixedpoint/_scan.py tests/integration/test_v2_langs.py
git commit -m "feat(angular-inline): fixedpoint chaser ルーティング（_seed eff 解決・_scan 2-root 遅延 angular_inline parse）"
```

---

## Task 5: golden + ゲート + master 反映

**Files:**
- Create: `tests/golden/cases/angular_inline_chain/{src/x.component.ts,input/TRACKED.grep,expected/TRACKED.tsv}`
- Modify: `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`

- [ ] **Step 1: src/input を作る**

`tests/golden/cases/angular_inline_chain/src/x.component.ts`（テンプレ内 `*ngFor` 束縛と消費を別行・TS コードでも TRACKED 使用）:
```typescript
import { Component } from "@angular/core";
@Component({
  selector: "app-x",
  template: `
    <li *ngFor="let row of TRACKED">
      {{ row.code }}
    </li>
  `,
})
export class XComponent {
  data = TRACKED;
}
```
`tests/golden/cases/angular_inline_chain/input/TRACKED.grep`（TRACKED は 5 行目テンプレと 11 行目コード）:
```
x.component.ts:5:    <li *ngFor="let row of TRACKED">
x.component.ts:11:  data = TRACKED;
```

- [ ] **Step 2: 生成して内容検証（目視・盲目スナップショット禁止）**

Run:
```bash
python -c "
from pathlib import Path
from grep_analyzer.pipeline import run, _default_opts
import tempfile
case = Path('tests/golden/cases/angular_inline_chain')
out = Path(tempfile.mkdtemp())
run(case/'input', out, case/'src', _default_opts())
print((out/'TRACKED.tsv').read_text('utf-8-sig'))
"
```
検証ポイント（**実出力で成立確認**）: 全行 language 列=`typescript`、TRACKED direct 2 行（5・11）、テンプレ内 `row` が indirect:var で 6 行目（`{{ row.code }}`）を参照、TS コード `data`（11 行目の代入）と混在。成立しなければ src 行レイアウトを見直すか報告。

- [ ] **Step 3: BOM 付きでスナップショット**

Run:
```bash
python -c "
from pathlib import Path
from grep_analyzer.pipeline import run, _default_opts
import tempfile
case = Path('tests/golden/cases/angular_inline_chain')
out = Path(tempfile.mkdtemp())
run(case/'input', out, case/'src', _default_opts())
sr = str((case/'src').resolve())
(case/'expected').mkdir(exist_ok=True)
for tsv in out.glob('*.tsv'):
    txt = ''.join((ln.replace(sr+'/', '{SOURCE_ROOT}/', 1) if (sr+'/') in ln else ln)
                  for ln in tsv.read_text('utf-8-sig').splitlines(keepends=True))
    (case/'expected'/tsv.name).write_text(txt, 'utf-8-sig')
    print(tsv.name, 'snapshotted')
"
```

- [ ] **Step 4: golden 緑＋全体回帰（Inv 二段ゲート）**

Run: `python -m pytest tests/golden -q && python -m pytest -q`
Expected: PASS（angular_inline_chain 含む全 golden 緑・既存 golden ゼロdiff・全体緑）

- [ ] **Step 5: master 反映（additive）**

`docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`:
- §389（「Angular inline template の式抽出（後続候補）」）を**完了**へ更新（本差分設計書 `2026-05-23-angular-inline-template-design.md`＋実装計画を参照）。残る後続候補は §390（chaser AST 化統一）のみと明記。
- §208 / §8.4: inline template 対応（実効言語 angular_inline・language 列は typescript・テンプレ内 JS `${}` は chase 空 等の既知限界）を追記。
- テスト件数ベースラインを新値へ更新。

- [ ] **Step 6: コミット**

```bash
git add tests/golden/cases/angular_inline_chain docs/superpowers/specs/2026-05-16-grep-analyzer-design.md
git commit -m "test(golden)+docs: angular_inline_chain（テンプレ内 row 多ホップ・language=typescript）＋master §389 完了反映"
```

---

## 完了基準（spec §5/§7）
- 全テスト緑（既存 golden ゼロdiff＝Inv ＋ angular_inline_chain 新規 golden）。
- テンプレ内 `*ngFor` 束縛が chase され、テンプレ内 classify が angular（代入/その他）、snippet が1行。
- TS コード行は typescript のまま不変。TSV `language` 列は inline template ヒットでも `typescript`。
- 非 typescript・template 無し typescript は `effective_language` 恒等＝既存挙動 byte 不変。
