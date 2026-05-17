# フェーズ0ゲート G1 結果記録

- 対象: `grep_analyzer` / spec §4.2 ゲートG1・§15 フェーズ0
- 検証日 (UTC): 2026-05-16
- 検証者: Claude Code（Task 0 実行）
- 位置づけ: 本ゲートが PASS しない限り Task 1 以降に着手しない（spec §15 フェーズ0）。

---

## Step 1: ターゲット環境の確定

開発環境（このボックス＝モダンLinux）で実測。稼働先「モダンLinux・オフライン／Python 3.12 既存」（spec §2.1）と同等環境とみなす。

| 項目 | コマンド | 実測値 |
|---|---|---|
| CPUアーキ | `uname -m` | `x86_64` |
| libc | `ldd --version \| head -1` | `ldd (Debian GLIBC 2.36-9+deb12u13) 2.36` → **glibc 2.36**（musl ではない） |
| Python | `python3.12 --version` | `Python 3.12.13` |
| platform タグ | `python3.12 -c "import sysconfig; print(sysconfig.get_platform())"` | `linux-x86_64` |
| Python ABI タグ | （pip debug） | `cp312` |

spec §2.1「要確定欄（実装前ゲート G1）」の確定値:

- **CPUアーキ = x86_64**
- **libc = glibc (≧ 2.36)**（Debian 12 / bookworm 系。musl ではない）
- **Python ABI タグ = cp312**

`python3.12 -m pip debug --verbose` の互換タグ先頭は `cp312-cp312-manylinux_2_36_x86_64`〜`manylinux_2_17_x86_64`（manylinux2014）まで広く互換。
wheel 解決には可搬性の高い **`manylinux_2_17_x86_64`（= manylinux2014, glibc 2.17+）** を採用（稼働先 glibc 2.36 で確実に動作。より古いモダンLinuxにも適合）。

---

## Step 2: 全必須依存の wheel オフライン取得実証

### 取得コマンド（開発環境・対象 platform タグ指定）

```
mkdir -p wheelhouse
python3.12 -m pip download --dest wheelhouse --only-binary=:all: \
  --implementation cp --python-version 3.12 --abi cp312 \
  --platform manylinux_2_17_x86_64 \
  "tree-sitter==0.21.3" "tree-sitter-java==0.21.0" "tree-sitter-c==0.21.4" \
  "chardet==5.2.0" pytest
```

注: 当タスクの確定依存リストは `tree-sitter==0.21.3` / `tree-sitter-java==0.21.0` /
`tree-sitter-c==0.21.4` / `chardet==5.2.0` ＋ `pytest`（フェーズ1テスト用）。
spec §4.1 に列挙の `pyahocorasick` は当タスク確定リスト外のため本ゲートでは未検証
（下記「懸念・申し送り」参照。後続フェーズ着手前に別途 G1 相当の wheel 実証が必要）。

### 取得結果（`ls wheelhouse` 相当）— すべて prebuilt `.whl`、sdist は 0 件

| ファイル | 区分 | 種別 |
|---|---|---|
| `tree_sitter-0.21.3-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl` | 必須 | ネイティブ cp312 wheel |
| `tree_sitter_java-0.21.0-cp38-abi3-manylinux_2_5_x86_64.manylinux1_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl` | 必須 | abi3 wheel（cp38+、cp312 互換） |
| `tree_sitter_c-0.21.4-cp38-abi3-manylinux_2_5_x86_64.manylinux1_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl` | 必須 | abi3 wheel（cp38+、cp312 互換） |
| `chardet-5.2.0-py3-none-any.whl` | 必須 | pure-Python wheel |
| `pytest-9.0.3-py3-none-any.whl` | テスト | pure-Python wheel |
| `iniconfig-2.3.0-py3-none-any.whl` | 推移（pytest） | pure-Python wheel |
| `packaging-26.2-py3-none-any.whl` | 推移（pytest） | pure-Python wheel |
| `pluggy-1.6.0-py3-none-any.whl` | 推移（pytest） | pure-Python wheel |
| `pygments-2.20.0-py3-none-any.whl` | 推移（pytest） | pure-Python wheel |

**結論: 確定必須依存＋推移依存すべてが cp312・対象 platform 向け `.whl` で取得可能。
sdist しか取れない依存は 0 件。spec §4.2 の (a) sdist同梱／(b) 代替 への分岐は不要。**

`wheelhouse/` は binary 重量物のため Git にコミットしない（`.gitignore` に登録）。
上記コマンドでネット接続のある開発環境にて再現生成可能。本タスクではローカル生成済み。

### 環境へのインストール実証（オフライン形式 `--no-index`）

```
python3.12 -m pip install --no-index --find-links wheelhouse \
  "tree-sitter==0.21.3" "tree-sitter-java==0.21.0" "tree-sitter-c==0.21.4" \
  "chardet==5.2.0" pytest
```

`importlib.metadata.version()` による実インストール版（後続 Task 4=chardet / Task 8=tree-sitter のテスト前提）:

| パッケージ | インストール版 |
|---|---|
| tree-sitter | **0.21.3** |
| tree-sitter-java | **0.21.0** |
| tree-sitter-c | **0.21.4** |
| chardet | **5.2.0** |
| pytest | **9.0.3** |

### tree-sitter `Language` API 形態の確定（重要・後続実装の前提）

tree-sitter 0.21.x は **2引数 API** `Language(<grammar capsule ptr>, "<name>")`。
（1引数 `Language(ptr)` は 0.22+ の新API。本プロジェクトは 0.21.3 ピンのため**必ず2引数形式**を使う。）

実測結果:

```
Language(tree_sitter_java.language(), "java")  -> <tree_sitter.Language object at 0x...>   OK
Language(tree_sitter_c.language(),   "c")      -> <tree_sitter.Language object at 0x...>   OK
```

機能スモーク（Java パース）:

```
Parser().set_language(Language(tree_sitter_java.language(), "java"))
parse(b'class A { int x = 1; }') -> root_node.type = "program" / has_error = False   OK
```

→ **2引数 `Language(ptr, name)` API が 0.21.3 で正常動作。実パースも成功。**

---

## Step 3: ゲート判定

### G1: PASS

理由:

1. ターゲット環境確定済み（x86_64 / glibc 2.36 / Python 3.12.13 / cp312）。spec §2.1 要確定欄を充足。
2. 当タスク確定の全必須依存（tree-sitter 0.21.3 / tree-sitter-java 0.21.0 / tree-sitter-c 0.21.4 / chardet 5.2.0）＋pytest＋全推移依存が、cp312・`manylinux_2_17_x86_64` 向け prebuilt `.whl` でオフライン取得可能であることを実証。sdist-only 依存ゼロ＝spec §4.2 フォールバック (a)/(b) 不要・単一トラック前提（spec §3）成立（当該依存範囲）。
3. wheelhouse からの `--no-index` インストールに成功し、ピン版どおりに import 可能。tree-sitter 0.21.3 の 2引数 `Language(ptr, name)` API と実パースを確認済み。

→ **Task 1 以降への着手可。**

### 懸念・申し送り

- **`pyahocorasick` 未検証** → **【2026-05-16 解消済み: 下記「Phase 2 着手ゲート（pyahocorasick G1 相当）記録」で PASS】**。spec §4.1 は必須依存に `pyahocorasick`（ネイティブ）を列挙するが、当 Task 0 の確定依存リスト（tree-sitter系＋chardet＋pytest）に含まれないため本ゲートでは wheel 実証していなかった。`pyahocorasick` を実際に使う後続フェーズ（多シンボル同時走査＝主にフェーズ2 §8.2）に着手する前に、同等の G1 相当検証（cp312・対象 platform の prebuilt wheel 取得可否、sdist-only の場合は §4.2 (a)/(b) 意思決定）を別途実施すること、としていた。フェーズ1（決定的コア）は tree-sitter＋chardet で完結するため本懸念は Task 1 着手をブロックしなかった。
- `wheelhouse/` は未コミット（`.gitignore` 登録）。配備時は本書 Step 2 のコマンドでネット接続環境にて再生成し持ち込む運用。
- 採用 platform タグは `manylinux_2_17_x86_64`（glibc 2.17+ 互換）。稼働先 glibc がこれ未満（極端に古い／musl）の場合は再検証が必要だが、稼働先想定「モダンLinux」では十分。

---

## Phase 1 完了記録（spec §15 フェーズ1）

- 完了確認日 (UTC): 2026-05-16
- コミット範囲: `3fb8595`（Task 1 雛形）..`HEAD`（Task 14 完了）
- 全テスト結果: **43 passed**（unit / integration / golden / smoke すべて PASS。0 failed、0 error）

### spec §15 フェーズ1 → 実装モジュール 対応表

| spec §15 フェーズ1 要件 | 実装タスク | モジュール / テスト |
|---|---|---|
| **Ingest**（`input/*.grep` 読込） | Task 3 / Task 11 | `src/grep_analyzer/ingest.py` / `tests/unit/test_ingest.py` |
| **grep行パース**（最左 `:<数字>:` 境界） | Task 3 | `src/grep_analyzer/ingest.py` / `tests/unit/test_ingest.py` |
| **文字コード**（chardet + 決定的フォールバック鎖・落とさない） | Task 4 | `src/grep_analyzer/encoding.py` / `tests/unit/test_encoding.py` |
| **言語ディスパッチ**（拡張子マップ + `EXEC SQL` ヒューリスティック + `--lang-map` 上書き） | Task 5 | `src/grep_analyzer/dispatch.py` / `tests/unit/test_dispatch.py` |
| **分類器 - tree-sitter**（Java / C の AST 分類・confidence=high） | Task 8 | `src/grep_analyzer/classifiers/ts_classifier.py` / `tests/unit/test_ts_classifier.py` |
| **分類器 - Pro\*C 行番号保存**（`EXEC SQL` 区間をプレースホルダ置換・行数不変） | Task 6 + Task 8 | `src/grep_analyzer/proc_preprocess.py` + `classifiers/ts_classifier.py` / `tests/unit/test_proc_preprocess.py` + `test_ts_classifier.py` |
| **分類器 - SQL / Shell 正規表現**（confidence=medium） | Task 7 | `src/grep_analyzer/classifiers/regex_classifier.py` / `tests/unit/test_regex_classifier.py` |
| **TSV スキーマ**（spec §9 列順・決定的全順序ソート・BOM 規則・原子的書込） | Task 2 + Task 10 | `src/grep_analyzer/model.py` + `tsv.py` / `tests/unit/test_model.py` + `test_tsv.py` |
| **golden 基盤**（6 言語 × direct 代表ケース・完全一致回帰・`category_sub` 空固定） | Task 13 | `tests/golden/` 全体（6 ケース: java\_direct / c\_direct / proc\_direct / sql\_direct / shell\_direct / encoding\_utf8） |
| **direct のみ完全決定性**（多ホップなし・golden が常に安定） | Tasks 1–13 全体 | パイプライン `pipeline.py`、全 unit/integration/golden テスト |

### 補足事項

- Task 12 で `src/grep_analyzer/__main__.py` と `cli.py` を実装。`python -m grep_analyzer --help` がパッケージング契約として smoke で検証済み（`tests/test_smoke.py`）。
- Task 13 の実際のコミットメッセージは `test: golden基盤と6言語direct代表ケース`（golden コミット規約 `chore(golden): <理由>` と異なる）。既存 git 履歴は変更しない。**今後の golden 更新コミットは `chore(golden): <理由>` 形式を使用すること**（`.claude/skills/writing-tests.md` Golden 節の規約に準拠。`docs/superpowers/plans/2026-05-16-grep-analyzer-phase1.md` の Task 13 Step 5 例示コマンドを同規約に修正済み）。
- **Phase 2 以降の着手前提**: `pyahocorasick`（多シンボル同時走査）の wheel 実証 → **2026-05-16 完了（下記「Phase 2 着手ゲート（pyahocorasick G1 相当）記録」で PASS）**。記録当時は未完了だった。

---

## Phase 1.5 着手ゲート記録

- 記録日 (UTC): 2026-05-16
- Step1: `python -m pytest -q` → 43 passed / 0 failed / 0 error
- Step2: spec `v7（現行）` 反映確認 → PASS（grep ヒット 1 行）
- 判定: **PASS**（Phase 1 ベースライン緑 ＆ spec v7 反映済み。Task 1 以降へ着手可）
- 注: `pyahocorasick` の wheel 実証は Phase 2 着手前提（本ゲート対象外）

---

## Phase 1.5 完了記録（spec §15 フェーズ1.5）

- 完了確認日 (UTC): 2026-05-16
- コミット範囲: `9dc82b0`（Task0 着手ゲート）..`f3f8d30`（Task8 golden）..`d1322f6`（本完了記録）
  - 注: 範囲内 `7a9ae65 feat(settings): add 'using-superpowers' skill to permissions` は `.claude/settings.local.json` への権限追記のみのスコープ外コミット（実装外のサブエージェント副作用。Phase 1.5 コード/テストには無関係）
- 全テスト結果: **78 passed**（unit / integration / golden / smoke すべて PASS。0 failed / 0 error）

### spec §15 フェーズ1.5 → 実装 対応表

| 要件 | 実装タスク | モジュール / テスト |
|---|---|---|
| §5.1 シェバン検出＋`.csh`/`.tcsh`・方言独立判定 | Task 1〜3 | `dispatch.py`（`shebang_dialect`/`detect_language`/`detect_shell_dialect`/`extension_resolves_language`）/ `tests/unit/test_dispatch.py` |
| §7 SQL=Oracle 方言精密化 | Task 4 | `classifiers/regex_classifier.py`（`_SQL_RULES`）/ `tests/unit/test_regex_classifier.py` |
| §7 Shell bourne/cshell 二方言 | Task 5 | `classifiers/regex_classifier.py`（`classify_shell`）/ 同上 |
| §8.1 用 Oracle/csh 追跡シンボル抽出規則（非配線・Phase2 入力） | Task 6 | `chase.py`（`extract_var_symbols`）/ `tests/unit/test_chase.py` |
| パイプライン方言伝播・§8.4 `unsupported_shebang`（手順3限定） | Task 7 | `pipeline.py` / `tests/integration/test_pipeline_dialect.py` |
| golden 決定的拡張（Oracle/csh/拡張子なし4ケース）・既存6不変 | Task 8 | `tests/golden/cases/{oracle_direct,csh_direct,csh_noext_shebang,sh_noext_shebang}` |
| direct のみ・完全決定性維持 | Task 1〜8 全体 | 既存6 golden 不変＋全体テスト緑 |

### 補足・申し送り
- `chase.py` は本 Phase ではパイプライン非配線（unit 固定のみ）。Phase 2 不動点エンジンが消費する。
- **Phase 2 着手前提（完了）**: `pyahocorasick` の §4.2 G1 相当 wheel オフライン実証 → **下記「Phase 2 着手ゲート（pyahocorasick G1 相当）記録」で PASS**。Phase 1.5 本体は tree-sitter＋chardet＋標準ライブラリのみで完結（本前提は Phase 1.5 をブロックしなかった）。

---

## Phase 2 着手ゲート（pyahocorasick G1 相当）記録

- 検証日 (UTC): 2026-05-16
- 検証者: Claude Code（Phase 2 着手前・spec §15 フェーズ2 着手前提 / §4.2 G1 相当）
- 位置づけ: spec §4.1 `pyahocorasick`（必須・多シンボル同時走査）は Phase 0 ゲート G1 の確定依存リスト（tree-sitter系＋chardet＋pytest）外で未検証だった（本書「懸念・申し送り」/「Phase 1 完了記録」）。spec §15 は本実証を**フェーズ2 着手前提**と明記し §4.2 は「ゲート未充足のまま着手不可」と規定。本節でその唯一の積み残しを解消する。

### 検証手順と結果（Phase 0 G1 と同一の platform タグ・厳密さ）

| 検証項目 | コマンド／方法 | 結果 |
|---|---|---|
| wheel オフライン取得 | `pip download --only-binary=:all: --implementation cp --python-version 3.12 --abi cp312 --platform manylinux_2_17_x86_64 "pyahocorasick==2.1.0"` | ✅ `pyahocorasick-2.1.0-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl`（Phase 0 G1 と**同一 platform タグ**）。sdist 0 件 |
| wheel 種別 | `unzip -l` | ✅ ネイティブ cp312 拡張 `ahocorasick.cpython-312-x86_64-linux-gnu.so` を含む binary wheel |
| 推移依存 | `pip download` 解決 | ✅ **なし**（単一自己完結ネイティブ拡張。§4.2 手順2「推移依存も取得可能」を自明に充足） |
| オフライン install | `pip install --no-index --find-links wheelhouse "pyahocorasick==2.1.0"` | ✅ 成功 |
| import / 実版 | `importlib.metadata.version` | ✅ `pyahocorasick 2.1.0` |
| 機能スモーク | `Automaton` 構築 → `add_word`×3 → `make_automaton` → `iter()` 多シンボル同時走査 | ✅ `[(7,'CODE'),(16,'v_code'),(29,'PATH')]`（§8.2 用途そのものを実走で確認） |

### G1 相当判定: **PASS**

理由:

1. spec §4.1 必須依存 `pyahocorasick`（最終ピン版 `==2.1.0`）が、Phase 0 G1 で確定したターゲット環境（x86_64 / glibc 2.36 / Python 3.12.13 / cp312）向け prebuilt `.whl` で**オフライン取得可能**。推移依存ゼロ・sdist-only 依存ゼロ。
2. §4.2 手順3 の分岐（取得不能時の (a) sdist 同梱／(b) 代替）は**不要**＝`pyahocorasick` についても単一トラック前提（spec §3）が成立。
3. wheelhouse からの `--no-index` インストール・import・多シンボル同時走査スモーク（§8.2 中核機能）まで実走確認。

→ **spec §15 フェーズ2 の着手前提を充足。Phase 2（不動点エンジン）着手可。**

### 申し送り

- `wheelhouse/` に `pyahocorasick-2.1.0-…whl` を集約済み（Phase 0 G1 の他 wheel と同居）。`.gitignore` 登録のため**未コミット**（Phase 0 G1 と同一運用＝配備時はネット接続環境で再生成し持ち込み）。
- 採用 platform タグは Phase 0 G1 と統一の `manylinux_2_17_x86_64`（glibc 2.17+ 互換）。稼働先想定「モダンLinux」（glibc 2.36 実測）で十分。
- **spec-vs-実装ギャップ（Phase 2 非ブロッカー・要追認）**: spec §4.1 は「`requirements.lock` で版/ハッシュ固定」を規定するが当該ファイルは未作成（Phase 0/1/1.5 を通じ未整備。実際のピンは `pip download` の明示 `==` ＋ wheelhouse 内容で担保）。spec §15 フェーズ2 の明示着手前提は「pyahocorasick の G1 相当 wheel 実証」であり `requirements.lock` 整備ではないため本ゲートはブロックしないが、配備正式化（ハッシュ固定の供給網完全性）には別途整備が必要。Phase 2 計画化時にスコープ判断する。

---

## Phase 2a 着手ゲート記録

- 記録日 (UTC): 2026-05-17
- 検証者: Claude Code（Phase 2a 実装 Task 0）
- Step1: `python -m pytest -q` → **78 passed**（0 failed / 0 error。Phase 1.5 ベースライン緑）
- Step2: `grep -nF 'G1 相当判定: **PASS**'` → 1 行ヒット（本書「Phase 2 着手ゲート（pyahocorasick G1 相当）記録」PASS。spec §4.2 充足）
- Step3: `pyahocorasick 2.1.0` import 可（現環境）
- 判定: **PASS**（Phase 1.5 緑 ＋ pyahocorasick G1 PASS。spec §15 フェーズ2 着手前提充足。Task 1 以降へ着手可）
- 注: `requirements.lock`（spec §4.1）は Phase 3 へ送る（ユーザ決定）。`--memory-limit`/オートマトン分割/`ripgrep`/経路爆発 degrade は Phase 2b。spec §9 は `07e81bb`、§8.1 手順5 は `8c21227` で明確化済（Phase 2a 計画 v4 の入力）。

---

## Phase 2a 完了記録（spec §15 フェーズ2 のうち 2a 範囲）

- 完了確認日 (UTC): 2026-05-17
- コミット範囲: `325ec3e`（Task0 着手ゲート）..`69304a8`（Task11 golden 確定）。実装11コミット（chase/stoplist×2/automaton/walk/provenance/classify/fixedpoint/pipeline/diagnostics/golden）＋本完了記録。
  - 注: 範囲外の `.claude/settings.local.json`（subagent 用スキル権限追記＝Phase 1.5 `7a9ae65` と同種の実装外副作用）は別コミット `feat(settings):` で分離。
- 全テスト結果: **130 passed**（unit / integration / golden / smoke すべて PASS。0 failed / 0 error。Phase 1.5 の 78 ＋ Phase 2a 追加 52）。
- spec 改訂（ユーザ承認・source of truth 維持）: §9 単純パスの「同一シンボル」明確化（`07e81bb`）、§8.1 手順5 ホスト変数文言を手順1/§8.4 と整合（`8c21227`）。
- レビュー経緯: 計画 v1→v4。3巡の独立3並行批判的レビュー（spec適合／アルゴリズム決定性／TDD実行可能性）＋各反映。subagent-driven-development で全タスク実装＋タスク毎2段レビュー（spec準拠→コード品質）APPROVED。

### spec §8/§9/§15（2a 範囲）→ 実装・テスト 対応表

| spec 要件 | 実装 | テスト（緑） |
|---|---|---|
| §8.1 反復・停止性（有限母集合飽和） | `fixedpoint.run_fixedpoint` | `test_fixedpoint::test_相互参照でも有限母集合で飽和し停止する` |
| §8.1 手順1 Pro\*C ホスト変数 非投入 | `chase.extract_chase_symbols`(proc) | `test_chase::test_C定義とconst定数を抽出しProCホスト変数は追跡投入しない` |
| §8.3 静的採否／getter/setter 非投入 | `stoplist.admit`/`partition` | `test_stoplist`（7本） |
| §8.3 大域決定的切り捨て（単調維持） | `fixedpoint._apply_global_cap`/`capped` | `test_fixedpoint::test_大域集合上限超過は決定的に切り捨て診断記録する` |
| §8.2 来歴集約（intro 精密エッジ・偽chain根治） | `fixedpoint`（intro/`is_seed`） | `test_fixedpoint::test_多ホップ…偽直結を生まない`／`test_複数seedで無関係seedからの偽chainを生まない` |
| §8.2 jobs 並列決定性 | `_scan_file`／rel昇順集約 | `test_fixedpoint::test_jobs1とjobsNでindirectキーが完全一致し非空` |
| §8.2 走査・symlink 重複排除・生成コード除外 | `walk.walk_files` | `test_walk`（5本） |
| §9 chain 正規形（07e81bb 明確化）／真の複数経路別行決定性 | `provenance`（単純パス） | `test_provenance`（7本）＋ golden `chain_multipath`（HUB@D 2行・厳密9行） |
| §9 ref_kind×言語表 禁止セル | `chase.extract_chase_symbols` | `test_chase::test_ref_kind言語表の禁止セルは空を返す` |
| §8.4 診断正本（全件性・決定性・max-depth到達記録） | `fixedpoint`/`diagnostics` | `test_diagnostics_phase2`（4本・2回実行一致・jobs決定性確認） |
| §5.1 lang_map の direct/indirect 対称 | `pipeline`/`cli`/`fixedpoint` | `test_pipeline_fixedpoint::test_lang_mapはdirectとindirectで対称に効く` |
| direct/indirect 併合の完全決定性 | `pipeline`（write_tsv 全順序ソート） | `test_pipeline_fixedpoint`（2回一致）＋既存8 golden 不変＋shell_direct/oracle_direct 意図regen（各 indirect:var 1行増・偽行ゼロ） |

### Phase 2b/3 申し送り（spec §15 根拠付き）
- Phase 2b: §8.2 資源 degrade（`--memory-limit` スピル・優先順位・オートマトン分割多パス）、`ripgrep` 一次フィルタ、chain 経路爆発 degrade、bytes ストリーミング化、キーワード横断 walk 診断重複の集約。
- Phase 3: 60GB perf ベースライン、`--resume`、diagnostics 縮約（§10.3）、規模分割 `<keyword>.partNN.tsv`（§9）、`requirements.lock`（§4.1・ユーザ決定）、`--output-encoding`/`--encoding-fallback`/`--use-ripgrep`/`--memory-limit`/`--progress`。
- Phase 2a 既知境界: 字句正規表現抽出（型解決なし＝§8.3 前提）、ASCII 識別子前提（`encoding_utf8` 非ASCII非追跡）、意味的同一性は human 判断（§8.4・intro＋is_seed で偽直結/自己汚染排除）、マスク非対称（抽出=マスク／走査=raw・§7+§8 根拠）、getter 報告量 vs PRD は `--stoplist`/`min-specificity`＋2b で緩和。
- 成果物: 「direct＋多ホップ indirect を偽陽性抑止しつつ `--jobs` 並列でも完全決定的に出し、chain 複数経路を真ダイヤモンド golden で固定した動くツール」。単体でテスト可能・出荷可能。

---

## Phase 2b 着手ゲート記録

- 検証日 (UTC): 2026-05-17 05:24:59 UTC
- 検証者: Claude Code（Phase 2b 着手ゲート Task 0）
- **Step 1**: `python -m pytest -q` → **130 passed**（0 failed / 0 error）。Phase 2a ベースライン全緑確認。
- **Step 2**: Phase 2a 完了記録の存在確認 → `grep -nF '## Phase 2a 完了記録'` → 1 行ヒット（243行目）。spec §15 フェーズ2a 完了済。
- **Step 3**: ripgrep 任意性確認 → `shutil.which('rg')` = `None`（本環境 rg 不在）。ripgrep は任意（`--use-ripgrep` 任意・既定無効・`requires_ripgrep` 隔離）。新規必須依存なし。
  - 注: rg 不在環境では ripgrep 経路テスト skip（CI 等 rg 実体のある環境で `pytest -m requires_ripgrep` を別途必ず実行が Task 11 受入条件）。
- **判定: PASS**（Phase 2a 緑 ＋ ripgrep 任意確認 ＋ 新規必須依存なし）。Phase 2b Task 1 以降へ着手可。

---

## Phase 2b 完了記録（spec §15 フェーズ2 のうち 2b 範囲）

- 完了日 (UTC): 2026-05-17 06:20:20 UTC
- コミット範囲: `41fa1b7`（Task0 着手ゲート）..`c39cfad`（Task10 不変条件契約）の **11 コミット**（gate / budget 50f261d / spill 979ad4f / ripgrep 7627853 / progress 7633b05 / walk 6849937 / Task6 ストリーミング ba204b0 / Task7 degrade p1+p2 24cb02c / Task8 分割 6baf05c / Task9 配線 661a628 / Task10 契約 c39cfad）。本 Task11 完了記録コミットを末尾に追加。なお計画 v5 改訂コミット `ebbda1f` は実装前のプラン改訂（4巡目レビュー反映）で実装範囲外。
- 全テスト結果: **163 passed, 4 skipped**（Phase 2a ベースライン 130 + Phase 2b 追加 33 passed + 4 skipped）、0 failed / 0 error。
  - `python -m pytest -q` → 集計行: `163 passed, 4 skipped in 1.65s`
  - `python -m grep_analyzer --help` → exit 0
  - `python -m pytest tests/golden -q` → 14 passed（不変）
- 4 skipped は全て `@pytest.mark.requires_ripgrep`（`tests/unit/test_ripgrep.py` 3本 + `tests/integration/test_phase2b_invariants.py` 1本）。本環境は `shutil.which('rg')` = None（rg 不在）。

### spec §8.2 L164／Inv 充足チェックリスト対応表

- §8.2 ストリーミング走査（bytes 親非常駐・確定全文1回読み＝C1根治）→ Task6
- §8.2 walk 一回化（重複解消・複数kw決定性・§8.4全件性は kw 毎独立で不変）→ Task5/9/10
- §8.2 任意 ripgrep（walk 上位集合・-a でバイナリ境界統一）→ Task3/9/10（rg 環境受入）
- §8.2 L164 priority-1（§8.3 切り捨て＝唯一の出力変更・max_symbols常設＋--memory-limit連動）→ Task7
- §8.2 L164 priority-2 来歴スピル（生存集合に出力透過）→ Task2/7（graph_spilled）
- §8.2 L164 最終手段オートマトン分割多パス（出力透過＝C2根治）+ --max-passes 上限・実パス数診断 → Task8（automaton_split）
- §8.2 --progress 標準エラー進捗 → Task4/9

### Inv-1〜4 充足の明記

- Inv-1（既定 byte 不変）: `--memory-limit=None` で既存 golden 14・既存 130 byte 完全不変
- Inv-2（priority-1 のみ出力変更で決定的記録）: `--memory-limit` 超過で indirect 決定的減。priority-2/分割透過・出力変更なし
- Inv-3（jobs/memory/ripgrep/複数kw 決定性）: `--memory-limit` 値や `--jobs`・ripgrep 有無等で「出力シンボル集合が変動しうる」が集合内の記録（相対順序含む）は完全決定的
- Inv-4（複数 kw diagnostics 決定性）: 複数 kw walk 重複 dedup の意図変化は spec 仕様・出力 TSV/終了コード/diagnostics（sum）に無影響。個別kw diagnostics も同規則

### rg 環境受入の状態

本環境は rg 不在のため `requires_ripgrep` 4本 skip。**受入条件未充足の申し送り**＝`shutil.which('rg')` が None でない環境（CI 等）で `pytest -m requires_ripgrep` を別途実行し全 PASS を確認・記録すること（Phase 2b 既知境界・Task0/Task11 受入条件）。

### レビュー経緯

計画 v1→v5（4巡の独立3並行批判的レビュー：spec適合/アルゴリズム決定性/TDD実行可能性。v5 で 4巡目の Critical1/High2＝fixedpoint連鎖パッチ置換範囲一意化を根治、5巡目で収束確認）。subagent-driven-development で Task0→11 実装、Task6/7/8/9 は各々 spec準拠レビュー＋コード品質レビューの2段 APPROVED。

### レビューで確認した既知 Minor（非ブロッカー・計画 verbatim 由来）

- Task8 nchunks-grow の off-by-one：best-effort degrade のチャンク数推定がやや少なめになり得るが byte 不変性・決定性に無影響＝spec §9 決定性優先・実バイト厳密化は Phase 3
- Task8 テスト名 `test_memory_limit0は分割スピル切り捨て併発でも…`：memory0 で keep=0→scan_syms 空となり分割不発火だがアサート（2回実行決定性）は有効
- 可読性 Minor：`keep` 変数名重複等。計画の収束済 verbatim 仕様由来で実害なし

### Phase 3 申し送り（計画「Phase 2b の境界」節準拠）

- 60GB perf ベースライン
- 近似 budget の実バイト厳密化
- `--resume` 機能
- diagnostics §10.3 縮約
- 規模分割 `<keyword>.partNN.tsv`
- `requirements.lock` 整備
- `--output-encoding` / `--encoding-fallback`
