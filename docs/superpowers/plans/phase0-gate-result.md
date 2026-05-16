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

- **`pyahocorasick` 未検証**: spec §4.1 は必須依存に `pyahocorasick`（ネイティブ）を列挙するが、当 Task 0 の確定依存リスト（tree-sitter系＋chardet＋pytest）に含まれないため本ゲートでは wheel 実証していない。`pyahocorasick` を実際に使う後続フェーズ（多シンボル同時走査＝主にフェーズ2 §8.2）に着手する前に、同等の G1 相当検証（cp312・対象 platform の prebuilt wheel 取得可否、sdist-only の場合は §4.2 (a)/(b) 意思決定）を別途実施すること。フェーズ1（決定的コア）は tree-sitter＋chardet で完結するため本懸念は Task 1 着手をブロックしない。
- `wheelhouse/` は未コミット（`.gitignore` 登録）。配備時は本書 Step 2 のコマンドでネット接続環境にて再生成し持ち込む運用。
- 採用 platform タグは `manylinux_2_17_x86_64`（glibc 2.17+ 互換）。稼働先 glibc がこれ未満（極端に古い／musl）の場合は再検証が必要だが、稼働先想定「モダンLinux」では十分。
