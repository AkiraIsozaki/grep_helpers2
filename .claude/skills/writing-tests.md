---
name: writing-tests
description: テストの新規作成・修正時に適用する方針。pytest のテストを書く・直す・追加するときに必ず使用すること。
---

# テストの書き方

> 本ツール（grep_analyzer）の設計は `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md` §11 を参照。本書とspecが齟齬する場合はspecを正とする。

## 基本姿勢
- **古典学派 (Detroit) + TDD** を基本とする。
- リファクタリング耐性と保守性を最優先。
- **how ではなく what**: 観測可能な振る舞いを検証し、内部実装には立ち入らない。

## テストメソッド
- メソッド名は **日本語**。`test_<期待される振る舞い>` の形。
- テスト名を上から並べたら仕様書として読めること（=「動く仕様」）。
- 例: `test_grep行は最左の数字コロン境界で分割する` / `test_型解決依存getterは不動点追跡集合に投入しない` / `test_ProC置換後も行番号は原ソースと一致する` / `test_文字コード判定不能時はlatin1置換し要確認フラグを立てる`

## ケース設計の手順
1. **ブラックボックス** で必要なケースを書き出す。
2. **ホワイトボックス** で内部分岐・境界条件を点検し、抜けを発見する。
3. 抜けを埋めるテストは **再びブラックボックス的に**書く（内部を知らないふりをして外側の仕様で表現）。
4. カバレッジは結果指標であり目標ではない。

## モックの線引き（全層共通）
- **外部 I/O 境界**（ファイル、外部プロセス＝`ripgrep` 等）のみ test double を使う。
- ドメイン層の協調オブジェクト（分類器・走査エンジン・採否ポリシー・来歴集約 等）は原則 **本物**（古典学派）。
- 本ツールに LLM・ネットワークは無い。外部境界はファイルシステムとサブプロセス（任意 `ripgrep`）に限られる。

## テスト層と縄張り
各層は **その層でしか出ない欠陥** を担当する。重複は「遅くて壊れやすいテスト」を増やすだけ。

| 層 | 専属の役割 | やってはいけない |
|---|---|---|
| `tests/unit/`         | 個々の関数・クラスの細かい仕様 | 配線 / I/O / サブプロセス |
| `tests/integration/`  | CLI/API の境界契約・オプション相互作用・エラー経路・実バイナリ連携 | 出力 TSV の全体一致、細かい仕様の網羅 |
| `tests/golden/`       | 実サンプル変換の完全一致による回帰検出 | 個別仕様の確認 |
| `tests/handcrafted/`  | 分類精度を理想出力との差分で測定（ダッシュボード） | pass/fail 判定 / CI 停止 |
| `tests/perf/`         | 大規模合成ツリーでの走査時間ベースライン（ダッシュボード） | pass/fail 判定 / CI 停止 |
| `tests/test_smoke.py` | import + CLI エントリ起動 + tree-sitter ABI 整合の生存確認 | それ以上 |

---

## Integration (`tests/integration/`)

### 役割
**境界/契約確認** が主、配線確認が補助。代表シナリオと回帰は golden に丸投げ。

### モック方針
- 本ツールに LLM は無いため stub 対象は基本無し（CI 安定・再現性はテストデータ固定で担保）。
- ファイル / 通常 subprocess は本物。
- **実 `ripgrep` バイナリを要するテストは `@pytest.mark.requires_ripgrep` で隔離**（実環境でのみ実行。CI に ripgrep が無くても他テストは緑）。

### 呼び出しスタイル
- **既定は in-process** (`from grep_analyzer.cli import main; rc = main(argv)`)
- subprocess は smoke の `--help` 1 本だけ（packaging 検証）

### アサーション
- **検証したい契約だけを点で確認**。1 テスト = 1 契約
- 出力 TSV の全体像確認は **絶対やらない**（golden の縄張り）
- 構造アサート（特定列の存在、`ref_kind`/`confidence` 値、diagnostics カテゴリ）は点アサートで拾えない時のみ
- negative assertion も使う（"stderr に `--source-root` 配下の機密内容が漏れない"、"型解決依存 getter が横展開していない" 等）

### テストデータ
- 既定は **合成された小規模ソースツリー ＋ `input/*.grep` フィクスチャ**（spec §11 の代表ツリー設計に準拠）
- samples に存在しないエッジ（壊れた grep 行、文字コード混在、symlink ループ、巨大ファイル等）のみ最小フィクスチャを動的生成
- unit 専用フィクスチャは integration では使わない

---

## Golden (`tests/golden/`)

| 軸 | 方針 |
|---|---|
| 比較 | 完全一致（テキスト同一）。出力 TSV ＝ 全列の全順序安定ソート済み（spec §9） |
| カバレッジ | 合成代表ツリーを全自動 parametrize（言語×ref_kind 必須網羅、文字コード/多ホップは pairwise） |
| 必須回帰 | 汎用getter横展開抑止 / chain複数経路の決定性 / Pro\*C `EXEC SQL` ホスト変数＋行番号保存 / symlink重複排除 / 文字コード混在（期待判定値を pin）。`category_sub` は初版空固定 |
| 失敗の意味 | 「壊れた」ではなく「変わった」。判定は人間 |
| 更新規律 | 必ず `git diff` で目視レビューしてから regen を commit。反射的 regen は alarm を殺す |
| commit 規約 | `chore(golden): <理由>` |
| 大量 churn | 多数 golden が一斉に動いたら不健全シグナル。即更新せず、**直前の変更を一旦止めて構造を疑う** |
| やらないこと | 個別仕様の検証（unit の縄張り） |

---

## Handcrafted (`tests/handcrafted/`)

| 軸 | 方針 |
|---|---|
| 役割 | 分類精度ターゲット。**ダッシュボード**であって pass/fail ゲートではない |
| CI 失敗 | しない。スコア低下は警告、停止判断は人間 |
| 更新トリガ | **人間レビューで「理想」が変わった時だけ**。コード変更で追従させてはいけない |
| カバレッジ | 任意。全サンプルに handcrafted は不要 |
| 用途 | 理想出力との差分を見ながら分類器（tree-sitterクエリ／正規表現）を直す |
| commit 規約 | `docs(handcrafted): <理由>` |

### Golden との非対称性

| | 更新トリガ |
|---|---|
| Golden | **コード** を直したら追従して更新 |
| Handcrafted | **人間が理想を変えた時だけ** 更新。コードを直しても触らない |

これが層の存在意義。Handcrafted をコード変更に追従させると、コードを直すための北極星が消える。

---

## Perf (`tests/perf/`)

- マーカは **`@pytest.mark.perf`**（Handcrafted と同じく **ダッシュボード・非ゲート・CI 停止しない**）。
- 大規模合成ツリーでの走査時間を spec §8.2 の参照基準（基準ハード・データ規模・目標オーダ）に対し計測し、**回帰検知のベースライン**として記録（絶対 SLA ではない）。
- 本物 60GB は持ち出さない前提。pass/fail 判定はしない。

---

## Smoke (`tests/test_smoke.py`)

- `import grep_analyzer` が通る
- `python -m grep_analyzer --help` が exit 0 を返す（packaging 契約。subprocess を許可する唯一の場所）
- tree-sitter バインディングと言語 grammar の **ABI 整合**（ロード成功）を確認（spec §4.1）
- 以上。実走査は integration / golden に任せる
