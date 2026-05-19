# grep_analyzer

grep 結果を言語別に分類し、**決定的（deterministic）**な TSV を出力するツール。
同一入力・同一オプションに対し常にバイト同一の結果を返すことを設計不変条件とする。

- Python 3.12 / 標準ライブラリ中心 + tree-sitter・chardet・pyahocorasick
- 大規模ソース木に対する直接ヒット抽出 ＋ 不動点による間接（indirect）参照追跡
- オフライン再現ビルド対応（`wheelhouse/` + `requirements.lock` を同梱）

---

## このツールで何ができる？（どんな困りごとを解消する？）

### 解決したい困りごと

大きなソースコードの中で「あるキーワード（定数名・API 名・設定キー・マジック値など）が
**結局どこまで影響しているのか**」を調べたい場面はよくある。
たとえば「この定数を消したい／変えたいが、巻き込み範囲は？」「この古い値はどこで使われている？」
といった**影響調査・移行調査・棚卸し**。

ところが素の `grep` だけでは、次のような壁にぶつかる。

1. **文字どおり一致した行しか出ない。** キーワードが変数に代入されたり、getter/setter
   経由で受け渡されたりして**間接的に伝わっている先**は、grep には映らない。手で芋づるを
   たどることになり、漏れるし、しんどい。
2. **結果がただの行の羅列。** どれが定義でどれが参照か、どの言語か、どんな使われ方かが
   分からず、仕分けが手作業になる。
3. **大きなコードベースだと運用がつらい。** 結果が巨大、実行が長い、途中で落ちるとやり直し、
   実行のたびに結果の並びが変わってレビュー（差分確認）にならない。レガシー（cp932 など
   非 UTF-8）のソースだと文字化けも混ざる。

### このツールがやること

- **間接参照まで追う。** direct ヒットを起点に、定数 → 変数 → getter/setter …と参照を
  「もう新しく見つからなくなるまで」たどり（＝**不動点**）、grep では見えない
  **本当の影響範囲（indirect ヒット）**まで洗い出す。
- **仕分け済みで出す。** 各ヒットを言語（Java / C / シェル）・分類（定義か参照かなど）
  付きの**表（TSV）**にする。Excel や差分ツールでそのまま見られる。
- **何度実行しても結果が同じ（決定的）。** 並びまで安定なので、ブランチ間・実行間の
  **差分が意味を持ち**、レビューや承認の証跡にできる。
- **大規模・実運用に耐える。** 巨大結果は Excel 互換で自動分割、`--resume` で途中再開、
  レガシー文字コードのフォールバック復号、メモリ上限での安全な縮退、
  クローン即オフライン再現ビルドまで面倒を見る。

### ざっくり例（grep との違い）

`K1` という定数を調べたいとする。

```java
static final int K1 = 1;          // ← grep でも見つかる（direct）
int limit = K1;                   // ← grep でも見つかる（direct）
applyLimit(limit);                // ← grep には映らない。でも K1 が効いている
```

素の grep は上 2 行で終わり。本ツールは `K1 → limit → applyLimit(...)` と参照を
たどり、3 行目のような**間接的に K1 が効いている箇所も「indirect ヒット」として
表に出す**。これで「K1 を変えたら何が壊れるか」が一望できる。

### 向いている場面

- 定数・API・設定キーの**変更／削除前の影響調査**
- 旧仕様・マジック値の**棚卸し／移行調査**
- 「この値が関わる箇所すべて」を出す**監査・セキュリティ用途**
- レガシー（日本語・cp932 等）混在の**大規模多言語ツリーの解析**

---

## 用語集

聞き慣れない言葉をできるだけかみ砕いて説明する（カッコ内は正式名や対応オプション）。

| 用語 | かみ砕いた説明 |
|---|---|
| **不動点（fixpoint）** | ヒットから参照をたどって新しいヒットを足す、を「**もうこれ以上新しく見つからなくなるまで**」くり返すこと。これ以上変化しない状態を数学で「不動点」と呼ぶのが名前の由来。間接的な参照を取りこぼさず集めるための仕組み。 |
| **direct ヒット** | grep の入力ファイルが「ここ」と**じかに指している**場所。 |
| **indirect ヒット** | そこから**芋づる式にたどって**見つかった、関連する場所。 |
| **決定的（deterministic）** | 同じ入力なら、**何回実行しても結果がまったく同じ**になること（1 文字もズレない）。このツールがいちばん大事にしている性質。 |
| **golden テスト** | 「これが正解」という出力をファイルに保存しておき、出力が**少しでも変わったら気づける**比較テスト。 |
| **manifest** | そのキーワードの処理が「**ちゃんと終わったか**」を判断するための、行数やハッシュを書いた小さな台帳ファイル（`<keyword>.manifest.json`）。`--resume` で使う。 |
| **part 分割** | 1 キーワードの結果が大きすぎるとき `<keyword>.part01.tsv` のように**複数ファイルに分ける**こと。つなげれば 1 ファイルのときと中身は同じ（Excel の行数上限対策）。 |
| **正規化（canonical blob）** | 「書き出すとき」と「終わったか確かめるとき」で、**まったく同じルールで中身を 1 本にそろえる**処理。ファイルの分け方が違っても同じ結果になる。 |
| **縮約 / §8.4 全件性** | 診断ログが多すぎるときに途中を**省略する**こと（縮約）。ただし「全部見えないと困る」種類のログだけは省略せず全部出す。 |
| **degrade / `_ITEMS_PER_MB`** | `--memory-limit` を付けたとき、実メモリではなく「**だいたいの件数**」でメモリ量を見積もり、多すぎたら**軽い処理方式に切り替える**こと。毎回同じ判断になるよう、あえて概算を使う。 |
| **decode フォールバック鎖** | 文字コード不明のファイルを読むとき「まず UTF-8 → ダメなら自動判定 → それでもダメなら指定した候補を順に」と**試す候補リスト**（`--encoding-fallback`）。 |
| **seed / hop** | seed＝たどり始めの地点（＝ direct ヒット）。hop＝そこから参照を**1 回たどる「1 歩」**。 |
| **TSV** | タブ区切りのテキスト表。出力の形式。 |
| **Inv-1〜7** | 「**これだけは絶対に崩さない**」と決めた性質。詳しくは「決定性と不変条件」を参照。 |

---

## 必要環境

- Python **3.12**（`requires-python = ">=3.12"`）
- モダン Linux / glibc ≥ 2.17（同梱 wheel は cp312・`manylinux_2_17` の x86_64／aarch64 両アーキ。配備先 aarch64＝DGX Spark、開発/CI＝x86_64）
- 任意機能: `rg`（ripgrep）— 無い場合は該当テストが自動 skip

## インストール（オフライン再現）

リポジトリは `wheelhouse/`（全依存の固定版 wheel）と `requirements.lock`
（版＋sha256 ハッシュ固定）を同梱しており、ネット接続なしで再現インストールできる。

`wheelhouse/` は**多アーキ同梱**＝配備先 **aarch64（NVIDIA DGX Spark / DGX OS・Python 3.12）**
と開発/CI の **x86_64** の双方で同一手順が成立する（ネイティブ依存は両アーキの
wheel を、純Python依存は共通 wheel を収録。`pip` が実行プラットフォーム適合 wheel を
自動選択）。オフライン `-e .` のビルド分離用に `setuptools`/`wheel` も同梱済み。
依存ピボットの根拠は `docs/superpowers/plans/phase0-gate-result.md` の
「aarch64 再ベースライン記録」節（spec v10）。

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install --no-index --find-links wheelhouse --require-hashes -r requirements.lock
pip install --no-index --find-links wheelhouse -e .   # grep_analyzer 本体（src レイアウト）
```

`requirements.lock` は `wheelhouse/` の wheel から決定的に再生成できる:

```bash
python scripts/gen_requirements_lock.py   # リポジトリルートで実行
```

ネット接続環境での `wheelhouse/` 再取得手順は
`docs/superpowers/plans/phase0-gate-result.md` に記録。

## 使い方

```bash
python -m grep_analyzer \
  --input   <grepファイル群のディレクトリ> \
  --output  <出力ディレクトリ> \
  --source-root <ソース木のルート>
```

- `--input`: キーワードごとの `*.grep`（`path:lineno:content` 行）を置いたディレクトリ
- `--output`: キーワードごとの TSV・`*.manifest.json`・`diagnostics.txt` を生成
- `--source-root`: ヒット箇所の実ソースを解決するルート

### 主なオプション（Phase 3 で追加された運用系を中心に）

| フラグ | 既定 | 説明 |
|---|---|---|
| `--resume` | off | 完了済みキーワードをスキップ（manifest 5 条件で完了判定） |
| `--output-encoding` | `utf-8-sig` | 出力 TSV のエンコーディング |
| `--encoding-fallback` | `cp932,euc-jp,latin-1` | 入力/ソース復号のフォールバック鎖（空指定は既定鎖へ復帰） |
| `--max-rows-per-part` | `1048575` | 超過時 `<kw>.partNN.tsv` へ Excel 互換分割 |
| `--diagnostics-detail-limit` | `1000` | diagnostics 詳細の縮約上限（`0` で無制限＝従来同値） |
| `--memory-limit` | なし | 決定的メモリ近似に基づく degrade トリガ（MB） |
| `--jobs` | `1` | 走査並列度 |

全フラグは `python -m grep_analyzer --help` を参照。

## 出力物

- `<keyword>.tsv` — 安定ソート済みヒット（既定は単一ファイル、`utf-8-sig` BOM）
- `<keyword>.partNN.tsv` — 行数が上限超過時の分割（連結＝単一と内容同値）
- `<keyword>.manifest.json` — 行数・`data_sha256`・版・定数等（`--resume` 完了判定の根拠）
- `diagnostics.txt` — 非致命診断のサマリ＋詳細（§8.4 全件性カテゴリは縮約免除）

## 決定性と不変条件

- **Inv-1**: 既定起動（`--resume` 無・既定エンコーディング）は従来出力と **1 バイト不変**
- **Inv-5**: part 分割は内容透過（再構成＝書込側と同一の正規化関数）
- **Inv-6**: `--diagnostics-detail-limit 0` は従来 `render()` とバイト同値
- **Inv-7**: `--resume` 冪等（同一条件下で有/無の最終出力は同値）

## テスト

```bash
pytest -q                 # 既定ゲート（perf は非ゲートで自動 skip）
pytest -q -m perf         # 性能ベースライン／_ITEMS_PER_MB 較正／オフライン再現スモーク
pytest tests/golden -q    # golden 14（既定出力 byte 不変の回帰アンカー）
```

- `@pytest.mark.perf`: CI を止めない非ゲート計測（既定除外）
- `@pytest.mark.requires_ripgrep`: `rg` 不在環境では自動 skip

## プロジェクト構成

```
src/grep_analyzer/   本体（pipeline / fixedpoint / output_writer / resume / encoding ...）
tests/unit           ユニット
tests/integration    結合（pipeline・encoding 配線・Inv-1 能動ガード ...）
tests/golden         既定出力 byte 不変の回帰
tests/perf           非ゲート perf＋合成コーパス生成
scripts/             requirements.lock 生成
wheelhouse/          オフライン再現用の固定版 wheel（同梱）
docs/superpowers/    設計 spec・実装計画・ゲート記録
```

## 設計ドキュメント

- マスター設計: `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`
- Phase 3 設計: `docs/superpowers/specs/2026-05-17-grep-analyzer-phase3-design.md`
- 実装計画: `docs/superpowers/plans/2026-05-17-grep-analyzer-phase3.md`
- ゲート/完了記録: `docs/superpowers/plans/phase0-gate-result.md`
- perf 較正レポート: `docs/superpowers/plans/phase3-perf-report.md`
