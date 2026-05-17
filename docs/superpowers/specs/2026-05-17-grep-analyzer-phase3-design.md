# grep_analyzer Phase 3 設計（規模・運用）

- 日付: 2026-05-17
- 位置づけ: マスター設計書 `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`（**source of truth**）の §15「フェーズ3（規模・運用）」を実装に落とす**従属設計**。本書は writing-plans（Phase 3 実装計画）の入力。マスター spec と齟齬がある場合は **マスター spec が優先**。
- 前提: Phase 0/1/1.5/2a/2b 完了（`phase0-gate-result.md`）。現状 `python -m pytest -q` = **167 passed**（rg 環境受入条件充足済・golden 14・既存 130 + Phase 2b 33 + rg 4）。作業ブランチは main 直接（ソロプロジェクト）。
- 構造決定: Phase 2 は 2a/2b に分割したが、**Phase 3 は単一計画**（ユーザー決定）。6 ワークストリーム（WS1〜6）を1つの spec/計画で扱う。

---

## 1. 目的とスコープ

Phase 3 完了をもって spec の残 v1 正本（§4.1 / §8.2 perf / §9 規模分割 / §10.1 出力encoding / §10.3 縮約・原子性・resume / §10.4 CLI / §11 / §15 フェーズ3）を全充足し、**v1 出荷可能**にする。

**スコープ内（6 ワークストリーム）**:

| WS | 項目 | spec 根拠 |
|---|---|---|
| WS1 | `--resume` 原子性 ＋ kw 毎 manifest | §10.3 L251-252 |
| WS2 | 規模分割 `<keyword>.partNN.tsv` | §9 L231 |
| WS3 | diagnostics §10.3 縮約（§8.4 全件性免除） | §10.3 L250・§8.4 |
| WS4 | `--output-encoding` / `--encoding-fallback` 配線 | §10.1 / §10.4 L261-265 |
| WS5 | `requirements.lock`（版＋ハッシュ固定） | §4.1 |
| WS6 | 60GB perf ベースライン ＋ `_ITEMS_PER_MB` 実バイト較正 | §8.2 L163 / §11 |

**スコープ外（v1 受容リスク・spec 準拠）**:

- キーワード**内**チェックポイント resume（spec §10.3 L252 / §14 = v1 スコープ外・受容リスク）。v1 は **キーワード単位 resume** のみ。
- 動的「プロジェクト頻出トップN」ストップリスト（spec §8.3 / §14 将来）。
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
  src/grep_analyzer/diagnostics.py     # render(detail_limit, exempt_categories) で §10.3 縮約
  src/grep_analyzer/pipeline.py        # resume スキップ判定 → output_writer.finalize 呼び出しへ差し替え
  src/grep_analyzer/cli.py             # --resume / --output-encoding / --encoding-fallback /
                                       #   --max-rows-per-part / --diagnostics-detail-limit
  src/grep_analyzer/model.py (EngineOptions)  # 上記オプションの保持（末尾既定追加・後方互換）

不変（変更しない決定的コア）:
  fixedpoint / chase / classify / walk / stoplist / automaton / provenance /
  ripgrep / budget(関数) / spill / progress / ingest / encoding.decode_bytes
  ※ WS6 は budget.py の定数 _ITEMS_PER_MB を「一度だけ」較正（関数ロジック不変）。
```

`output_writer` は既存 `tsv.write_tsv` の原子プリミティブ（`tempfile.mkstemp` → `write` → `flush` → `os.fsync` → `os.replace`、例外時 tmp 削除）を**内部再利用**する。`tsv.write_tsv` 自体のシグネチャは互換維持（単一ファイル経路の薄いラッパとして残すか、`output_writer` に吸収し呼び出し側を差し替える — 実装計画で一意化）。

---

## 3. データフロー（pipeline.run の kw ループ）

```
for grep_file in sorted(input_dir.glob("*.grep")):
    keyword = grep_file.stem
    if opts.resume and resume.is_complete(output_dir, keyword, opts):
        diag.add("resume_skipped", keyword)        # 非 §8.4・縮約対象
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

`output_writer.finalize` の内部手順:

1. `ordered = sorted(rows, key=model.sort_key)`（既存の決定的全順序）＋ 各セル `_sanitize`。
2. データ行数 `n` が `opts.max_rows_per_part` 以下 → **単一ファイル `<kw>.tsv`**（part サフィックスを付けない）。超過 → `<kw>.part01.tsv`, `<kw>.part02.tsv`, …（順次チャンク）。
3. 各 part = ヘッダ行（`TSV_COLUMNS`）＋ 当該チャンクのデータ行。各 part を tmp→fsync→`os.replace` で原子確定（既存プリミティブ）。
4. 全 part 確定後、`<kw>.manifest.json` を tmp→fsync→`os.replace` で**最後に**原子確定し、続けて**親ディレクトリを fsync**（rename の耐クラッシュ永続化・spec §10.3 原子性）。
5. part 数 > 1 のとき `diag.add("scale_split", f"{keyword}\t{n} rows\t{nparts} parts")`（spec §9「分割＋diagnostics 警告」）。

---

## 4. 各ワークストリームの確定仕様

### WS1: `--resume` 原子性 ＋ kw 毎 manifest

- **manifest 形式**: `<keyword>.manifest.json`。UTF-8、`json.dumps(..., sort_keys=True, ensure_ascii=False, separators=(",", ":"))` で**キー昇順・決定的**。**タイムスタンプ等の非決定要素は含めない**（テスト容易性・golden 安定）。
- **manifest スキーマ**:
  ```json
  {"schema_version":1,
   "keyword":"<kw>",
   "encoding":"utf-8-sig",
   "total_rows":<データ行数>,
   "parts":[{"name":"<kw>.tsv","rows":<n>}],
   "tool":"grep_analyzer","spec_phase":"3"}
  ```
  単一ファイル kw も `parts` 1 要素（`name` = `<kw>.tsv`）で manifest を発行（**規則統一**＝部分 part 群と単一を同一判定路で扱う）。
- **完了判定** `resume.is_complete(out, kw, opts)`: manifest が存在し JSON 妥当 ∧ `parts` の全ファイルが実在 ∧ 各ファイルのデータ行数（ヘッダ除く実測）が manifest 記載と一致 → **完了**。いずれか欠落/不一致 → 未完了（部分 part 群・部分書込を完了誤認しない＝spec §10.3「rename 済みのみ完了」）。
- **`--resume` 挙動**: 指定時のみ完了 kw をスキップ（`resume_skipped` 診断）。無指定時は全 kw を再処理（既存ファイルは原子上書き）。
- **耐クラッシュ**: part 書込中にクラッシュ → manifest 未確定 → 当該 kw 未完了扱い → 次回（--resume 時）再処理。manifest を最後に原子確定することで「manifest 存在 ⇔ 全 part 確定済」を保証。

### WS2: 規模分割 `<keyword>.partNN.tsv`

- **上限**: `opts.max_rows_per_part`（CLI `--max-rows-per-part`、**既定 1,048,575 データ行**）。各 part は「ヘッダ 1 行 ＋ 最大 1,048,575 データ行」= 最大 1,048,576 行 ＝ Excel 行上限内（spec §9「Excel 上限（約104万行）」を決定的定数化）。
- **分割境界**: `model.sort_key` 安定全順序ソート後の**順次チャンク**（spec §9「全順序安定ソート後の順次チャンク・境界は決定的・golden が割れない」）。チャンク i = データ行 `[i*L : (i+1)*L]`。
- **命名**: 単一（n ≤ L）→ `<kw>.tsv`（**サフィックス無＝Inv-1**）。複数 → `<kw>.partNN.tsv`。`NN` は **part 総数の桁数にゼロ詰め**（最小 2 桁）。例: 3 parts → `part01..part03`、150 parts → `part001..part150`。part 総数はソート後行数の決定的関数ゆえ命名も決定的。
- **ヘッダ**: 各 part の先頭に `TSV_COLUMNS`（Excel で各 part 単体が開ける）。
- **BOM**: encoding が `utf-8-sig` のとき**各 part 先頭に BOM**（各 part が独立ファイルとして Excel 互換・spec §9）。非 UTF-8 は BOM 無（既存規則）。

### WS3: diagnostics §10.3 縮約（§8.4 全件性免除）

- `Diagnostics.render(detail_limit: int, exempt: frozenset[str])`:
  - `detail_limit == 0` → **無制限＝現行 `render()` と完全同一**（Inv: Phase 2b と byte 不変）。
  - `detail_limit > 0` → カテゴリ毎に、`cat in exempt`（§8.4 全件性カテゴリ）なら**全件出力（縮約しない）**。非 exempt かつ件数 > `detail_limit` なら **先頭 `detail_limit` 件（既存決定順）＋ 集約行** `f"{cat}\t(... {extra} more, {total} total)"` を出力。
  - summary（カテゴリ別件数）は常に**真の総数**（縮約しても件数サマリは全数を示す）。
- **`SECTION_8_4_CATEGORIES`**（縮約免除＝spec §8.4「唯一の正本・全件」が §10.3 縮約に優先・Phase 2b 既知境界(5)の論理継承）: `symbol_rejected`, `getter_setter_no_expand`, `prov_*`（プレフィックス一致＝`prov_` で始まる全カテゴリ）。
- CLI `--diagnostics-detail-limit`（**既定 1000**＝1 カテゴリあたり 1000 件、`0` で無制限）。
- **決定性**: 代表サンプル = 既存の決定的追加順の先頭 K。同一入力で同一 diagnostics.txt。

### WS4: `--output-encoding` / `--encoding-fallback` 配線

- `--output-encoding`（既定 `utf-8-sig`）→ `opts.output_encoding` → `output_writer` の全 part 書込に適用。**BOM は `utf-8-sig` のときのみ**（既存 `tsv` 規則・spec §9「非UTF-8出力は BOM を付与しない」）。`errors="replace"`（既存・落とさない）。
- `--encoding-fallback`（カンマ区切り・既定 `encoding.DEFAULT_FALLBACK` = `cp932,euc-jp,latin-1`）→ `opts.encoding_fallback` → `decode_bytes(..., fallback_chain=opts.encoding_fallback)` に注入。spec §10.4 L265 通り **② フォールバック候補鎖のみを置換**し、**① chardet 検出は常に最初に実行**（`decode_bytes` 既存挙動を変えず引数で鎖だけ差し替え＝Phase 1.5 確立済 decode を不変利用）。入力 `.grep` と走査ソース両方に適用（既存 2 箇所の `decode_bytes` 呼び出しに同一鎖）。
- `diagnostics.txt` は常に utf-8 固定（ツールログ＝ §9 TSV 出力 encoding の対象外）。

### WS5: `requirements.lock`

- `wheelhouse/*.whl` の各 wheel について `pkg==version --hash=sha256:<sha256(wheel)>` を生成し `requirements.lock` を作成（spec §4.1「`==` 完全版ピン＋ハッシュ固定」）。
- **再現スモーク**（spec §11）: クリーン venv で `pip install --no-index --find-links wheelhouse --require-hashes -r requirements.lock` が成功し、`tree_sitter`/`tree_sitter_java`/`tree_sitter_c`/`pyahocorasick`/`chardet`/`pytest`系 が import 可能であることを検証するテスト（rg は任意ゆえ lock 対象外＝spec §4.1「任意」）。
- **整合テスト**: `requirements.lock` のハッシュが `wheelhouse/` の実ファイルと一致することを検証（lock と wheelhouse の乖離を CI で検出）。
- 実行時コード変更なし（配備再現性の成果物のみ）。

### WS6: 60GB perf ベースライン ＋ `_ITEMS_PER_MB` 実バイト較正

- `tests/perf/corpus_gen.py`: シード固定の決定的合成ソース木生成器。サイズパラメタ（ファイル数 / 言語比 Java:C:shell / シンボル相互参照密度）でスケール可変。同一シードで同一木（再現性）。
- `tests/perf/test_perf.py`: `@pytest.mark.perf`。`pyproject.toml` に marker 登録し**既定実行から除外**（`requires_ripgrep` と同型の非ゲート運用）。計測項目:
  - throughput（files/s, MB/s）、peak RSS（`tracemalloc` または `resource.getrusage`）。
  - スケール特性: サイズ S, 2S, 4S で計測し線形/準線形を確認、O 表記見積りを **perf レポート doc**（`docs/superpowers/plans/` 配下に Phase 3 完了記録と共に）へ記録。
  - `--memory-limit` × 実パス数の関係（degrade ラダーの実挙動確認）。
- **`_ITEMS_PER_MB` 較正**: 合成コーパスで来歴グラフ構造（symbols/edges/intro）の**実測 bytes/item**（`sys.getsizeof` 等の集計）を求め、`budget._ITEMS_PER_MB` を**一度だけ**実測由来の値へ更新し、**perf 証跡（測定スクリプト出力）と共に同一コミットで確定**する。
  - budget 関数自体は依然 **item 数の純関数**（決定性不変）。定数のみ経験的接地。
  - **不変条件への影響**: `--memory-limit=None`（既定）経路は `budget.unlimited` で budget を評価しない ⇒ **Inv-1（既定 byte 不変）に無影響**。`--memory-limit` 指定時は degrade トリガ点が（Phase 2b の暫定定数から）動くが、spec §8.2 L164 の決定的ラダー・§8.4 全件記録・Inv-3（集合内記録は決定的）は維持（純関数ゆえ同一入力＋同一 limit で同一判断）。較正は v1 確定の一度きりで、以後は固定定数。

---

## 5. 決定性不変条件（Phase 2b 継承＋Phase 3 拡張）

**Phase 2b の Inv-1〜4 は全て Phase 3 でも不変として継承**する（Inv-2 = priority-1 のみ出力変更で §8.4 全件記録、Inv-4 = 複数 kw diagnostics の walk 重複 dedup 意図変化、も Phase 3 機能で破らない）。下表は Phase 3 で特に焦点となる継承分（Inv-1/Inv-3）と新規追加分（Inv-5/6/7）を示す。

| Inv | 内容 | 検証 |
|---|---|---|
| **Inv-1** | 既定起動（行数 ≤ 上限・診断 ≤ 上限・UTF-8 BOM・`--resume` 無）は **Phase 2b golden 14・既存 167 と 1 バイト不変**。manifest は追加生成物で TSV/diagnostics バイトに無影響 | 既存 golden 14・既存テスト 167 を回帰で byte 不変確認 |
| **Inv-5** | part 分割透過: 全 part の（ヘッダ除く）データ行を順に連結 ＝ 単一ファイル時の本体データと完全同一。境界は安定ソート後の決定的順次チャンク | `test_output_writer` で連結＝単一同値・2 回実行一致 |
| **Inv-6** | 縮約は §8.4 全件性を侵さない: `SECTION_8_4_CATEGORIES` は常に全件、縮約は非 §8.4 のみ、代表サンプルは既存決定順先頭 K で決定的 | `test_diagnostics` で §8.4 カテゴリ全件・非 §8.4 縮約・2 回一致 |
| **Inv-7** | resume 冪等: 同一入力で `--resume` 有/無の最終出力（全 part＋manifest バイト）は同値。中断後再開で完了集合は単調増加のみ・既完了 kw のバイトは不変 | `test_resume` で中断→再開シナリオ・最終バイト同値 |
| **Inv-3 継承** | `--memory-limit`/`--jobs`/ripgrep 有無/複数 kw で出力シンボル集合は変動しうるが集合内記録（相対順序含む）は完全決定的（Phase 2b Inv-3） | 既存 Phase 2b 不変条件テスト不変 |

---

## 6. エラー処理

- part 書込中クラッシュ → manifest 未確定 → resume 未完了扱い（部分 part を完了誤認しない・§10.3）。
- encoding 置換発生 → 既存 `encoding` 列＋diagnostics「要確認」経路（不変）。出力 encoding で表現不能文字 → `errors="replace"`（落とさない・§10.1）。
- `requirements.lock` ハッシュ不一致 → `pip --require-hashes` が pip 段で致命終了（インストール時検出）。
- `--resume` 指定だが manifest 破損（JSON 不正）→ 未完了扱いで再処理（保守的・部分結果を信用しない）。
- 終了コードは既存規約（致命/警告）を踏襲。

---

## 7. テスト戦略（TDD・Phase 2b と同型）

- 各 WS に失敗先行の単体テスト: `test_output_writer`（part 境界・命名ゼロ詰め・manifest 原子性・BOM 規則）、`test_resume`（完了判定・冪等・破損 manifest）、`test_diagnostics`（§10.3 縮約・§8.4 免除・detail_limit=0 現行同値）、`test_encoding_wiring`（fallback 鎖差し替え・output_encoding・BOM）、`test_requirements_lock`（wheelhouse 整合・オフライン再現スモーク）、`tests/perf/`（非ゲート計測・スケール）。
- **回帰（Inv-1 最重要）**: 既定オプションで既存 golden 14・既存 167 が **byte 完全不変**。
- 統合: `--resume` 中断→再開、part 分割×複数 kw×複数 part、`--output-encoding cp932` 出力。
- perf は `@pytest.mark.perf` で既定除外（spec §11 非ゲート）。

---

## 8. Phase 3 完了の定義

- 全テスト緑（既定スイートで Inv-1 維持・Phase 2b 167 + Phase 3 追加分 passed、perf は非ゲート別実行）。
- `phase0-gate-result.md` に「Phase 3 完了記録」（完了日 UTC・コミット範囲・全テスト結果・WS1〜6 対応表・Inv-1/5/6/7 充足・perf スケール証跡＋`_ITEMS_PER_MB` 較正値と根拠・`requirements.lock` オフライン再現結果・v1 出荷判定）を追記。
- 成果物: 「既定で Phase 2b と 1 バイト不変を保ちつつ、大規模 kw の Excel 互換 part 分割・kw 単位 resume の原子性・診断の §8.4 全件性を侵さない縮約・出力/フォールバック encoding 配線・ハッシュ固定オフライン再現ビルド・非ゲート perf ベースラインを備えた、**v1 出荷可能**な決定的ツール」。

---

## 9. レビュー方針（ユーザー要件）

フェーズ移行（Phase 3 着手＝writing-plans 確定）前に、複数回の独立 3 並行批判的レビュー（spec 適合 / アルゴリズム決定性 / TDD 実行可能性）を実施し各反映（Phase 2a/2b と同型）。本設計書のユーザーレビュー承認 → writing-plans で実装計画 → 計画への批判的レビュー → 実装。
