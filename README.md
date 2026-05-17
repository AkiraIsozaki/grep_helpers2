# grep_analyzer

grep 結果を言語別に分類し、**決定的（deterministic）**な TSV を出力するツール。
同一入力・同一オプションに対し常にバイト同一の結果を返すことを設計不変条件とする。

- Python 3.12 / 標準ライブラリ中心 + tree-sitter・chardet・pyahocorasick
- 大規模ソース木に対する直接ヒット抽出 ＋ 不動点による間接（indirect）参照追跡
- オフライン再現ビルド対応（`wheelhouse/` + `requirements.lock` を同梱）

---

## 用語集

このツール特有の用語を、コード上の意味で簡潔に説明する。

| 用語 | 意味 |
|---|---|
| **不動点（fixpoint）** | grep の直接ヒットから出発し、参照先シンボル（定数/変数/getter/setter）を辿って新ヒットを足す処理を、**集合がもう増えなくなる（= 変化しない＝不動点）まで反復**すること。間接参照を網羅するための収束計算。 |
| **direct ヒット** | 入力 `*.grep` が直接指している箇所（`path:lineno:content`）。 |
| **indirect ヒット** | direct から不動点反復でシンボルを辿って到達した参照箇所。 |
| **決定的（deterministic）** | 同一入力・同一オプションなら実行のたびに出力が**バイト単位で同一**であること。本ツールの中核要件。 |
| **golden テスト** | 期待出力を固定ファイルとして保存し、出力が 1 バイトでも変われば失敗する回帰テスト。既定出力 byte 不変（Inv-1）の安全網。 |
| **manifest** | `<keyword>.manifest.json`。行数・`data_sha256`・ツール版・定数等を記録。`--resume` の完了判定（5 条件）の根拠。 |
| **part 分割** | 1 キーワードの行数が `--max-rows-per-part` を超えたとき `<keyword>.partNN.tsv` に分けること（Excel 行上限互換）。全 part を連結すると単一出力と内容同値。 |
| **正規化（canonical blob）** | 書込側と `--resume` 完了判定側が**共有する唯一のバイト列化**。part 分割境界に依存せず同一ハッシュになる。 |
| **§8.4 全件性 / 縮約** | diagnostics の詳細行を上限で切り詰めること（縮約）。ただし網羅が必要な一部カテゴリ（§8.4 全件性カテゴリ・`prov_*`）は縮約免除＝常に全件出力。 |
| **degrade / `_ITEMS_PER_MB`** | `--memory-limit` 指定時、RSS 実測でなく**決定的なアイテム数近似**でメモリを見積もり、超過時に分割等へ縮退する判断。決定性のため近似定数を使う。 |
| **decode フォールバック鎖** | 入力/ソース復号の試行順「utf-8 厳格 → chardet 検出 → フォールバック候補列 → 末尾 +replace」の候補列（`--encoding-fallback`）。 |
| **seed / hop** | seed = 探索の起点（direct ヒット）。hop = 不動点反復の 1 段（参照を 1 ホップ辿る）。 |
| **TSV** | タブ区切り値。本ツールの出力フォーマット。 |
| **Inv-1〜7** | 設計不変条件。代表は本書「決定性と不変条件」節を参照。 |

---

## 必要環境

- Python **3.12**（`requires-python = ">=3.12"`）
- モダン Linux / glibc ≥ 2.17（同梱 wheel は cp312・`manylinux_2_17_x86_64`）
- 任意機能: `rg`（ripgrep）— 無い場合は該当テストが自動 skip

## インストール（オフライン再現）

リポジトリは `wheelhouse/`（全依存の固定版 wheel）と `requirements.lock`
（版＋sha256 ハッシュ固定）を同梱しており、ネット接続なしで再現インストールできる。

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
