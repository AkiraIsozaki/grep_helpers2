# grep_analyzer Phase 3 設計（規模・運用）

- 日付: 2026-05-17（v4: 3並行批判レビュー 第1〜3ラウンド反映・3軸収束＝writing-plans 着手可）
- 位置づけ: マスター設計書 `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`（**source of truth**）の §15「フェーズ3（規模・運用）」を実装に落とす**従属設計**。本書は writing-plans（Phase 3 実装計画）の入力。マスター spec と齟齬がある場合は **マスター spec が優先**。
- 前提: Phase 0/1/1.5/2a/2b 完了（`phase0-gate-result.md`）。現状 `python -m pytest -q` = **167 passed**（rg 環境受入条件充足済・golden 14・既存 130 + Phase 2b 33 + rg 4）。作業ブランチは main 直接（ソロプロジェクト）。
- **出荷前提（spec §13 R6 / §4.2 G1 / §2.1）**: §4.2 G1 は writing-plans 着手前のブロッキング前提。`phase0-gate-result.md` で **G1 = PASS**（x86_64 / glibc 2.36 / cp312、§2.1 要確定欄充足、wheel オフライン取得実証済）。ただし G1 は開発ボックスを稼働先（spec §2.1「モダンLinux・オフライン」）と**同等環境とみなした**確定であり、採用 platform タグは `manylinux_2_17_x86_64`（glibc 2.17+ 互換）。**稼働先実機が glibc < 2.17 ／ musl の場合は spec §13 R6（High）・§4.2 が再検証を要求**＝その範囲では Phase 3 完了をもってしても「v1 出荷可能」は条件付き（稼働先が想定「モダンLinux」である限り出荷可）。本書 §8 の v1 出荷判定はこの前提を明記する。
- 構造決定: Phase 2 は 2a/2b に分割したが、**Phase 3 は単一計画**（ユーザー決定）。6 ワークストリーム（WS1〜6）を1つの spec/計画で扱う。

---

## 1. 目的とスコープ

Phase 3 完了をもって spec の残 v1 正本（§4.1 / §8.2 perf / §9 規模分割 / §10.1 出力encoding / §10.3 縮約・原子性・resume / §10.4 CLI / §11 / §15 フェーズ3）を全充足し、上記**出荷前提（稼働先＝想定モダンLinux）の下で v1 出荷可能**にする。

**スコープ内（6 ワークストリーム）**:

| WS | 項目 | spec 根拠 |
|---|---|---|
| WS1 | `--resume` 原子性 ＋ kw 毎 manifest | §10.3 L251-252 |
| WS2 | 規模分割 `<keyword>.partNN.tsv` | §9 L231 |
| WS3 | diagnostics §10.3 縮約（§8.4 全件性免除） | §10.3 L250・§8.4 |
| WS4 | `--output-encoding` / `--encoding-fallback` 配線 | §10.1 L241 / §10.4 L261-265 |
| WS5 | `requirements.lock`（版＋ハッシュ固定） | §4.1 |
| WS6 | 60GB perf ベースライン ＋ `_ITEMS_PER_MB` 実バイト較正 | §8.2 L163 ＋ §11 |

**スコープ外（v1 受容リスク・spec 準拠）**:

- キーワード**内**チェックポイント resume（spec §10.3 L252 / §14 L311 = v1 スコープ外・受容リスク）。v1 は **キーワード単位 resume** のみ。
- 動的「プロジェクト頻出トップN」ストップリスト（spec §8.3 L171 / §14 L310 将来）。
- 実 60GB コーパスでの実測（環境に実コーパス無し）。perf は spec §11 通り**非ゲート**＝合成コーパスでスケール特性を計測しモデル外挿（実コーパス実測は実データ保有者が別途）。

---

## 2. アーキテクチャ

**採用方針 A（出力確定モジュール集約）**。WS2/WS1(manifest)/WS4 は「最終 TSV バイトをどうディスクに原子確定するか」という単一トランザクションの関心であり、1 モジュールに集約して決定性論証を 1 箇所に閉じる。

```
新規:
  src/grep_analyzer/output_writer.py   # 安定ソート→part分割→各part原子書込→manifest原子確定→encoding選択
  src/grep_analyzer/resume.py          # manifest を読み「完了 kw」を判定
  tests/perf/corpus_gen.py             # 決定的・サイズ可変な合成ソース木生成
  tests/perf/test_perf.py              # @pytest.mark.perf 非ゲート計測
  requirements.lock                    # wheelhouse 由来の == + --hash 固定（成果物）

拡張:
  src/grep_analyzer/diagnostics.py     # render(detail_limit, exempt) で §10.3 縮約
  src/grep_analyzer/pipeline.py        # resume スキップ判定 → output_writer.finalize 呼び出しへ差し替え
  src/grep_analyzer/cli.py             # --resume / --output-encoding / --encoding-fallback /
                                       #   --max-rows-per-part / --diagnostics-detail-limit
  src/grep_analyzer/fixedpoint.py (EngineOptions)  # 上記オプションの保持（実体は fixedpoint.py:33 の EngineOptions・末尾既定追加・後方互換。pipeline は from fixedpoint import EngineOptions）
  tests/conftest.py                    # pytest_collection_modifyitems に perf 除外分岐を追加（§7・WS6）

不変（変更しない決定的コア）:
  fixedpoint / chase / classify / walk / stoplist / automaton / provenance /
  ripgrep / budget(関数) / spill / progress / ingest / encoding.decode_bytes
  ※ WS6 は budget.py の定数 _ITEMS_PER_MB を「一度だけ」較正（関数ロジック不変）。
```

`output_writer` は既存 `tsv.write_tsv` の原子プリミティブ（`tempfile.mkstemp` → `write` → `flush` → `os.fsync` → `os.replace`、例外時 tmp 削除＝`tsv.py:26-36`）を**内部再利用**する。

**`tsv.write_tsv` の去就（実装計画で一意化／制約付き）**: 単一ファイル経路の薄いラッパとして残すか、`output_writer` に吸収し pipeline 呼び出し側（`pipeline.py:80` の唯一の出力経路）を差し替えるかは実装計画で一意化する。**ただしどちらを選んでも次を制約として満たす**: (a) Inv-1（既定起動で既存 golden 14・既存 167 が 1 バイト不変）、(b) spec §10.3 L251 の原子プリミティブ（`mkstemp→write→flush→os.fsync→os.replace`、例外時 tmp 削除）を逸脱しない、(c) 単一ファイル経路と part 経路の原子確定論証が同一モジュール内に閉じる（方針 A の主旨）。

---

## 3. データフロー（pipeline.run の kw ループ）

```
for grep_file in sorted(input_dir.glob("*.grep")):       # kw ループは sorted＝決定的
    keyword = grep_file.stem
    if opts.resume and resume.is_complete(output_dir, keyword, opts):
        diag.add("resume_skipped", keyword)        # 非 §8.4・縮約対象（§4 WS3 M 参照）
        continue
    hits  = ... (既存: direct 抽出)
    indirect = run_fixedpoint(hits, ..., files=files)   # 既存・不変
    output_writer.finalize(output_dir, keyword, hits + indirect, opts)
# ループ後
(output_dir / "diagnostics.txt").write_text(
    diag.render(detail_limit=opts.diagnostics_detail_limit,
                exempt=SECTION_8_4_CATEGORIES),
    encoding="utf-8")          # diagnostics.txt は常に utf-8（TSV とは別系）
return 0
```

`output_writer.finalize(out_dir, keyword, rows, opts)` の**確定手順（順序を規定）**:

1. **整列＋正規データ列の確定**: `ordered = sorted(rows, key=model.sort_key)`（既存の決定的全順序）。各セルは既存 `tsv._sanitize` 規則でタブ/改行/CR を空白化。**唯一の正規化関数 `_canonical_data_blob`** を定義する（書込側・完了判定・Inv-5・テストが全て本関数を共有＝正規形の出所を一意化）:
   - 入力＝データ行列（`ordered` の各 `Hit.to_row()` を `_sanitize` 適用後 `"\t".join` した行＝`tsv.py:22` と**同一バイト列**。ヘッダ・BOM を含まない）。
   - 出力＝`"\n".join(sanitized_data_lines)` を **`"utf-8"`（BOM 無 codec）** で encode したバイト列（**末尾改行を含めない**・改行は LF 固定・`split("\n")` の厳密逆）。`data_sha256 = sha256(_canonical_data_blob(ordered)).hexdigest()`。
   - **part 群からの再構成は逐語同一手続き**: 各 part を `manifest.encoding` で個別 decode → 各 part 先頭 BOM 除去（`utf-8-sig` 時）→ 各 part 先頭ヘッダ 1 行除去 → 各 part を `text.rstrip("\n").split("\n")`（書込時付与の末尾 `\n` 由来の末尾空要素のみ除去。データ行内に LF は `_sanitize` 済ゆえ存在しない）でデータ行列化 → 全 part のデータ行を順に連結 → 同じ `_canonical_data_blob`。`splitlines()` は使わない（`_sanitize` が除去しない U+2028/U+0085/U+000B/U+000C/U+001C-1E 等を `splitlines()` は行分割するため `"\n".join` の逆にならない＝`split("\n")` に固定）。`n == 0`（ヒット 0 件）は単一ファイルがヘッダ 1 行＋末尾 `\n` のみ → データ行 0 → blob は空バイト列（一意・決定的）。
2. **規模パラメタを全 part 書込前に確定**（リネーム経路を設計上禁止＝確定名で直接書く）:
   - データ行数 `n = len(ordered)`（ファイル再パースではなく内部カウント。**`n` の唯一の定義**）。
   - `L = opts.max_rows_per_part`。
   - `nparts = 1 if n <= L else ceil(n / L)`（∴ `n == L` は単一、`n == 0` も単一、`n` が `L` の整数倍でも空 part を作らない）。
   - 桁幅 `width = max(2, len(str(nparts)))`（例: `nparts=3 → width 2 → part01..part03`、`nparts=9 → width 2 → part01..part09`、`nparts=100 → width 3 → part001..part100`、`nparts=150 → width 3 → part001..part150`）。`nparts` も `width` も `n` の決定的関数ゆえ命名は決定的。
3. **part 群を確定名で原子書込**: `nparts == 1` → 単一 `<kw>.tsv`（part サフィックス無＝Inv-1 / 命名規約）。`nparts > 1` → チャンク `i = ordered[i*L : (i+1)*L]`（`i in range(nparts)`）を `<kw>.part{ i+1 :0{width}}.tsv` に。各 part = ヘッダ行（`TSV_COLUMNS`）＋当該チャンクのデータ行。各 part を `mkstemp→write→flush→os.fsync→os.replace` で原子確定（既存プリミティブ。**確定名で書く＝書込後リネームは行わない**）。
4. **manifest を最後に原子確定**: 全 part 確定後、`<kw>.manifest.json` を `mkstemp→write→flush→os.fsync→os.replace` で原子確定し、続けて**親ディレクトリを fsync**（同一親 dir の全 part＋manifest のディレクトリエントリを一括永続化＝rename の耐クラッシュ永続化・spec §10.3 原子性）。
5. **孤児 part のクリーンアップ（manifest 確定後＝耐クラッシュ順序を保持）**: manifest 確定**後に**、当該 kw の `<kw>.tsv` / `<kw>.part*.tsv` のうち**新 manifest の `parts[].name` に無いもの**を削除する（`--resume` 無の再処理や `--max-rows-per-part` 変更で `nparts`/`width` が変わり旧命名の part が残留するのを除去＝同一入力→output_dir 内容も決定的に）。**順序が重要**: 「新 part 群＋manifest を原子確定 → その後で旧孤児を削除」。クリーンアップ途中クラッシュでも manifest は正しい新 parts のみ列挙ゆえ resume 正当性は不変。**有効な出力を新出力出現前に破壊しない**。**既知の挙動**: 手順4 確定後・手順5 完了前にクラッシュし以後 `--resume` で再実行すると、当該 kw は完了判定が真でスキップされ手順5 に再到達しないため旧孤児 part が残留しうる（manifest と新 parts は正しく resume 正当性・決定性は不変＝spec §10.3「rename 済みのみ完了」を満たす。孤児は `--resume` 無の再処理で掃ける）。出力ディレクトリの完全クリーン性を要する運用は `--resume` 無実行で担保。
6. **規模警告**: `nparts > 1` のとき `diag.add("scale_split", f"{keyword}\t{n} rows\t{nparts} parts")`（spec §9「分割＋diagnostics 警告」）。

---

## 4. 各ワークストリームの確定仕様

### WS1: `--resume` 原子性 ＋ kw 毎 manifest

- **manifest 形式**: `<keyword>.manifest.json`。UTF-8、`json.dumps(..., sort_keys=True, ensure_ascii=False, separators=(",", ":"))` で**キー昇順・決定的**。**タイムスタンプ等の非決定要素は含めない**（テスト容易性・golden 安定）。
- **manifest スキーマ**:
  ```json
  {"schema_version":1,
   "keyword":"<kw>",
   "encoding":"<opts.output_encoding 実効値（既定 utf-8-sig・例 cp932）>",
   "total_rows":<データ行数 n>,
   "data_sha256":"<_canonical_data_blob(ordered) の sha256（§3 手順1 で一意定義）>",
   "tool_version":"<grep_analyzer 版>",
   "items_per_mb":<budget._ITEMS_PER_MB 実効値>,
   "parts":[{"name":"<kw>.tsv","rows":<n>}],
   "tool":"grep_analyzer","spec_phase":"3"}
  ```
  - 単一ファイル kw も `parts` 1 要素（`name` = `<kw>.tsv`）で manifest を発行（**規則統一**＝part 群と単一を同一判定路で扱う）。
  - `data_sha256` = **§3 手順1 の `_canonical_data_blob(ordered)` の sha256**（ヘッダ・BOM 非含、サニタイズ後タブ結合データ行を LF 連結・末尾改行無・`"utf-8"` codec。part 分割境界に依らず単一定義＝決定的・golden 安定・タイムスタンプ非依存）。書込側定義と完了判定の再構成は**同一関数 `_canonical_data_blob` を共有**し、`split("\n")` ベース（`splitlines()` 不使用）で正規形を一意化。
  - `tool_version` / `items_per_mb` は **resume 冪等の前提照合用**（§5 Inv-7・§6）。WS6 較正で `_ITEMS_PER_MB` が変わると `items_per_mb` 不一致 → 未完了扱い（保守的再処理）。
- **完了判定** `resume.is_complete(out, kw, opts)`: 次を**全て**満たすとき完了、いずれか欠落/不一致なら未完了（部分 part 群・部分書込・別版生成物を完了誤認しない＝spec §10.3「rename 済みのみ完了」）:
  1. `<kw>.manifest.json` が存在し JSON 妥当。
  2. `parts` の全ファイルが実在。
  3. 各 part の**データ行数**（後述手続き）が manifest 記載 `rows` と一致。
  4. **§3 手順1 の `_canonical_data_blob` を part 群から再構成**した sha256 が manifest `data_sha256` と一致（書込側と**同一関数**で算出＝正規形一致が論証上接続。**Inv-7: resume スキップ＝現コードでの再生成と同一バイトの保証**。行数一致のみでは内容同一を保証しないため）。
  5. `tool_version` が現行と一致 ∧ `items_per_mb` が現行 `budget._ITEMS_PER_MB` と一致（較正版またぎを保守的に未完了扱い）。
  - **データ行数のカウント手続き**（曖昧排除・`_canonical_data_blob` と同一の行抽出を再利用）: part ファイルを `manifest.encoding` で decode → 先頭 BOM 除去（`utf-8-sig` 時）→ `text.rstrip("\n").split("\n")`（`splitlines()` 不使用） → 先頭 1 行（ヘッダ）を除いた残り要素数。`n == 0`（ヒット 0 件）の単一ファイルは「ヘッダ 1 行のみ＋末尾 `\n`」→ `rstrip("\n").split("\n")` = `["header"]` → ヘッダ除去後 0 ＝データ行数 0。
- **`--resume` 挙動**: 指定時のみ完了 kw をスキップ（`resume_skipped` 診断）。無指定時は全 kw を再処理（既存ファイルは原子上書き）。
- **耐クラッシュ（クラッシュタイミング場合分け）**:
  - part 書込中（part の `os.replace` 前）にクラッシュ → tmp は残るが確定名ファイルは未出現 → manifest 未確定 → 未完了。
  - 一部 part の `os.replace` 後・manifest `os.replace` 前にクラッシュ → manifest 不在 → 未完了（条件1で落ちる）。
  - manifest `os.replace` 後・親 dir fsync 前にクラッシュ → ファイルシステムの rename 永続性は OS 保証（各 part・manifest は個別に `os.fsync` 済みでデータブロックは永続。親 dir fsync は**ディレクトリエントリ**の永続化）。仮に最後の親 fsync 前で一部 part のエントリが未永続なら当該 part 消失 → 条件2で未完了（保守的再処理）。**`os.fsync` 済みファイルのデータブロックがゼロ化する事象は前提としない**（per-part fsync が永続性を保証。rename 自体の OS 原子性・永続性は Phase 2b で確立した `tsv` 不変プリミティブの責務として継承）。
  - 以上より「manifest 存在 ∧ 完了判定 1〜5 全充足 ⇔ 当該 kw は現コードで再生成しても同一バイト」を保証。

### WS2: 規模分割 `<keyword>.partNN.tsv`

- **上限**: `opts.max_rows_per_part`（CLI `--max-rows-per-part`、**既定 1,048,575 データ行**）。各 part は「ヘッダ 1 行 ＋ 最大 1,048,575 データ行」= 最大 1,048,576 行 ＝ Excel 行上限内（spec §9「Excel 上限（約104万行）」を決定的定数化）。
- **part 数・命名・境界**: §3 手順2/3 で確定。`nparts = 1 if n <= L else ceil(n/L)`、`width = max(2, len(str(nparts)))`、チャンク `ordered[i*L:(i+1)*L]`。単一（`n ≤ L`）→ `<kw>.tsv`（**サフィックス無＝Inv-1**）。複数 → `<kw>.part{NN:0width}.tsv`。全 part 書込前に `nparts`/`width` を確定し**確定名で直接書く（リネーム禁止）**ため命名は決定的かつ原子的。
- **ヘッダ**: 各 part の先頭に `TSV_COLUMNS`（Excel で各 part 単体が開ける）。
- **BOM 規則（spec §9 L199 と実装の対応を明記）**: spec §9「既定 UTF-8 with BOM／非UTF-8 出力は BOM を付与しない」。実装規則は既存 `tsv` と同一＝**`output_encoding == "utf-8-sig"` のときのみ各 part 先頭に BOM**。`--output-encoding utf-8`（BOM 無し UTF-8 を明示）・非 UTF-8 は BOM 無（spec「非UTF-8 は BOM 付与しない」を `utf-8` 明示にも適用＝既存 `tsv.py` の `encode(encoding)` が `utf-8-sig` codec のみ BOM 付与する挙動を踏襲）。既定 `utf-8-sig` ＝ spec「UTF-8 with BOM 既定」。

### WS3: diagnostics §10.3 縮約（§8.4 全件性免除）

- `Diagnostics.render(detail_limit: int, exempt: frozenset[str])`:
  - `detail_limit == 0` → **無制限＝現行 `render()` と完全同一**。実装制約: `render(detail_limit=0, ...)` は**既存 `render()` と同一コードパスへ委譲**し、`detail_limit > 0` の縮約分岐のみを追加で分岐させる（別経路で再実装しない）。これにより既存 `tests/unit/test_diagnostics.py`（現行 `render()` の振る舞いを固定済）がそのまま `detail_limit=0` のアンカーになる（Inv: Phase 2b と byte 不変）。
  - `detail_limit > 0` → カテゴリ毎に、`cat in exempt`（§8.4 全件性カテゴリ）なら**全件出力（縮約しない）**。非 exempt かつ件数 > `detail_limit` なら **先頭 `detail_limit` 件（既存決定順）＋ 集約行** `f"{cat}\t(... {extra} more, {total} total)"` を出力。
  - summary（カテゴリ別件数）は常に**真の総数**（縮約しても件数サマリは全数を示す）。
- **`SECTION_8_4_CATEGORIES`**（縮約免除＝spec §8.4「唯一の正本・全件」が §10.3 縮約に優先・Phase 2b 既知境界(5)の論理継承）: `symbol_rejected`, `getter_setter_no_expand`, および `prov_*`（プレフィックス一致＝`prov_` で始まる全カテゴリ。実在は `prov_path_capped` / `prov_max_depth` / `prov_cycle_cut` の3つ・`provenance.py`/`fixedpoint.py` で確認）。
- **CLI** `--diagnostics-detail-limit`（**既定 1000**＝1 カテゴリあたり 1000 件、`0` で無制限）。
- **代表サンプル順の決定性論証**（一語で済ませず根拠を束ねる）: `Diagnostics.add()` は `self._detail[cat].append(message)`＝呼び出し順、`render()` はカテゴリ名 `sorted()`＋カテゴリ内 append 順保持（`diagnostics.py` で確認）。縮約対象（非 §8.4）カテゴリの append 順が決定的であることは、既確立の合成事実の継承による: (a) kw ループ `sorted(glob("*.grep"))`（`pipeline.py:43`）、(b) scan 結果のファイル順正規化（`fixedpoint.py` の `sorted(...)`）、(c) `_ingest` の決定的反復。実装は縮約を別経路（例 `Counter.most_common`）で書かず、`_detail[cat]` の append 列の先頭 `detail_limit` を取る（順序の出所を一意化）。
- **`resume_skipped` の扱い**: `resume_skipped` は §8.4 正本ではないため**縮約対象**（多数 kw スキップ時は先頭 `detail_limit`＋集約に丸まる。完了集合の完全な運用追跡は各 `<kw>.manifest.json` 群で別途可能ゆえ全件免除しない＝意思決定として明記）。

### WS4: `--output-encoding` / `--encoding-fallback` 配線

- `--output-encoding`（既定 `utf-8-sig`）→ `opts.output_encoding` → `output_writer` の全 part 書込に適用。BOM 規則は WS2 の通り。`errors="replace"`（既存・落とさない・spec §10.1）。
- `--encoding-fallback`（カンマ区切り・既定 `encoding.DEFAULT_FALLBACK` = `cp932,euc-jp,latin-1`）→ `opts.encoding_fallback`。spec §10.4 L265 通り **② フォールバック候補鎖のみを置換**し、**① chardet 検出は常に最初に実行**（`decode_bytes` 既存挙動を変えず引数で鎖だけ差し替え＝Phase 1.5 確立済 decode を不変利用）。
- **配線対象（行番号でなく decode 経路で規定＝実装シグネチャ変更に頑健）**: `DEFAULT_FALLBACK` ハードコードを `opts.encoding_fallback` 注入に置換すべき **decode 経路は 3 つ**（実コードで確認: `decode_bytes(..., DEFAULT_FALLBACK)` の呼び出しは `pipeline` 2 箇所と `fixedpoint._file_meta` 単一実装）:
  1. **入力 `.grep` decode**（`pipeline` 内・現 `pipeline.py:45`）。
  2. **direct ソース decode**（`pipeline` 内・現 `pipeline.py:58`、`target.read_bytes()`）。
  3. **indirect ソース decode**（`fixedpoint._file_meta` 内の単一 `decode_bytes`・現 `fixedpoint.py:61`）。`_file_meta` は現状 `fallback_chain` 引数を持たず `DEFAULT_FALLBACK` 直参照で、**呼出元 3 箇所**（現 `fixedpoint.py:75 / 170 / 313`）から到達する。配線は「`_file_meta` に fallback 鎖引数を追加し、3 呼出元へ `opts` の鎖を伝播」＝1 経路（行番号でなく `_file_meta` シグネチャで一意化）。
  - spec §10.1 L241「入力 `.grep` と走査対象ソース両方に適用」を満たし、direct/indirect で**同一鎖**（同一バイト列が経路で異なる encoding に分岐しない＝一貫性）。実装計画で **単一注入点**（`opts` から各 decode 経路へ鎖を渡す経路）を一意化する。行番号は実装で変動しうるため**規定は decode 経路名**で行い、`test_encoding_wiring` は行番号でなく観測挙動（§7 (a)(b)(c)）でアサートする。
- `diagnostics.txt` は常に utf-8 固定（ツールログ＝ §9 TSV 出力 encoding の対象外）。

### WS5: `requirements.lock`

- `wheelhouse/*.whl` の各 wheel について `pkg==version --hash=sha256:<sha256(wheel)>` を生成し `requirements.lock` を作成（spec §4.1「`==` 完全版ピン＋ハッシュ固定」）。`wheelhouse/` は実在（Phase 0/2 G1 で集約済・`.gitignore` 登録のため未コミット・配備時再生成持込）。`rg` は spec §4.1「任意」ゆえ lock 対象外。
- **テストを 2 本に分離（ゲート/非ゲートを明示）**:
  1. `test_requirements_lock_consistency`（**既定ゲート・高速・決定的**）: `requirements.lock` 各行の `--hash=sha256:` が `wheelhouse/*.whl` の実 `hashlib.sha256` と一致、かつ lock の pkg 集合 ⊇ `pyproject` の必須依存。純粋なファイル読み＋hashlib のみ＝失敗先行に明確に落ちる（lock 未作成時 `FileNotFoundError` で RED）。
  2. `test_requirements_lock_offline_reproduce`（**非ゲート＝`@pytest.mark.perf` と同じく既定除外**。重い venv 生成を既定スイートから外す）: `tempfile.TemporaryDirectory` 内に `python -m venv` → `subprocess.run([venv_pip,"install","--no-index","--find-links",wheelhouse,"--require-hashes","-r",lock])` の `returncode == 0` → その venv python で `import tree_sitter, tree_sitter_java, tree_sitter_c, ahocorasick, chardet, pytest` を `subprocess` 実行し returncode 0 を assert（spec §11 再現スモーク）。観測点は returncode と import の分解で曖昧さを排除。
- 実行時コード変更なし（配備再現性の成果物のみ）。

### WS6: 60GB perf ベースライン ＋ `_ITEMS_PER_MB` 実バイト較正

- `tests/perf/corpus_gen.py`: シード固定の決定的合成ソース木生成器。サイズパラメタ（ファイル数 / 言語比 Java:C:shell / シンボル相互参照密度）でスケール可変。同一シードで同一木（再現性）。
- `tests/perf/test_perf.py`: `@pytest.mark.perf`。**非ゲート運用の機構（事実訂正）**: `requires_ripgrep` は pyproject の marker 登録**だけでは除外されておらず**、実体は `tests/conftest.py:16-23` の `pytest_collection_modifyitems` による動的 skip 注入（marker 登録は警告抑止のみ）。よって perf も**同一機構**＝`conftest.py` の `pytest_collection_modifyitems` に「`-m` で `perf` が明示指定されない限り `perf` を持つ item に skip 注入」分岐を追加する。**`pyproject.toml:24-26` には `perf`・`requires_ripgrep` の marker は既に登録済（警告抑止用）。よって Phase 3 で追加すべきは `pyproject` への marker 追加ではなく `conftest` の `pytest_collection_modifyitems` への perf 除外分岐のみ**（`conftest.pytest_configure` は触らない＝既存 marker 二重登録は no-op で不問。重複 no-op タスクを作らない）。**実装契約（テストのアンカー固定）**: perf skip 注入時の `reason` 文字列は **`perf` を含む**こと（`test_perf_excluded_by_default` が reason 部分一致で検証＝実装側仕様としてここで固定。`requires_ripgrep` の汎用 reason を流用すると恒久 RED になるため）。計測項目:
  - throughput（files/s, MB/s）、peak RSS（`resource.getrusage` 主・`tracemalloc` 併用可）。
  - スケール特性: サイズ S, 2S, 4S で計測し線形/準線形を確認、O 表記見積りを **perf レポート doc**（`docs/superpowers/plans/` 配下に Phase 3 完了記録と共に）へ記録。
  - `--memory-limit` × 実パス数の関係（degrade ラダーの実挙動確認）。
- **`_ITEMS_PER_MB` 較正**: 合成コーパスで来歴グラフ構造（symbols/edges/intro）の**実測 bytes/item** を求め、`budget._ITEMS_PER_MB` を**一度だけ**実測由来の値へ更新し、**perf 証跡（測定スクリプト出力）と共に同一コミットで確定**する。測定は G1 で確定した対象 ABI（cp312）・対象アーキ（x86_64/glibc）環境で実施（`sys.getsizeof` 等は実装/ABI 依存ゆえ。確定後は純定数で決定性不変）。
  - budget 関数自体は依然 **item 数の純関数**（決定性不変）。定数のみ経験的接地。較正値は本書冒頭 I-1 と同じ「開発ボックス＝稼働先同等」前提（`phase0-gate-result.md`）に依存し、稼働先実機が大きく異なる ABI/アーキの場合は `--memory-limit` 指定時の degrade トリガ点が想定とずれうる（ただし**既定 `--memory-limit=None` 経路は定数不感ゆえ既定出荷物＝Inv-1 は不変**）。
  - **不変条件への影響**: `--memory-limit=None`（既定）経路は `budget.MemoryBudget.unlimited` で `exceeded()` が常に `False`・`item_budget` は `None` 経路で `_ITEMS_PER_MB` を参照しない（`budget.py:24-32` で確認）⇒ **Inv-1（既定 byte 不変）に無影響**。`--memory-limit` 指定時は degrade トリガ点が（Phase 2b の暫定定数から）動くが、spec §8.2 L164 の決定的ラダー・§8.4 全件記録は維持（純関数ゆえ同一入力＋同一 limit＋同一定数で同一判断）。較正版またぎの resume は manifest `items_per_mb` 照合で保守的再処理（§5 Inv-7・§6）。較正は v1 確定の一度きりで、以後は固定定数。

---

## 5. 決定性不変条件（Phase 2b 継承＋Phase 3 拡張）

**Phase 2b の Inv-1〜4 は全て Phase 3 でも不変として継承**する。下表は Phase 3 で特に焦点となる継承分と新規追加分を示す。

| Inv | 内容 | 検証 |
|---|---|---|
| **Inv-1** | 既定起動（行数 ≤ 上限・診断 ≤ 上限・UTF-8 BOM・`--resume` 無・`--memory-limit=None`）は **Phase 2b golden 14・既存 167 と 1 バイト不変**。manifest は追加生成物で TSV/diagnostics バイトに無影響 | 既存 golden 14・既存 167 を回帰で byte 不変確認＋ `_ITEMS_PER_MB` 能動ガード（§7） |
| **Inv-5** | part 分割透過。**比較手続きは §3 手順1 の `_canonical_data_blob` に一元定義**（part 群再構成＝書込側と同一関数。各 part 個別 decode→BOM 除去→ヘッダ 1 行除去→`split("\n")`→データ行連結。`splitlines()` 不使用。BOM/ヘッダは part 数回現れるため「データ行のみ」で比較）。part 群の `_canonical_data_blob` ＝単一ファイル版の `_canonical_data_blob` ＝ `manifest.data_sha256` の原像、の三者一致を 1 関数で保証。境界は安定ソート後の決定的順次チャンク | `test_output_writer` で `_canonical_data_blob(part群)==_canonical_data_blob(単一)==書込時 ordered` ・`n=0/n=L/n=kL/n=L+1` 境界・2 回実行一致 |
| **Inv-6** | 縮約は §8.4 全件性を侵さない: `SECTION_8_4_CATEGORIES` は常に全件、縮約は非 §8.4 のみ、代表サンプルは既存決定順（add 列）先頭 K で決定的（§4 WS3 の合成事実継承） | `test_diagnostics` で §8.4 カテゴリ全件・非 §8.4 縮約・複数 kw＋縮約発火で 2 回一致 |
| **Inv-7** | resume 冪等。**前提を明記**: 同一入力 **かつ 同一ツール版（`tool_version`）かつ 同一 `_ITEMS_PER_MB` かつ 同一オプション**の下で、`--resume` 有/無の最終出力（全 part＋manifest バイト）は同値。前提のいずれかが崩れる（例 WS6 較正またぎ）場合は完了判定 5 が未完了とし保守的再処理＝バイト不一致を作らない。中断後再開で完了集合は単調増加のみ・既完了 kw のバイト不変。冪等の根拠＝`sorted(model.sort_key)` 安定全順序＋固定 encoding＋完了判定 4（data_sha256 一致）で「スキップ＝再生成と同一バイト」を機械保証 | `test_resume` で中断→再開・破損 manifest・行数/sha256/版/定数 不一致・最終バイト同値（クラッシュ注入は §7） |
| **Inv-3 継承** | （Phase 2b Inv-3）同一入力＋同一オプションで 2 回実行 byte 一致。併せて（Phase 2b Inv-2/境界6）`--memory-limit`/`--jobs`/ripgrep 有無/複数 kw で出力シンボル**集合**は変動しうるが集合内記録（相対順序含む）は完全決定的 | 既存 Phase 2b 不変条件テスト不変 |

---

## 6. エラー処理

- part 書込中クラッシュ → manifest 未確定 → resume 未完了扱い（部分 part を完了誤認しない・§10.3）。場合分けは §4 WS1「耐クラッシュ」参照。
- `--resume` 指定だが完了判定 5（`tool_version`/`items_per_mb`）不一致（例 WS6 較正をまたいだ再開）→ 未完了扱いで再処理（保守的・別版生成物を信用しない）。
- `--resume` 指定だが manifest 破損（JSON 不正）または `data_sha256` 不一致 → 未完了扱いで再処理（部分結果/改竄を信用しない）。
- encoding 置換発生 → 既存 `encoding` 列＋diagnostics「要確認」経路（不変）。出力 encoding で表現不能文字 → `errors="replace"`（落とさない・§10.1）。
- `requirements.lock` ハッシュ不一致 → `pip --require-hashes` が pip 段で致命終了（インストール時検出）。
- 終了コードは既存規約（致命/警告）を踏襲。

---

## 7. テスト戦略（TDD・Phase 2b と同型）

各 WS に**失敗先行**の単体テスト。観測可能なアサーション（具体バイト/行数/ファイル名/例外/sha256）に落とす:

- `test_output_writer`: part 境界（`n=0` 単一・`n=L` 単一・`n=L+1` で 2 part・`n=2L` で 2 part＝空 part 無）、命名ゼロ詰め（`nparts=9→part01..part09`、`nparts=100→part001..part100` を確定値 assert）、manifest スキーマ/原子性、BOM 規則（`utf-8-sig` のみ・`utf-8` 明示は無 BOM）、Inv-5 比較手続き（decode→BOM除去→ヘッダ1行除去→連結＝単一同値）、2 回実行一致。
- `test_resume`: 完了判定 1〜5、冪等（`--resume` 有/無 最終バイト同値）、破損 manifest、行数一致だが `data_sha256` 不一致を未完了判定、`items_per_mb`/`tool_version` 不一致を未完了判定。**`test_resume_sha_mismatch` の改竄レシピ**: 行数を保ったまま 1 セルの 1 文字を別文字へ置換し sha256 のみ変える（行追加だと条件3で先に落ち条件4を検証できない罠を回避）。`test_resume_orphan_cleanup`: 前回 `nparts=100`（3桁名）→今回 `nparts=99`（2桁名）等で旧孤児 part が finalize 手順5 で除去され output_dir が新 manifest の parts のみになることを assert。
  - **クラッシュ注入方針（明記・これが無いと WS1 が TDD 駆動不能）**: `output_writer.finalize` を「① 全 part 原子確定 → ② manifest 原子確定＋親 fsync」の 2 フェーズに分離し、②直前にフック可能点（例 `_write_manifest`）を置く。`test_resume_crash_before_manifest`: `monkeypatch` で `_write_manifest` を `raise RuntimeError` に差し替え → `finalize` が `pytest.raises` で落ちる → part 群は存在するが `<kw>.manifest.json` 不在 → `resume.is_complete is False` → `--resume` 再実行で当該 kw 再処理し無故障時と最終バイト同値（Inv-7）。`test_resume_partial_part`: part を 1 個だけ人工配置＋manifest 不在 → `is_complete is False`。`test_resume_rowcount_mismatch` / `test_resume_sha_mismatch`: manifest を実ファイルと食い違わせ配置 → `is_complete is False`。**スコープ線引き**: `os.replace`/`os.fsync` 自体の途中切断はプロセス内再現不能ゆえテストしない。OS の rename 原子性・永続性は Phase 2b で確立した `tsv` 不変プリミティブの責務として**検証範囲外**（この線引きを設計に明記し実装者が再現不能テストで停滞しないようにする）。
- `test_diagnostics`: §10.3 縮約・§8.4 免除（`symbol_rejected`/`getter_setter_no_expand`/`prov_*` 全件）・`detail_limit=0` が既存 `render()` と同一（既存 `test_diagnostics.py` をアンカーに自己同値）・複数 kw＋縮約発火で 2 回 byte 一致。
- `test_encoding_wiring`: 3 decode 経路（入力 `.grep` / direct ソース / indirect ソース＝`fixedpoint._file_meta`）すべてに `opts.encoding_fallback` が届く。**行番号でなく観測挙動でアサート**（実装シグネチャ変更に頑健）: (a) chardet が確信する入力は fallback を変えても出力不変、(b) chardet 不確信の既知 cp932 専用バイト列で fallback 鎖を変えると復号結果（`encoding` 列/本文）が鎖に依存して変わる、(c) direct と indirect で同一バイト列が同一 encoding に解決（一貫性）。
- `test_requirements_lock_consistency`（ゲート）/ `test_requirements_lock_offline_reproduce`（非ゲート）: §4 WS5 の通り 2 本。
- `test_corpus_gen_deterministic`（**既定ゲート・非 perf・small サイズ**）: `corpus_gen(seed=42, size=S)` を 2 ディレクトリへ生成し全相対パス集合・各ファイル sha256 完全一致を assert（モジュール未作成で `ImportError` RED）。perf 計測（重い・非ゲート）とは分離。
- `test_default_path_independent_of_items_per_mb`（**既定ゲート・Inv-1 能動ガード**）: `monkeypatch.setattr("grep_analyzer.budget._ITEMS_PER_MB", v)` を `v∈{1, 10**9}` で、`--memory-limit` 無指定の pipeline 出力 TSV sha256 が同値（既定経路が定数に不感＝WS6 較正値を将来動かしても Inv-1 を機械保証。手動規律に依存しない）。加えて既存 `test_budget` の `estimate_items` 純関数性継承。
- `test_perf_excluded_by_default`（メタテスト）: 機構は **skip 注入**（`requires_ripgrep` と同一＝`item.add_marker(pytest.mark.skip)`、pytest 上は "skipped"・deselect ではない）。観測 API を一意化＝`pytest.Pytester` で `@pytest.mark.perf` ダミーテストを含む一時 pkg を `runpytest()` し `result.assert_outcomes(skipped=1, passed=0)` かつ skip reason に **`perf`** を含むことを assert（reason 契約は §4 WS6 で実装側仕様に固定済。"deselect/skip" の二択を skip+reason に確定し恒久 RED 偽陽性を排除）。
- **回帰（Inv-1 最重要）**: 既定オプションで既存 golden 14・既存 167 が **byte 完全不変**。既存 golden 照合は片側包含方式（`tests/golden/test_golden.py` は expected 側ファイル名のみ照合）ゆえ新規 `<kw>.manifest.json` を out に追加しても既存 golden を構造的に割らない（回帰ハーネス新規作成不要）。
- 統合: `--resume` 中断→再開、part 分割×複数 kw×複数 part、`--output-encoding cp932` 出力。
- perf は `@pytest.mark.perf` で既定除外（spec §11 非ゲート・機構は conftest 改変＝WS6）。

---

## 8. Phase 3 完了の定義

- 全テスト緑（既定スイートで Inv-1 維持・Phase 2b 167 + Phase 3 追加分 passed、perf／オフライン再現スモークは非ゲート別実行）。
- `phase0-gate-result.md` に「Phase 3 完了記録」（完了日 UTC・コミット範囲・全テスト結果・WS1〜6 対応表・Inv-1/5/6/7 充足・perf スケール証跡＋`_ITEMS_PER_MB` 較正値と根拠・`requirements.lock` オフライン再現結果・**v1 出荷判定（前提: 稼働先＝想定モダンLinux／glibc≧2.17。glibc<2.17・musl は spec §13 R6・§4.2 再検証要＝出荷ブロッカー）**）を追記。
- 成果物: 「既定で Phase 2b と 1 バイト不変を保ちつつ、大規模 kw の Excel 互換 part 分割・kw 単位 resume の原子性＋再生成同値保証・診断の §8.4 全件性を侵さない縮約・出力/フォールバック encoding 配線（3 配線点）・ハッシュ固定オフライン再現ビルド・非ゲート perf ベースラインを備えた、**（想定モダンLinux 前提で）v1 出荷可能**な決定的ツール」。

---

## 9. レビュー方針（ユーザー要件）

フェーズ移行（Phase 3 着手＝writing-plans 確定）前に、複数回の独立 3 並行批判的レビュー（spec 適合 / アルゴリズム決定性 / TDD 実行可能性）を実施し各反映（Phase 2a/2b と同型）。本 v4 は第 1〜3 ラウンド反映済。第 2 ラウンドで C-2 のゼロブロック論拠は per-part fsync セマンティクス検証により push back し不採用（`data_sha256` 正規形一意化を別根拠で採用）。**第 3 ラウンドで 3 軸（spec適合/決定性/TDD）すべて「収束・writing-plans 可」**＝Critical/Important 皆無、決定性 Critical は Python 反例再構築で実証的に閉鎖確認。残 Minor（実装計画吸収可）も spec 側に固定済。ユーザーレビュー承認 → writing-plans で実装計画 → 計画への批判的レビュー → 実装。
