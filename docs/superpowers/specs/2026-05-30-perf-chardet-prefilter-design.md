# 60GB 非UTF-8 コーパスの性能改善（chardet メモ化 / rg 同梱 / prefilter 既定ON）設計

- 日付: 2026-05-30
- 正本 spec: `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`（§8.1/§8.2/§8.4/§9/§10.1/§10.3/§11/§15）
- 関連既存計画: `docs/superpowers/plans/2026-05-24-perf-fixedpoint-caching.md`（#1/#2/#5/#6 実装済・#3 撤回）
- 方針: **option A＝出力の TSV 行はバイト不変を厳守**した上での性能改善

---

## 1. 背景と根本原因（計測で確定）

60GB 規模（Java 多め・**ほとんどが非UTF-8**＝cp932/euc-jp）のソース木に対し、本ツールが1日たっても完走しない。

### 1.1 ボトルネックの構造

処理は2フェーズ:

1. **direct フェーズ**（`pipeline.py`）— grep 出力に出るファイルだけを読む。grep 行数に比例。軽い。
2. **不動点 indirect フェーズ**（`fixedpoint/__init__.py`）— direct ヒットから記号を抽出し、**ソース木全体を再スキャン**して間接参照を多ホップ追跡（最大 `max_depth=10`）。

`run_fixedpoint` のループは **毎ホップ `scan_files = files`（=全ファイル）を走査**する（`use_ripgrep` 既定 False ＝ prefilter 無効）。各ファイルで `_scan_one` が「ディスク再読込 → `decode_bytes` 復号 → 全行 automaton 走査 →（Java等は）tree-sitter パース」を実行。

### 1.2 真の律速＝chardet（計測値）

`encoding.py:decode_bytes` は **UTF-8 厳格デコードに失敗したファイルだけ** `chardet.detect()` を全バイトに対し実行する。**非UTF-8が大半**だと全ファイルが毎ホップ chardet を通る。

実測（本リポの開発機）:

| 処理 | 速度 |
|---|---|
| `chardet.detect`（非UTF-8検出） | **約 0.1 MB/s** |
| 既知コーデックでの strict 復号（cp932 等） | 約 92 MB/s（**約1200倍速**） |

投影: 30GB 相当を chardet だけで走らせると **1ホップ約108時間**。これ単独で「1日で終わらない」を説明する。grep 行数は支配項ではなく、1行入力でも結局は数日級になる。

### 1.3 既存キャッシュが60GBで無力な理由

`_FileCache`（`_scan.py`）は **復号テキスト本体**を予算 **64MB** で LRU 保持する。対する作業集合は60GB＝ヒット率約0.1%で、**ホップ間再利用は実質ゼロ**。毎ホップ全ファイルを再 chardet している。

### 1.4 過去の #3 撤回判断は本番 regime 非代表

`#3`（rg prefilter 既定ON）は「合成コーパスで実測利得ゼロ」を理由に撤回され opt-in 化された。しかし perf コーパス生成 `tests/perf/corpus_gen.py` は **全ファイルを `"utf-8"` で生成**しており、**chardet が一度も発火しない**。すなわち測っていたのは「生read＋automaton＋tree-sitter」のみで、prefilter のサブプロセス起動コストが相対的に勝って「利得ゼロ」に見えただけ。**本番（非UTF-8・chardet律速）を代表しないベンチに基づく判断**であり、#3 の再導入は正当。

---

## 2. 目標と制約

- **目標**: 60GB・キーワード 30〜35 個・非UTF-8 主体で **1時間以内に完走**。
- **不変条件**: 同一入力＋同一オプションで **TSV 行はバイト不変**（既存 Inv-3 継承）。診断 `diagnostics.txt` は §6 の通り一部変動を許容。
- **配備先**: aarch64 / Python 3.12 / **オフライン**。glibc は新しめ（公式 gnu バイナリ可）。wheelhouse による offline 再現ビルド方針を踏襲。

---

## 3. 解決策の三本柱

1. **encoding 検出のメモ化**（chardet を「全ファイル×全hop×全keyword」→「ユニークファイル×1回」へ）。
2. **rg バイナリ同梱**（オフライン）＋解決経路の拡張。
3. **#3 prefilter 既定ON の再導入**（コーパス総バイト閾値でゲート）。

加えて運用ガイダンスとして **`--jobs $(nproc)`** で初回検出・走査を並列化する。

---

## 4. アーキテクチャとデータフロー

### 4.1 encoding メモ（新コンポーネント）

`abspath(str) → (enc, replaced)` の辞書。**`decode_bytes` の純粋メモ化**。

```python
def decode_with_memo(memo, abspath, raw, fallback):
    hit = memo.get(abspath)
    if hit is not None:                       # 既知 → C速度。chardet を呼ばない
        enc, replaced = hit
        text = raw.decode(enc, errors="replace" if replaced else "strict")
        return text, enc, replaced
    text, enc, replaced = decode_bytes(raw, fallback)   # 初回のみ chardet 経路
    memo[abspath] = (enc, replaced)
    return text, enc, replaced
```

`raw.decode(enc, …)` は `decode_bytes` の返す text とバイト同値（同一 bytes＋同一 codec＋同一 errors ポリシー＝replaced フラグで分岐）。→ 検出は「ユニークファイル×1回」に収束。

### 4.2 メモを通す3経路

1. **indirect スキャン（本丸）** — `_scan_one`/`_read_meta` がメモ参照。
   - 直列: `scan_hop` にメモを渡す。
   - 並列: worker 引数タプルに per-file 既知 enc を追加（`(relpath, abspath, sig, sym_path, known_enc)`）。worker は既知なら chardet スキップ、未知なら従来通り検出し enc を戻り値で返す（既存戻り値に enc あり）。**初回検出は worker 並列で捌ける**。
2. **direct スキャン** — `pipeline.run` の `decode_bytes(target.read_bytes(), fb)` を同メモ経由に。35 keyword で同一ファイルが何度 direct ヒットしても chardet は1回。
3. **keyword 横断共有** — 共有メモを `pipeline.run` レベルに1つ生成し、全 `.grep` の direct/indirect に渡して共有する。encoding はキーワード非依存＝共有しても各 hit の `encoding` 列は同値（出力不変）。

#### キー設計（既存 `encoding_of` との関係）

- **共有メモのキーは `abspath`（str）**。`_scan_one` が手元に持つのも `_FileCache` のキーも `abspath` で統一されているため。
- 既存 `ChaseState.encoding_of`（**`relpath` キー**・`absorb_results` が出力用に populate）は **役割を変えず残す**。これは indirect hit の `encoding` 列を出すための「出力ビュー」であり、本設計では触らない。
- すなわち「スキャン時の chardet 回避」は共有メモ（abspath）が担い、「出力の encoding 列」は従来どおり `encoding_of`（relpath）が担う。両者は同一の `(enc, replaced)` 値を保持する別ビューで、`source_root` 固定下で abspath↔relpath は 1:1 ＝整合。run_fixedpoint は共有メモを **scan への入力として渡すだけ**で、`encoding_of` への書き戻し経路は現状不変。

> 既存 `_FileCache`（テキスト LRU・64MB）は本メモと直交。小規模・同一hop内の再read 抑止に残置（除去はスコープ外）。

### 4.3 rg 同梱と解決

- 配置: `vendor/ripgrep/{aarch64,x86_64}/rg`（公式 gnu バイナリ・**バージョン固定**・`LICENSE` 同梱・`.gitattributes` に `binary`・実行ビット）。x86_64 は dev/CI（golden・`requires_ripgrep`）用。
- `ripgrep.py` の解決を拡張: 現状 `_RG = shutil.which("rg")` のみ → **`GREP_ANALYZER_RG`(env) → 同梱 `vendor/ripgrep/{platform.machine()}/rg` → `shutil.which("rg")`** の順。

### 4.4 並列の決定性

worker が返す `enc` は bytes の純関数。メモ状態（chardet経由か既知codec経由か）に関わらず `pass_results` は同値。**完了順・jobs 数・prefilter 有無に非依存で TSV 行不変**（Inv-3 整合）。

---

## 5. prefilter 既定ON の閾値（golden を割らない設計）

- **rg 解決可能 かつ コーパス総バイト ≥ 閾値（既定 1 GiB・`--ripgrep-threshold-bytes` で可変）** のときだけ既定ON。`--use-ripgrep`/`--no-use-ripgrep` で明示上書き。rg 不在は常に OFF。
- 総バイトは `collect_files` の walk 中に既に `stat` 済み＝追加コストゼロで集計。閾値判定自体も決定的。
- 効果: **golden/小規模は従来通り OFF＝diagnostics 含め完全バイト不変（既存テスト無傷）**、本番60GBは自動ON。

> 代替: 閾値なし「rg検出→即ON」＋golden 側 `--no-use-ripgrep` 明示。golden 多数の改変が要るため**閾値案を採用**。

---

## 6. 出力不変の証明と診断の扱い

### 6.1 TSV 行のバイト不変

- **encoding メモ**: `decode_with_memo` は `decode_bytes` の純粋メモ化。同一 bytes に常に同一 `(text, enc, replaced)`＝全 Hit 列が同値。構造的に不変。
- **prefilter 既定ON**: `ripgrep.py` の不変条件を継承。除外 relpath は「追跡記号を生バイトとして部分文字列にすら持たない」→ automaton 0 ヒット確定 → Hit 行を生まない。非ASCII記号を含む hop は自動無効化（`ripgrep.py:41`）。ASCII 記号は cp932/euc-jp/latin-1/utf-8 でバイト同一＝安全な上位集合。→ on/off で TSV 行バイト一致。

### 6.2 診断（diagnostics.txt）

- prefilter ON では記号を含まないファイルが走査されず、そのファイル由来の `decode_replaced`/`unsupported_shebang`/`missing_source` 等が出なくなり得る。
- **方針: TSV 行のみ不変を保証**。診断のこの差分は「キーワードの影響範囲に寄与しない無関係ファイルの符号化ノイズが減るだけ」＝適切として **spec §8.4（既知限界）に明記**。
- 担保: **prefilter on/off で TSV 行がバイト一致する回帰テスト**を追加（診断は対象外と明示）。

---

## 7. テスト方針

流儀: 古典学派TDD・日本語テスト名・golden バイト一致・`requires_ripgrep`/`perf` マーカー。各 production 変更は **golden 全件バイト一致を完了条件**。

### 単体・統合（`tests/integration/`）

1. `decode_with_memo` が `decode_bytes` とバイト同値（utf-8/cp932/euc-jp/latin-1＋`replaced=True` 各経路）。
2. chardet を spy し、同一ファイル2回目以降は**呼ばれない**。
3. keyword 横断共有: 複数 `.grep` で同一ファイル登場でも chardet は1回（spy）。
4. 並列授受: `jobs>1` で既知 enc が worker に渡り chardet スキップ、出力が `jobs=1` とバイト一致。
5. rg 解決順: `GREP_ANALYZER_RG`(env) > 同梱 `{machine}/rg` > `shutil.which` と arch 選択（monkeypatch）。
6. prefilter 閾値: 総バイト ≥ 閾値で自動ON・未満でOFF・明示フラグが上書き・rg不在は常にOFF。

### 不変条件（`requires_ripgrep`）

7. prefilter on/off で TSV 行バイト一致（診断対象外）。非ASCII記号 hop の自動無効化を含む。
8. golden 全件バイト一致が無傷（閾値で小規模 OFF 据置）。

### perf（`perf`・非ゲート）— 撤回誤りの再発防御

9. **非UTF-8（cp932）perf コーパスを追加**し chardet 呼び出し回数／dt を計測。encoding メモ＋prefilter の本番 regime での利得を可視化・固定。「合成ベンチで利得ゼロ→撤回」の再発を防ぐ恒久ガード。

---

## 8. 実装範囲（変更ファイル概略）

- `src/grep_analyzer/encoding.py`: `decode_with_memo` 追加（`decode_bytes` は不変）。
- `src/grep_analyzer/fixedpoint/_scan.py`: `_scan_one`/`_read_meta`/`scan_hop` にメモ授受。worker 引数に `known_enc`。
- `src/grep_analyzer/fixedpoint/__init__.py`: `run_fixedpoint` が共有メモ（abspath キー）を受け取り `scan_hop` へ橋渡し（`encoding_of` への書き戻しは現状不変）。
- `src/grep_analyzer/pipeline.py`: メモ生成（run 単位・keyword 横断）と direct 経路の接続。
- `src/grep_analyzer/ripgrep.py`: 解決経路を env→同梱→PATH に拡張。
- `src/grep_analyzer/cli.py`: prefilter 既定ON（閾値ゲート）・`--no-use-ripgrep`・`--ripgrep-threshold-bytes`。
- `vendor/ripgrep/{aarch64,x86_64}/rg` ＋ `LICENSE`、`.gitattributes`。
- `tests/integration/`・`tests/perf/`・golden（小規模は不変・新規ケースのみ）。
- spec §8.4 注記、`tests/perf` の非代表性是正の記録。

---

## 9. 計測チェックポイントと次段（スコープ外）

- 三本柱適用後、**実コーパス（または非UTF-8 perf コーパス）で chardet 呼び出し回数・dt を計測**し1時間目標を確認。
- 初回検出が候補ファイル集合のサイズで律速し目標未達なら、follow-up として:
  - (a) **encoding メモのディスク永続化**（再実行で chardet ゼロ・mtime/size キーで無効化）。
  - (b) **chardet 置換**（既知環境前提で strict フォールバック鎖 or cchardet・**出力ベースライン更新＝spec 改定とレビュー前提**＝本設計の範囲外）。
