---
name: coding-conventions
description: コードの新規作成・修正時に適用するコーディング規約。ファイルの作成・編集を行うときに必ず使用すること。
---

# コーディング規約

## 言語

- コード内のコメント・docstringは**日本語**で記述する
- 変数名・関数名・クラス名は英語のまま

## コメントルール

1. **モジュールdocstring（必須）**: 全 `.py` ファイルの先頭に、そのモジュールの責務を1〜2行で記述する（詳細な形式は後述の「モジュール docstring 形式」を参照）
   ```python
   """pyahocorasick ラッパ。識別子語境界一致のみ採用し決定的に返す。

   Related: spec §8.2
   """
   ```

2. **クラスdocstring（必須）**: 全クラスにそのクラスの役割を記述する
   ```python
   class Neo4jClient:
       """Neo4jデータベースへの接続を管理し、ノードとリレーションシップのMERGE操作を提供する。"""
   ```

3. **関数・メソッドdocstring（必須）**: publicなメソッド・関数には必ずdocstringを付ける。privateメソッド（`_`始まり）はロジックが自明でない場合に付ける
   ```python
   def merge_nodes(self, nodes: list[NodeData], batch_size: int = 1000) -> None:
       """ノードをNeo4jにMERGE（存在すれば更新、なければ作成）する。

       Args:
           nodes: マージ対象のノードデータのリスト。
           batch_size: 一度にコミットするノード数。
       """
   ```

4. **インラインコメント（適宜）**: 複雑なロジック、意図が不明瞭な箇所、ワークアラウンドには理由を添えたコメントを付ける。自明なコードにはコメント不要
   ```python
   # fnmatchはディレクトリの再帰パターン（**）を処理しないため、手動でプレフィックスマッチする
   if pat.endswith("/**"):
   ```

5. **コメントを付けない場面**: 変数名や関数名から明らかに意図が読み取れるコードに冗長なコメントは不要

## モジュール docstring 形式

`.py` の module docstring は次の形にする（**新規作成時から守ること**。守らないと後で全モジュール一括改稿になる）。

- **1 文目に spec 番号（`§X`）を書かない**。何を提供するモジュールかを自然文で書く
- spec 参照は **末尾に `Related: spec §X` 行で集約**する
- WHY・不変条件・決定性根拠・外部ライブラリ版差吸収根拠は本文に残す

```python
# 悪い例（1 文目に spec 番号）
"""pyahocorasick ラッパ（spec §8.2）。識別子語境界一致のみ採用し決定的に返す。"""

# 良い例（spec 参照は末尾 Related: へ）
"""pyahocorasick ラッパ。識別子語境界一致のみ採用し決定的に返す。

Related: spec §8.2
"""
```

## フェーズ・版・タスクマーカー禁止

進行管理の痕跡を **コードに残さない**（git log で辿れる）。

- `Phase 2a` / `Phase 3` 等のフェーズマーカー → 書かない
- `v9` / `v10` 等の版マーカー → 書かない（仕様は spec 側で管理）
- `Task2` / `TODO(後で)` 等のタスクマーカー → 書かない（必要なら Issue 化）
- spec 参照だけのコメント（`# spec §X` のみ）→ 書かない。意図が要るなら「何を保証しているか」を能動文で書く

**削除してはいけないコメント**: 不変条件・停止性保証・決定性の根拠・workaround の理由・外部ライブラリの版差吸収根拠。

## 命名規約

### フルスペル原則

略語は原則禁止。次のホワイトリストに限り略可:

`api`, `id`, `url`, `uri`, `io`, `os`, `re`, `ast`, `cli`, `tsv`, `csv`, `utf`, `sql`, `min`, `max`, `len`, `idx`, `tmp`, `args`, `kwargs`, `enc`(encoding), `lang`(language), `opts`(options), `diag`(diagnostics)

（`idx`/`tmp`/`args`/`kwargs`/`ast`/`uri`/`io` 等は Python 汎用の慣用句として許容。本プロジェクトで現在未使用でも「使ってよい候補」であり廃止対象ではない。）

それ以外はフルスペルにする。今回の実例: `au`→`automaton_obj`, `sym`/`syms`→`symbol`/`symbols`, `cs`→`chase_symbols`, `dia`→`dialect`, `rel`→`relpath`, `agg`→`hits_by_relpath`, `meta`→`file_meta_by_relpath`, `lp`/`rps`→`lparen`/`rparens`, `vocc`/`vsym`→`visited_occurrences`/`visited_symbols`。

### 述語・動詞の統一

- 真偽返却: `is_*` / `has_*` / `should_*`（例: `_err`→`_has_error`）
- 取得: 副作用なし `get_*`、計算重ければ `compute_*` / `build_*`
- 変換: `to_*` / `*_from_*` で方向を明示

### ドメイン語彙の表記固定（混在禁止）

同じ概念は 1 表記に固定する。grep_analyzer では:

- `relpath`（`rel` / `relative_path` / `rel_path` は禁止）
- `lineno`（`line_no` / `line_number` / `linenum` は禁止）
- `keyword`, `symbol`, `occurrence`, `provenance`, `chain`, `hop`, `seed`, `dialect`, `span`

### 命名見直しの除外

次は規約対象外（rename しない）:

- 内包表記 / ジェネレータ式の束縛変数（`[x for x in xs]` の `x`）
- ループカウンタの慣用識別子（`for i in range(...)` の `i`/`j`/`k`）
- アンダースコア単独（`_`）の意図的破棄
- 定義から最終参照まで **3 物理行以内**のローカル変数

逆に **関数引数・クラス属性・モジュール定数・4 行以上のローカル変数は対象**（短くても `for symbol in part.chase:` のように本体が長いループ変数は rename する）。

**ネスト関数・lambda 代替の小ヘルパー関数名も対象**（例: `def m(ri, pi)`→`def match_segments(rel_idx, pat_idx)`）。定義から最終参照まで 3 行以内かつ自明なものだけ除外。

## 構造規約

- **1 ファイル 1 責務**。ファイルが大きくなったら責務別に分割する（snippet/ や fixedpoint/ のようにサブパッケージ化）
- **用途別サブモジュール**: regex 等を `_patterns.py` 単一ファイルに全部入れない。用途ごとに分ける（`snippet_boundaries.py` / `literal_masking.py` / `symbol_extraction.py`）
- **層分離（葉→根の一方向、循環禁止）**: `patterns/*` は何にも依存しない葉。`classifiers/*` は `patterns/*` と `model` のみ。下位が上位（pipeline/cli）を import しない
- **DRY 誤適用防止**: 「偶然 2 箇所が同じ形」を安易に寄せない。集約前に (1) 同一知識か（片方だけ変わるシナリオが想像できるなら寄せない）、(2) 同じ用語で説明できるか、(3) Rule of Three（3 箇所目が出てから抽象化）を確認する

## 実装の罠（今回ハマった点）

- **multiprocessing worker に状態オブジェクトを渡さない**: `Pool.map` で呼ぶ worker 関数の引数はプリミティブ（str/bytes/dict 等）に限る。大きな状態クラスは main process で保持し、worker には必要な値だけ抽出して渡す（pickle コスト・決定性のため）
- **モジュールを跨いで共有する helper は public 名にする**: `_` 接頭辞は「そのモジュール内 private」の意味。他モジュールから import される helper に `_` を付けると意味が破れる（例: `_file_meta`→`file_meta`）。逆に、公開 API と紛らわしい実装詳細は private のままにする
- **import は先頭に集約**: 関数内 import / ファイル途中の import（mid-file import, PEP8 E402）を避ける。循環依存回避でやむを得ない場合のみ局所 import を許容し、理由をコメントする
