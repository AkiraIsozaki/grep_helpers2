# Angular inline template 式抽出 設計書（§14 後続候補1）

- 日付: 2026-05-23
- 区分: マスター設計書 `2026-05-16-grep-analyzer-design.md` §389 後続候補1の実装設計。track C 差分設計書 `2026-05-23-v2-track-c-embedded-design.md` への追補（埋め込みの「TS 内 Angular テンプレ」拡張）。master/track C が正、本書が触れない事項はそれらに従う。
- 対象: `.component.ts` 等の `template: \`...\`` インラインテンプレート内の Angular 式を、track C の `extract_angular_ts` 再利用で抽出する。
- 由来: master §14 が track C 完了後の後続候補として記録（§389）。§390（既存 java/c/jsp chaser の AST 化統一）は本書の対象外＝別サブプロジェクト（候補2）。

---

## 1. 目的とスコープ

### 1.1 本書が対象とすること
`.component.ts`（dispatch 言語 = `typescript`）内の `template: \`...\`` インラインテンプレート領域のヒットを、**行単位の実効言語ルーティング**で Angular として扱う（classify / AST chaser / snippet を angular 化）。コード領域は typescript のまま。

### 1.2 本書が対象としないこと
- §390 既存 java/c/jsp chaser の AST 化統一（別サブプロジェクト＝候補2）。
- `templateUrl: './x.html'`（外部テンプレ）＝track C の `.html` dispatch 経路で対応済み。
- `.tsx`（React/JSX・Angular 非使用）。
- track C angular のテンプレ限界（パイプ名/`#ref`/`*ngFor` 別名/多行補間/`[ngClass]` キー過抽出）は継承（§6）。

### 1.3 確定スコープ判断（ブレインストーミング結果）
- **直接ヒットは既に automaton 生行走査で検出済み**（grep ヒット/scan は言語非依存）。本書の追加価値は **template 領域内の (a) binding chase（`*ngFor` の `row` 等）・(b) classify 精度・(c) snippet（template_string 巨大スパン回避→1行）** に限定。
- **対応範囲**: 領域ルーティングで chase+classify+snippet を angular 化（フル）。
- **パース方式**: track C と同じ char-native 正規表現検出＋`extract_angular_ts` 再利用（tree-sitter の byte/char 変換を回避）。

---

## 2. アーキテクチャ（実効言語ルーティング）

ファイルの dispatch 言語は `typescript` のまま（**dispatch 無改修**）。ヒット行が inline template 領域内かで**実効言語を行単位に解決**する。

```
effective_language(file_lang, file_text, lineno):
    if file_lang != "typescript":
        return file_lang                       # 高速短絡（既存全言語ゼロコスト）
    if lineno が inline_template_spans(file_text) のいずれかに含まれる:
        return "angular_inline"
    return "typescript"
```

### 2.1 新擬似言語 `angular_inline`（dispatch に登場しない・実効言語専用）
| 経路 | 写像 |
|---|---|
| host_grammar | `"typescript"` |
| host_source | `extract_inline_angular`（§3） |
| `_CATEGORY_BY_LANG` | `_CATEGORY_TS`（angular と同一） |
| `_AST_CHASERS` | `typescript_chaser`（angular と同一） |
| `LANG_KEYWORDS` | `_ANGULAR_KW`（angular と同一） |
| snippet | ヒット1行（ts_span 非経由） |

### 2.2 出力規約（重要な決定）
**TSV `language` 列は dispatch 言語 = `typescript` のまま**（inline template ヒットも）。`angular_inline` は内部の実効言語専用で TSV 語彙には登場しない。proc（C+SQL→"proc"）・jsp（Java+HTML→"jsp"）と同じ「ファイル言語で一律」規約に整合し出力語彙を増やさない。改善は category/chase/snippet の精度に限定。

---

## 3. 検出と抽出（char-native・track C 流儀）

`embed_preprocess.py` に追加（`extract_angular_ts`/`_blank` を流用）。

### 3.1 検出正規表現
```python
_INLINE_TEMPLATE = re.compile(r"\btemplate\s*:\s*`(.*?)`", re.DOTALL)
```
- `template: \`...\`` を捕捉し group(1) = テンプレ内容。`templateUrl:` は `:` が直後でないため非マッチ。

### 3.2 `inline_template_spans(ts_source) -> list[tuple[int,int]]`
各 `_INLINE_TEMPLATE` マッチについて group(1) の行スパン `(start,end)`（0始まり）を返す:
```python
[(ts_source.count("\n", 0, m.start(1)), ts_source.count("\n", 0, m.end(1)))
 for m in _INLINE_TEMPLATE.finditer(ts_source)]
```

### 3.3 `extract_inline_angular(ts_source) -> str`（`host_source("angular_inline", ...)`）
```python
def extract_inline_angular(ts_source):
    kept = list(_blank(ts_source))                 # 全空白化（行数・char 長保存）
    for m in _INLINE_TEMPLATE.finditer(ts_source):
        for i in range(m.start(1), m.end(1)):
            kept[i] = ts_source[i]                  # テンプレ markup だけ復元
    return extract_angular_ts("".join(kept))        # angular 式を抽出
```
→ TS コード領域は空白＝angular パターン非マッチ、テンプレ markup からのみ `{{}}`/`[x]=`/`*ngFor`(of→=正規化) が抽出される。結果を typescript parse すれば `binding_at_line` がテンプレ内束縛（`row` 等）を取得。

### 3.4 `effective_language(file_language, file_text, lineno) -> str`
§2 の擬似コードどおり。`embed_preprocess.py` に追加（classify/snippet/seed が共用）。

---

## 4. パイプライン配線（11拡張点に準じる）

`effective_language` を**共有エントリ点に通す**ことで direct/indirect 両方を一括対応（`pipeline.py`/`fixedpoint/_finalize.py` は無改修）。

| # | ファイル | 差分 |
|---|---|---|
| 1 | `embed_preprocess.py` | `_INLINE_TEMPLATE`/`inline_template_spans`/`extract_inline_angular`/`effective_language` 追加。`_HOST_GRAMMAR["angular_inline"]="typescript"`、`host_source` に angular_inline 分岐（→`extract_inline_angular`） |
| 2 | `classifiers/ts_classifier.py` | `_CATEGORY_BY_LANG["angular_inline"]=_CATEGORY_TS` |
| 3 | `classifiers/__init__.py` | `_AST_CHASERS["angular_inline"]=typescript_chaser` |
| 4 | `stoplist.py` | `LANG_KEYWORDS["angular_inline"]=_ANGULAR_KW` |
| 5 | `classify.py` | `classify_hit` 冒頭で `language = effective_language(language, file_text, lineno)`、classify_ts 分岐タプルに `angular_inline` 追加（direct/indirect 共有経路） |
| 6 | `snippet/__init__.py` | `build_snippet` 冒頭で `effective_language` 解決。`angular_inline` は ts_span 分岐に**入れず1行**（template_string 巨大スパン誤適用回避＝精度向上） |
| 7 | `fixedpoint/_seed.py` | seed の AST/行判定前に `effective_language(lang, text, lineno)` で解決（seed は少数＝regex 許容） |
| 8 | `fixedpoint/_scan.py` | AST 分岐で `spans = inline_template_spans(text)` を **file 単位1回**算出。occurrence が span 内なら `angular_inline` root（`parse_tree("angular_inline",text)` を**遅延1回**）＋`extract_chase_symbols_from_root("angular_inline",...)`、否なら従来 typescript root。**file 単位1パース最適化を維持**（template occurrence がある時のみ追加1パース） |

- **`fixedpoint/_ingest.py`（absorb）は無改修**: worker が正しい cs を found タプルに同梱済（既存 4-tuple 契約のまま）。
- **`effective_language` 高速短絡**: `file_language != "typescript"` は即 file_language 返却＝既存全言語・非 Angular .ts はゼロ追加コスト（regex も走らない）。
- **`pipeline.py`/`_finalize.py` 無改修**: classify_hit/build_snippet の共有エントリで direct/indirect 両方カバー。
- 循環 import なし（classify/snippet/_scan/_seed → embed_preprocess → proc_preprocess の単方向）。

### 4.1 効率（hot path）
- 非 typescript ファイル: `effective_language` 即短絡＝ゼロコスト。
- inline template 無し typescript: `inline_template_spans` の regex 1回（O(n)・空返却）＝追加パースなし。
- inline template 有り typescript: span 内 occurrence がある時のみ `angular_inline` バッファを **file 単位1回**追加 parse。

---

## 5. Inv（不変条件）
- `effective_language` は **非 typescript・inline template 無し typescript・テンプレ外行**で恒等＝**既存 golden 全件 byte 不変**（track A の ts_enum_readonly/tsx_chain/js_kinds/py_chain、track C の jsp_chain/html_passthrough/angular_chain 含む。これらの src は `template:` インラインを含まない＝spans 空＝恒等）。
- 変化するのは「inline template を持つ .ts のテンプレ領域内ヒット」のみ＝新 golden で固定。
- 全て additive（新擬似言語キー追加・共有エントリでの実効言語解決）。
- **二段ゲート**: ①既存 golden 再生成 diff ゼロ ②既存 unit/integration 全緑。

| リスク | 緩和 |
|---|---|
| R1: effective_language が既存 typescript golden を変える | 既存 typescript src は `template:` インライン無し＝spans 空＝恒等。golden ゼロdiff で実証 |
| R2: extract_inline_angular が TS コードから誤抽出 | テンプレ領域外を空白化してから `extract_angular_ts`＝TS object literal（`selector:"x"`）等は非抽出。単体で表明 |
| R3: scan worker の追加パースで perf 劣化 | 非 ts/template 無し ts はゼロ追加パース。template 有りのみ file 単位1パース追加 |
| R4: `template:` 誤検出（コメント/文字列内） | best-effort（§6・track C の `%>`-in-string と同型） |
| R5: snippet が template_string 巨大スパンを返す | angular_inline を ts_span 分岐に入れず1行＝むしろ現状の誤適用を是正 |

---

## 6. 既知限界（master §8.4 / track C §6 に追記）
- `template:` がコメント/文字列内に出る稀ケースで誤検出（best-effort）。
- テンプレ内容に `\``（ネスト/エスケープ template literal）が出ると非貪欲マッチ早期終端（稀）。
- `.tsx` 非対象（Angular 非使用）。`@Component` デコレータ非限定（`template:` パターンのみ＝非 Angular の `template:` リテラルを誤 angular 化しうる・稀）。
- **TSV `language` 列は inline template ヒットでも `typescript`**（内部実効言語のみ angular_inline・§2.2）。
- track C angular のテンプレ限界を継承（パイプ名/`#ref`/`*ngFor` 別名 `as`/`index as i`/多行補間/`[ngClass]` オブジェクトキー過抽出）。

---

## 7. テスト
- **単体**: `inline_template_spans`（`template:` 検出・`templateUrl:` 非検出・多行スパン）／`extract_inline_angular`（テンプレ領域のみ angular 抽出・TS コードの `selector:"x"` 等を誤抽出しない・`*ngFor` 正規化・行数保存）／`effective_language`（typescript+テンプレ内→angular_inline、typescript+コード行→typescript、非 ts→恒等、template 無し .ts→typescript）。
- **classify**: テンプレ内 `(click)="x=1"`→代入・`{{}}`→その他、TS コード行→従来 typescript（不変）。
- **chaser**: テンプレ内 `*ngFor="let row of TRACKED"`→row（angular_inline 経由）、TS コード束縛→typescript（不変）。
- **snippet**: テンプレ内ヒット→1行（template_string 巨大スパン回避）。
- **言語×ref_kind golden** `angular_inline_chain`: `.component.ts`（inline template に `*ngFor="let row of TRACKED"` と別行 `{{ row.code }}`＋TS コードで TRACKED 使用）。language 列=`typescript`、テンプレ内 `row` が indirect:var で chase、TS コード direct と混在を固定。
- **Inv 二段ゲート**（§5）＋2回実行 byte 一致（既存機構）。

---

## 8. master への反映（実装後）
- §389: 「Angular inline template の式抽出（後続候補）」→**完了**（本差分設計書＋実装計画を参照）。残る後続候補は §390（chaser AST 化統一＝候補2）。
- §208 / §8.4: inline template 対応とその既知限界（§6）を追記。
