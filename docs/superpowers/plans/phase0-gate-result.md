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
