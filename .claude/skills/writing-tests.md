---
name: writing-tests
description: テストの新規作成・修正時に適用する方針。pytest のテストを書く・直す・追加するときに必ず使用すること。
---

# テストの書き方

## 基本姿勢
- **古典学派 (Detroit) + TDD** を基本とする。
- リファクタリング耐性と保守性を最優先。
- **how ではなく what**: 観測可能な振る舞いを検証し、内部実装には立ち入らない。

## テストメソッド
- メソッド名は **日本語**。`test_<期待される振る舞い>` の形。
- テスト名を上から並べたら仕様書として読めること（=「動く仕様」）。
- 例: `test_全角数字プレフィックスはH2と判定する` / `test_テーブルがない場合は空リストを返す`

## ケース設計の手順
1. **ブラックボックス** で必要なケースを書き出す。
2. **ホワイトボックス** で内部分岐・境界条件を点検し、抜けを発見する。
3. 抜けを埋めるテストは **再びブラックボックス的に**書く（内部を知らないふりをして外側の仕様で表現）。
4. カバレッジは結果指標であり目標ではない。

## モックの線引き（全層共通）
- **外部 I/O 境界**（LLM クライアント、ファイル、外部プロセス等）のみ test double を使う。
- ドメイン層の協調オブジェクトは原則 **本物**（古典学派）。

## テスト層と縄張り
各層は **その層でしか出ない欠陥** を担当する。重複は「遅くて壊れやすいテスト」を増やすだけ。

| 層 | 専属の役割 | やってはいけない |
|---|---|---|
| `tests/unit/`         | 個々の関数・クラスの細かい仕様 | 配線 / I/O / サブプロセス |
| `tests/integration/`  | CLI/API の境界契約・オプション相互作用・エラー経路・実バイナリ連携 | 出力 .md の全体一致、細かい仕様の網羅 |
| `tests/golden/`       | 実サンプル変換の完全一致による回帰検出 | 個別仕様の確認 |
| `tests/handcrafted/`  | 理想出力との差分で精度測定（ダッシュボード） | pass/fail 判定 / CI 停止 |
| `tests/test_smoke.py` | import + CLI エントリ起動の生存確認 | それ以上 |

---

## Integration (`tests/integration/`)

### 役割
**境界/契約確認** が主、配線確認が補助。代表シナリオと回帰は golden に丸投げ。

### モック方針
- **LLM client のみ stub**（CI 安定・再現性・コスト・揺らぎ排除）
- ファイル / openpyxl / 通常 subprocess は本物
- LibreOffice / pdftoppm が必要なテストは `@pytest.mark.no_external` で隔離（実環境でのみ実行）

### 呼び出しスタイル
- **既定は in-process** (`from convert_to_md.cli import main; rc = main(argv)`)
- subprocess は smoke の `--help` 1 本だけ（packaging 検証）

### アサーション
- **検証したい契約だけを点で確認**。1 テスト = 1 契約
- 出力 .md の全体像確認は **絶対やらない**（golden の縄張り）
- 構造アサート（YAML キー存在、特定ヘッダ存在）は点アサートで拾えない時のみ
- negative assertion も使う（"stderr に API キーが漏れない" 等）

### テストデータ
- 既定は `samples/*.xlsx`（real sample）
- samples に存在しないエッジ（空シート、壊れた xlsx 等）のみ openpyxl で最小 xlsx を動的生成
- `tests/fixtures/synth.py` の SheetView は **unit 専用**。integration では使わない

---

## Golden (`tests/golden/`)

| 軸 | 方針 |
|---|---|
| 比較 | 完全一致（テキスト同一） |
| カバレッジ | `samples/` を全自動 parametrize |
| 失敗の意味 | 「壊れた」ではなく「変わった」。判定は人間 |
| 更新規律 | 必ず `git diff` で目視レビューしてから regen を commit。反射的 regen は alarm を殺す |
| commit 規約 | `chore(golden): <理由>` |
| 大量 churn | 多数 golden が一斉に動いたら不健全シグナル。即更新せず、**直前の変更を一旦止めて構造を疑う** |
| やらないこと | 個別仕様の検証（unit の縄張り） |

---

## Handcrafted (`tests/handcrafted/`)

| 軸 | 方針 |
|---|---|
| 役割 | 精度ターゲット。**ダッシュボード**であって pass/fail ゲートではない |
| CI 失敗 | しない。スコア低下は警告、停止判断は人間 |
| 更新トリガ | **人間レビューで「理想」が変わった時だけ**。コード変更で追従させてはいけない |
| カバレッジ | 任意。全サンプルに handcrafted は不要 |
| 用途 | `scripts/diff_handcrafted.py` を見ながら detect/handlers を直す |
| commit 規約 | `docs(handcrafted): <理由>` |

### Golden との非対称性

| | 更新トリガ |
|---|---|
| Golden | **コード** を直したら追従して更新 |
| Handcrafted | **人間が理想を変えた時だけ** 更新。コードを直しても触らない |

これが層の存在意義。Handcrafted をコード変更に追従させると、コードを直すための北極星が消える。

---

## Smoke (`tests/test_smoke.py`)

- `import convert_to_md` が通る
- `python -m convert_to_md.cli --help` が exit 0 を返す（packaging 契約。subprocess を許可する唯一の場所）
- 以上。実変換は integration / golden に任せる
